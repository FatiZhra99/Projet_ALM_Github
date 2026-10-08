"""
Modèle ALM - assureur vie épargne en euros
Projection actif/passif en run-off sur 30 ans, générateur de scénarios économiques Hull-White 1F,
rachats dynamiques, participation aux bénéfices, PPB, stress tests et formule standard simplifiée.
Usage : python modele_alm.py   (lit donnees_ALM.xlsx, écrit resultats_ALM.xlsx + figures PNG)
"""
import numpy as np, pandas as pd, json, os, sys, time
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

DATA = os.environ.get("ALM_DATA", "C:/Users/FATIM/OneDrive/Bureau/Auto_formation/projets personnels/Projet ALM/donnees_ALM_NV.xlsx")
OUTD = os.path.dirname(DATA)

# ------------------------------------------------------------------ données
hyp = pd.read_excel(DATA, sheet_name="Hypothèses")
P = {r["Paramètre"]: r["Valeur"] for _, r in hyp.iterrows()}
for k, v in P.items():
    try: P[k] = float(v)
    except: pass
cv = pd.read_excel(DATA, sheet_name="Courbe_taux")
MATS = cv.iloc[:, 0].values.astype(float); ZANN = cv.iloc[:, 1].values.astype(float)
act = pd.read_excel(DATA, sheet_name="Actifs")
act.columns = ["ID", "cls", "sub", "rating", "cpn", "mat", "nom", "bv", "mv", "dur", "spr", "latent"]
bonds = act[act.cls.str.startswith("Obligations")].reset_index(drop=True)
MVE = act[act.cls == "Actions"].mv.sum(); BVE = act[act.cls == "Actions"].bv.sum()
MVR = act[act.cls == "Immobilier"].mv.sum(); BVR = act[act.cls == "Immobilier"].bv.sum()
CASH0 = act[act.cls == "Monétaire"].mv.sum()
mpt = pd.read_excel(DATA, sheet_name="Passif_ModelPoints")
mpt.columns = ["ID", "seg", "gen", "tmg", "age", "anc", "nb", "pm", "lapse"]
seg = mpt.groupby("seg").agg(tmg=("tmg", "first"), pm=("pm", "sum"), lapse=("lapse", "mean")).sort_values("tmg")
TMG = seg.tmg.values; PM0 = seg.pm.values; LAP0 = seg.lapse.values
H = int(P["horizon"]); TMAX = H + 45
TT = np.arange(TMAX + 1)

# ------------------------------------------------------------------ moteur
def run(n_paths=2000, deterministic=False, shift=0.0, eq_shock=0.0, re_shock=0.0, spread_shock=0.0,
        lapse_mult=1.0, mass_lapse=0.0, reinv_mat=None, eq_cut=0.0, seed=None, keep=False):
    a, sig = P["hw_a"], (0.0 if deterministic else P["hw_sigma"])
    n = 1 if deterministic else n_paths
    reinv = int(reinv_mat or P["maturite_reinvestissement"])
    # courbe zéro-coupon continue (choc parallèle)
    zc = lambda t: np.interp(t, MATS, np.log(1 + ZANN)) + shift
    lnP0 = -zc(TT) * TT
    h = 1e-4
    f0 = zc(TT) + TT * (zc(TT + h) - zc(TT - h)) / (2 * h) + 0 * TT  # forward instantané
    f0[0] = zc(0.0)
    P0 = np.exp(lnP0)
    alpha = f0 + sig ** 2 / (2 * a ** 2) * (1 - np.exp(-a * TT)) ** 2
    # simulation du taux court
    rng = np.random.default_rng(int(P["graine"]) if seed is None else seed)
    if deterministic:
        Z = np.zeros((1, H, 3))
    else:
        half = n // 2
        Zb = rng.standard_normal((half, H, 3)); Z = np.concatenate([Zb, -Zb], axis=0)
    rho, rho2 = P["corr_taux_actions"], P["corr_actions_immo"]
    Zr = Z[:, :, 0]
    Ze = rho * Zr + np.sqrt(1 - rho ** 2) * Z[:, :, 1]
    Zi = rho2 * Ze + np.sqrt(1 - rho2 ** 2) * Z[:, :, 2]
    x = np.zeros((n, H + 1))
    sd = sig * np.sqrt((1 - np.exp(-2 * a)) / (2 * a))
    for t in range(H): x[:, t + 1] = x[:, t] * np.exp(-a) + sd * Zr[:, t]
    r = x + alpha[None, :H + 1]
    # déflateur avec correction de martingale
    D = np.ones((n, H + 1))
    for t in range(H): D[:, t + 1] = D[:, t] * np.exp(-r[:, t])
    for t in range(1, H + 1): D[:, t] *= P0[t] / D[:, t].mean()

    def Pgrid(t, rt):
        """P(t,T) pour T=0..TMAX (valide pour T>=t), forme fermée Hull-White."""
        tau = np.maximum(TT - t, 0.0)
        Bt = (1 - np.exp(-a * tau)) / a if sig > 0 else tau * 0 + (0 if a == 0 else (1 - np.exp(-a * tau)) / a)
        lnp = (lnP0[None, :] - lnP0[t]) + Bt[None, :] * f0[t] \
              - sig ** 2 / (4 * a) * (1 - np.exp(-2 * a * t)) * Bt[None, :] ** 2 - Bt[None, :] * rt[:, None]
        return np.exp(lnp)

    # obligations d'origine : regroupées par spread
    spr = bonds.spr.values + np.where(bonds.spr.values > 0, spread_shock, 0.0)
    gspr = np.unique(spr); N = bonds.nom.values; C = bonds.cpn.values; M = bonds.mat.values.astype(int)
    p_bv = bonds.bv.values / bonds.nom.values
    CFg = np.zeros((len(gspr), TMAX + 1))
    for i in range(len(bonds)):
        g = np.searchsorted(gspr, spr[i])
        CFg[g, 1:M[i] + 1] += N[i] * C[i]; CFg[g, M[i]] += N[i]
    surv_i = lambda t: np.exp(-spr * t)          # flux attendus nets de pertes de défaut (intensité = spread)
    coup = np.array([np.sum(N * C * (M >= t) * surv_i(t)) for t in range(H + 2)])
    matc = np.array([np.sum(N * (M == t) * surv_i(t)) for t in range(H + 2)])
    bv_alive = np.array([np.sum(N * (p_bv + (1 - p_bv) * min(t, m) / m) * (m > t)) for t in range(H + 2)
                         for m in [1]] ) if False else None
    bvu = lambda t, mask_ge: np.sum(N * (p_bv + (1 - p_bv) * np.minimum(t, M) / M) * mask_ge * surv_i(t))
    bv_alive = np.array([bvu(t, M > t) for t in range(H + 2)])
    bv_pre = np.array([bvu(t, M >= t) for t in range(H + 2)])

    def mv_orig(t, Pt):
        out = np.zeros(n)
        tt = np.arange(TMAX + 1)
        for g, s in enumerate(gspr):
            cf = np.where(tt > t, CFg[g], 0.0)
            out += (Pt * np.exp(-s * tt)[None, :]) @ cf
        return out

    sprR = P["spread_reinvestissement"] + spread_shock * 0.5
    def par_coupon(t, Pt, m):
        s = np.arange(t + 1, t + m + 1)
        disc = Pt[:, s] * np.exp(-sprR * (s - t))[None, :]
        return (1 - disc[:, -1]) / disc.sum(axis=1)

    def mv_tr(t, Pt, tr):
        s = np.arange(t + 1, tr["m"] + 1)
        disc = Pt[:, s] * np.exp(-sprR * (s - t))[None, :]
        return tr["n"] * np.exp(-sprR * (t - tr["tk"])) * (tr["c"] * disc.sum(axis=1) + disc[:, -1])

    # états initiaux
    cutE, cutR = eq_cut * MVE, eq_cut * MVR          # ventes décidées avant le choc de marché
    S_e = np.full(n, (MVE - cutE) * (1 + eq_shock)); S_r = np.full(n, (MVR - cutR) * (1 + re_shock))
    BVe = np.full(n, BVE * (1 - eq_cut)); BVr = np.full(n, BVR * (1 - eq_cut))
    cash = np.full(n, CASH0); so = np.ones(n); trs = []
    qe, qr = P["div_actions"], P["loyer_immo"]
    ve, vr = (0.0 if deterministic else P["vol_actions"]), (0.0 if deterministic else P["vol_immo"])
    PM = np.tile(PM0, (n, 1)); PPB = np.full(n, P["ppb_initiale"]); last_cred = np.full(n, P["taux_servi_precedent"])
    P_init = Pgrid(0, r[:, 0])
    A0 = mv_orig(0, P_init).mean() + S_e.mean() + S_r.mean() + CASH0 + cutE + cutR
    if eq_cut > 0:                              # désensibilisation actions/immo -> obligations
        trs.append(dict(n=np.full(n, cutE + cutR), c=par_coupon(0, P_init, reinv), m=reinv, tk=0))
    mt = dict(zc={}, eq={}); S_e0 = MVE * (1 + eq_shock)
    PV_out = np.zeros(n); rec = dict(cred=[], lap=[], cov=[], pm=[], out=[], A=[], ppb=[], div=[])
    for t in range(H):
        Pn = Pgrid(t + 1, r[:, t + 1])
        Pt = Pgrid(t, r[:, t])
        z10 = -np.log(Pt[:, t + 10]) / 10.0
        r_comp = np.maximum(np.exp(z10) - 1 - P["ecart_concurrent"], 0.0)
        # actions / immo
        S_e1 = S_e * np.exp(r[:, t] - np.log(1 + qe) - 0.5 * ve ** 2 + ve * Ze[:, t])
        S_r1 = S_r * np.exp(r[:, t] - np.log(1 + qr) - 0.5 * vr ** 2 + vr * Zi[:, t])
        # revenus financiers
        sv = lambda u, tr: np.exp(-sprR * (u - tr["tk"]))
        coupons = so * coup[t + 1] + sum(tr["n"] * tr["c"] * sv(t + 1, tr) * (tr["m"] >= t + 1) for tr in trs)
        mats_c = so * matc[t + 1] + sum(tr["n"] * sv(t + 1, tr) * (tr["m"] == t + 1) for tr in trs)
        amort = so * (bv_pre[t + 1] - bv_alive[t]) + sum(tr["n"] * (sv(t + 1, tr) - sv(t, tr)) * (tr["m"] >= t + 1) for tr in trs)
        div = qe * S_e1 + qr * S_r1
        cint = cash * (np.exp(r[:, t]) - 1)
        g_e = P["taux_realisation_pvl"] * np.maximum(S_e1 - BVe, 0); g_r = P["taux_realisation_pvl"] * np.maximum(S_r1 - BVr, 0)
        BVe = BVe + g_e; BVr = BVr + g_r
        fin = coupons + amort + div + cint + g_e + g_r
        PMt = PM.sum(axis=1)
        # participation aux bénéfices
        avail = np.maximum(P["ratio_pb"] * fin - P["frais_gestion_encours"] * PMt, 0)
        mand = PM @ TMG
        desired = (np.maximum(TMG[None, :], r_comp[:, None]) * PM).sum(axis=1)
        credit = np.maximum(np.minimum(desired, avail + PPB), mand)
        ppb_new = np.maximum(PPB + avail - credit, 0)
        excess = np.maximum(ppb_new - P["ppb_plafond"] * PMt, 0); credit = credit + excess; ppb_new -= excess
        cseg = TMG[None, :] + ((credit - mand) / PMt)[:, None]
        PMpre = PM * (1 + cseg)
        # rachats dynamiques
        lap = np.clip(LAP0[None, :] * lapse_mult + P["rachat_pente"] * (r_comp - last_cred)[:, None],
                      0.5 * LAP0[None, :] * lapse_mult, P["rachat_plafond"])
        if t == 0 and mass_lapse > 0: lap = np.minimum(lap + mass_lapse, 1.0)
        dec = P["mortalite"]
        claims = (PMpre * (lap + dec)).sum(axis=1)
        PMn = PMpre * (1 - lap - dec)
        expn = P["frais_generaux"] * PMt
        outf = claims + expn
        PV_out += D[:, t + 1] * outf
        # cash et rééquilibrage
        cash = cash + coupons + mats_c + div + cint - outf
        so_ = so
        # valorisation des obligations à t+1 (hors échues)
        mvb = so * mv_orig(t + 1, Pn)
        bvb = so * bv_alive[t + 1]
        for tr in trs:
            if tr["m"] > t + 1:
                mvb = mvb + mv_tr(t + 1, Pn, tr); bvb = bvb + tr["n"] * sv(t + 1, tr)
        buf = P["tresorerie_cible"] * (PMn.sum(axis=1) + ppb_new)
        diff = cash - buf
        buy = np.maximum(diff, 0)
        if buy.max() > 0:
            trs.append(dict(n=buy.copy(), c=par_coupon(t + 1, Pn, reinv), m=t + 1 + reinv, tk=t + 1))
        sell = np.minimum(np.maximum(-diff, 0), mvb)
        fsell = np.where(mvb > 0, sell / np.maximum(mvb, 1e-9), 0.0)
        so = so * (1 - fsell)
        for tr in trs[:-1] if buy.max() > 0 else trs: tr["n"] = tr["n"] * (1 - fsell)
        cash = cash - buy + sell
        mvb_after = mvb * (1 - fsell) + buy
        A = mvb_after + S_e1 + S_r1 + cash
        L = PMn.sum(axis=1) + ppb_new
        rec["cred"].append(credit / PMt); rec["lap"].append((lap * PM).sum(axis=1) / PMt)
        rec["cov"].append(A / L); rec["pm"].append(PMn.sum(axis=1)); rec["out"].append(outf)
        rec["A"].append(A); rec["ppb"].append(ppb_new); rec["div"].append(fin)
        if keep and (t + 1) in (5, 10, 20, 40) and t + 11 <= TMAX:
            mt["zc"][t + 1] = float((D[:, t + 1] * Pn[:, t + 11]).mean() / P0[t + 11])
            mt["eq"][t + 1] = float((D[:, t + 1] * S_e1 * (1 + qe) ** (t + 1)).mean() / S_e0)
        S_e, S_r, PM, PPB, last_cred = S_e1, S_r1, PMn, ppb_new, credit / PMt
    term = D[:, H] * (PM.sum(axis=1) + PPB)
    bel_path = PV_out + term
    res = dict(A0=A0, BEL=bel_path.mean(), NAV=A0 - bel_path.mean(), bel_path=bel_path)
    res["nav_path"] = A0 - bel_path
    if keep:
        res.update({k: np.array(v) for k, v in rec.items()})
        res["D"] = D; res["P0"] = P0; res["r"] = r; res["f0"] = f0; res["ZEq"] = None
        res["mart"] = mt
    return res

def asset_bond_mv(shift):
    zc = lambda t: np.interp(t, MATS, np.log(1 + ZANN)) + shift
    tot = 0.0
    for b in bonds.itertuples():
        s = np.arange(1, int(b.mat) + 1); cf = np.full(len(s), b.cpn); cf[-1] += 1
        tot += b.nom * np.sum(cf * np.exp(-(zc(s) + b.spr) * s))
    return tot

if __name__ == "__main__":
    t0 = time.time(); NP = int(P["nb_scenarios"]); R = {}
    # 1) Contrôles de martingale (déflateur)
    base = run(NP, keep=True)
    R["martingale"] = base["mart"]
    # 2) Scénario central déterministe et stochastique
    det = run(deterministic=True, keep=True)
    R["A0"] = base["A0"]; R["BEL_det"] = det["BEL"]; R["BEL_sto"] = base["BEL"]
    R["NAV_det"] = det["NAV"]; R["NAV_sto"] = base["NAV"]; R["TVOG"] = base["BEL"] - det["BEL"]
    npth = base["nav_path"]
    R["NAV_pct"] = {q: float(np.percentile(npth, q)) for q in (5, 25, 50, 75, 95)}
    cov = base["cov"]
    R["cov_pct_an10"] = {q: float(np.percentile(cov[9], q)) for q in (5, 25, 50, 75, 95)}
    R["taux_servi_moyen_an1"] = float(base["cred"][0].mean())
    R["taux_servi_moy_10ans"] = float(base["cred"][:10].mean())
    R["rachat_moy_an1"] = float(base["lap"][0].mean())
    R["couverture_min10_p5"] = float(np.percentile(cov[:10].min(axis=0), 5))
    R["prob_cov_lt1_10ans"] = float((cov[:10].min(axis=0) < 1).mean())
    # 3) Durations et gap
    d = 0.001
    bm_up, bm_dn, bm0 = asset_bond_mv(d), asset_bond_mv(-d), asset_bond_mv(0)
    dur_bonds = -(bm_up - bm_dn) / (2 * d * bm0)
    bel_up = run(deterministic=True, shift=d)["BEL"]; bel_dn = run(deterministic=True, shift=-d)["BEL"]
    dur_liab = -(bel_up - bel_dn) / (2 * d * det["BEL"])
    A0 = det["A0"]; dollar_A = dur_bonds * bm0
    R.update(dur_bonds=dur_bonds, dur_liab=dur_liab, bonds_mv=bm0, dd_A=dollar_A, dd_L=dur_liab * det["BEL"],
             dd_gap=dollar_A - dur_liab * det["BEL"])
    # 4) Stress tests (mêmes aléas -> variations comparables)
    stress_defs = {
        "Taux +100 bp": dict(shift=0.01), "Taux -100 bp": dict(shift=-0.01),
        "Actions -39 %": dict(eq_shock=-0.39), "Immobilier -25 %": dict(re_shock=-0.25),
        "Spread crédit +100 bp": dict(spread_shock=0.01), "Rachat massif 40 %": dict(mass_lapse=0.40),
        "Rachats +50 %": dict(lapse_mult=1.5), "Rachats -50 %": dict(lapse_mult=0.5),
        "Combiné (taux -100, actions -30, rachats +50 %)": dict(shift=-0.01, eq_shock=-0.30, lapse_mult=1.5)}
    NAV0 = base["NAV"]; st = {}
    for k, kw in stress_defs.items():
        out = run(NP, **kw)
        st[k] = dict(NAV=out["NAV"], dNAV=out["NAV"] - NAV0, A0=out["A0"])
    R["stress"] = st
    R["nav_det_sens"] = dict(up=run(deterministic=True, shift=0.01)["NAV"] - det["NAV"],
                             dn=run(deterministic=True, shift=-0.01)["NAV"] - det["NAV"])
    # 5) SCR formule standard simplifiée
    s = lambda k: max(0.0, -st[k]["dNAV"])
    ir_up, ir_dn = s("Taux +100 bp"), s("Taux -100 bp")
    ir = max(ir_up, ir_dn); down = ir_dn >= ir_up
    mk = {"Taux": ir, "Actions": s("Actions -39 %"), "Immobilier": s("Immobilier -25 %"), "Spread": s("Spread crédit +100 bp")}
    names = list(mk); v = np.array([mk[k] for k in names])
    c = 0.5 if down else 0.0
    corr = np.array([[1, c, c, c], [c, 1, .75, .75], [c, .75, 1, .5], [c, .75, .5, 1]])
    scr_mkt = float(np.sqrt(v @ corr @ v))
    scr_life = max(s("Rachats +50 %"), s("Rachats -50 %"), s("Rachat massif 40 %"))
    bscr = float(np.sqrt(scr_mkt ** 2 + scr_life ** 2 + 2 * 0.25 * scr_mkt * scr_life))
    op = 0.0045 * base["BEL"]
    SCR = bscr + op
    R["SCR"] = dict(modules=mk, marche=scr_mkt, vie=scr_life, BSCR=bscr, op=op, SCR=SCR,
                    solvabilite=NAV0 / SCR, sens_taux_dir="baisse" if down else "hausse")
    # 6) Comparaison de stratégies d'investissement
    strat = {"A. Statu quo": {}, "B. Extension duration (réinvest. 15 ans)": dict(reinv_mat=15),
             "C. Désensibilisation actions/immo (-50 %)": dict(eq_cut=0.5),
             "D. B + C": dict(reinv_mat=15, eq_cut=0.5)}
    SR = {}
    for k, kw in strat.items():
        b0 = run(NP, keep=True, **kw)
        up = run(NP, shift=0.01, **kw)["NAV"] - b0["NAV"]; dn = run(NP, shift=-0.01, **kw)["NAV"] - b0["NAV"]
        eqs = run(NP, eq_shock=-0.39, **kw)["NAV"] - b0["NAV"]
        dt = run(deterministic=True, **kw)
        SR[k] = dict(NAV=b0["NAV"], TVOG=b0["BEL"] - dt["BEL"], d_up=up, d_dn=dn, d_eq=eqs,
                     cred10=float(b0["cred"][:10].mean()), cred_vol=float(b0["cred"][:10].std(axis=1).mean() if False else b0["cred"][:10].mean(axis=1).std()),
                     prob_cov=float((b0["cov"][:10].min(axis=0) < 1).mean()))
    R["strategies"] = SR
    # 7) Calibration des rachats sur l'historique
    h = pd.read_excel(DATA, sheet_name="Historique").iloc[:, :4]
    h.columns = ["an", "oat", "servi", "rachat"]
    X = np.maximum(h.oat - P["ecart_concurrent"], 0) - h.servi
    A_ = np.vstack([np.ones(len(h)), X]).T
    coef, *_ = np.linalg.lstsq(A_, h.rachat.values, rcond=None)
    ss = ((h.rachat - A_ @ coef) ** 2).sum(); st_ = ((h.rachat - h.rachat.mean()) ** 2).sum()
    R["calib_rachat"] = dict(intercept=float(coef[0]), pente=float(coef[1]), r2=float(1 - ss / st_))
    # 8) Gap d'écoulement
    asset_cf = np.array([np.sum(bonds.nom * bonds.cpn * (bonds.mat >= t)) + np.sum(bonds.nom * (bonds.mat == t)) for t in range(1, H + 1)])
    liab_cf = np.array(det["out"]).reshape(-1)
    R["flows"] = dict(asset=asset_cf.tolist(), liab=liab_cf.tolist())
    json.dump(R, open(os.path.join(OUTD, "resultats_ALM.json"), "w"), indent=1, default=float)

    # ------------------------------------------------------------------ figures
    plt.rcParams.update({"font.family": "DejaVu Sans", "axes.spines.top": False, "axes.spines.right": False})
    yrs = np.arange(1, H + 1)
    fig, ax = plt.subplots(figsize=(7, 4)); ax.plot(MATS, ZANN * 100, "o-", color="#1F3864")
    ax.set_xlabel("Maturité (ans)"); ax.set_ylabel("Taux zéro-coupon (%)"); ax.set_title("Courbe des taux de départ (31/12/2025)")
    fig.tight_layout(); fig.savefig(os.path.join(OUTD, "fig1_courbe_taux.png"), dpi=150); plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4.2))
    asset_cf, liab_cf, yrs = asset_cf[:30], liab_cf[:30], yrs[:30]
    ax.bar(yrs - 0.2, asset_cf, 0.4, label="Flux actifs obligataires (coupons + remb.)", color="#2E75B6")
    ax.bar(yrs + 0.2, liab_cf, 0.4, label="Flux passif (prestations + frais), scénario central", color="#C55A11")
    ax.set_xlabel("Année"); ax.set_ylabel("M€"); ax.legend(frameon=False, fontsize=8); ax.set_title("Écoulement actif / passif")
    fig.tight_layout(); fig.savefig(os.path.join(OUTD, "fig2_ecoulement.png"), dpi=150); plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 4)); ax.hist(cov[9], bins=50, color="#2E75B6", alpha=.85)
    ax.axvline(1.0, color="r", ls="--", label="Couverture = 100 %")
    ax.set_xlabel("VM des actifs / (PM + PPB) à 10 ans"); ax.set_ylabel("Fréquence"); ax.legend(frameon=False)
    ax.set_title("Distribution du ratio de couverture à 10 ans"); fig.tight_layout()
    fig.savefig(os.path.join(OUTD, "fig3_couverture_10ans.png"), dpi=150); plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.5, 4)); cr = base["cred"][:15] * 100
    for q, ls in ((5, ":"), (25, "--"), (50, "-"), (75, "--"), (95, ":")):
        ax.plot(range(1, 16), np.percentile(cr, q, axis=1), ls, color="#1F3864", label=f"P{q}")
    ax.set_xlabel("Année"); ax.set_ylabel("Taux servi (%)"); ax.legend(frameon=False, ncol=5, fontsize=8)
    ax.set_title("Taux servi projeté (percentiles)"); fig.tight_layout()
    fig.savefig(os.path.join(OUTD, "fig4_taux_servi.png"), dpi=150); plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4.2)); ks = list(st); vals = [st[k]["dNAV"] for k in ks]
    ax.barh(ks[::-1], vals[::-1], color=["#C00000" if x < 0 else "#548235" for x in vals[::-1]])
    ax.set_xlabel("Variation de NAV (M€)"); ax.set_title("Stress tests : impact sur les fonds propres"); fig.tight_layout()
    fig.savefig(os.path.join(OUTD, "fig5_stress.png"), dpi=150); plt.close(fig)

    fig, axs = plt.subplots(1, 2, figsize=(10, 4)); ks = list(SR)
    axs[0].bar([k[:2] for k in ks], [SR[k]["NAV"] for k in ks], color="#2E75B6"); axs[0].set_title("NAV (M€)")
    w = .25; xs = np.arange(len(ks))
    axs[1].bar(xs - w, [SR[k]["d_up"] for k in ks], w, label="Taux +100 bp"); axs[1].bar(xs, [SR[k]["d_dn"] for k in ks], w, label="Taux -100 bp")
    axs[1].bar(xs + w, [SR[k]["d_eq"] for k in ks], w, label="Actions -39 %"); axs[1].set_xticks(xs); axs[1].set_xticklabels([k[:2] for k in ks])
    axs[1].axhline(0, color="k", lw=.6); axs[1].legend(frameon=False, fontsize=8); axs[1].set_title("Sensibilité de la NAV (M€)")
    fig.tight_layout(); fig.savefig(os.path.join(OUTD, "fig6_strategies.png"), dpi=150); plt.close(fig)
    print(json.dumps(R, indent=1, default=float)); print("durée", round(time.time() - t0, 1), "s")
