Résumé du projet ALM:
Gestion actif-passif d'un assureur vie, fonds en euros

Objectif:
Évaluer si un assureur vie, qui garantit un taux minimum à ses assurés et les laisse libres de racheter leur contrat, est bien protégé contre les variations de taux, de marchés et de rachats. L'actif de 1 000 M€ (obligations, actions, immobilier, trésorerie) finance 900 M€ de provisions mathématiques réparties en 4 générations de contrats (taux garantis de 0 % à 2,5 %).
Ce qui a été réalisé:
1.	Création des données : un classeur Excel synthétique avec 40 obligations, des actions, de l'immobilier, 400 groupes de contrats, une courbe des taux, un historique 2005-2025 et 27 hypothèses modifiables.
2.	Modèle de projection : simulation de 2 000 scénarios économiques sur 50 ans (taux Hull-White, actions, immobilier), avec participation aux bénéfices, provision pour participation aux excédents et rachats qui dépendent de l'écart entre taux concurrent et taux servi.
3.	Valorisation : calcul de la valeur économique des fonds propres (NAV) et du coût des garanties (TVOG).
4.	Analyse des risques : analyse de l'adossement actif/passif, 9 stress tests et calcul d'un SCR simplifié.
5.	Comparaison de 4 stratégies d'investissement, puis recommandations.
   
Résultats clés:

Indicateur                            	Valeur
NAV déterministe (un seul scénario)	    66,6 M€
NAV stochastique (2 000 scénarios)	    39,7 M€
TVOG : coût des options et garanties	  26,9 M€
Duration actif / passif	                5,8 / 3,8 ans
Baisse des taux de 100 bp	             −17,6 M€
Rachat massif de 40 %	                 −13,4 M€
SCR simplifié	                          35,3 M€
Ratio de couverture (NAV / SCR)	        112,5 %

Trois enseignements:
•	Les garanties coûtent cher : elles absorbent environ 40 % de la valeur calculée avec un seul scénario (66,6 M€ contre 39,7 M€).
•	Le gap de duration est trompeur : l'actif est plus long que le passif, ce qui suggère un risque en cas de hausse des taux. Le modèle stochastique montre l'inverse : c'est la baisse des taux qui détruit le plus de valeur, parce que les garanties deviennent coûteuses.
•	Réduire les actions et allonger les réinvestissements paie : la stratégie combinant les deux fait passer la NAV de 39,7 à 52,2 M€ et le TVOG de 26,9 à 17,9 M€.

Recommandations:
•	Allonger la duration des réinvestissements (15 ans au lieu de 10).
•	Réduire de moitié l'exposition aux actions et à l'immobilier.
•	Conserver une provision pour participation aux excédents élevée et un coussin de liquidité face au risque de rachats massifs.
•	Étudier une couverture contre la baisse des taux (floors, swaptions receveuses).

Limites à garder en tête:
•	Les données sont synthétiques : les chiffres illustrent la méthode et ne décrivent aucun assureur réel.
•	Les frais (0,40 % et 0,80 % de l'encours) ont été choisis dans une fourchette de marché pour obtenir une NAV positive.
•	Le SCR est simplifié et la valorisation se fait en univers risque-neutre : les résultats servent à comparer des options, pas à fixer un capital réglementaire.

Livrables:
rapport_ALM.pdf (rapport complet), donnees_ALM_NV.xlsx, modele_alm.py.
