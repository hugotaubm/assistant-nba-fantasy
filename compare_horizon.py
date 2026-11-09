"""Compare des réglages de l'optimiseur (horizon de 3 semaines, pénalité des paires d'une même équipe)
sur ton équipe actuelle : transferts conseillés, joueurs alignés par soir et points sur 3 semaines.

    python3 compare_horizon.py
"""
import datetime as dt
import assistant as a

cfg0 = a.lire_config()
boot, fixtures, sched, mt, sources = a.charger(cfg0, False)
gw, gw_suiv, jours, commencee = a.gameweek_courante(boot, dt.datetime.now(dt.timezone.utc))
a.PROCHAIN[0] = jours[0]["id"]
gw_suiv = dict(gw_suiv, events=[e for e in boot["events"] if gw_suiv["start_event"] <= e["id"] <= gw_suiv["stop_event"]])
gw3 = next(p for p in boot["phases"] if p["name"].lower().startswith("gameweek") and p["start_event"] == gw_suiv["stop_event"] + 1)
a.SEMAINE3[0] = [e for e in boot["events"] if gw3["start_event"] <= e["id"] <= gw3["stop_event"]]
joue, matchs = a.construire_calendrier(boot, fixtures, sched)
a.JOUE[0] = joue
a.MALUS_B2B[0] = cfg0["malus_back_to_back"]
saison = a.minutes_saison(boot, False)
joueurs = a.projeter(boot, cfg0, commencee, saison)
try:
    a.defenses(joueurs, saison, matchs, cfg0)
except Exception:
    pass
a.opportunites(joueurs, saison, joue, list(jours) + gw_suiv["events"], cfg0)
equipe, banque, prix_vente, gratuits, cap_dispo, _ = a.mon_equipe(mt, cfg0, joueurs, boot, gw)
nom = lambda q: joueurs[q]["nom"]
variantes = [("actuel (2 semaines)", dict(poids_semaine3=0.001, penalite_meme_equipe=0)),
             ("3 semaines (50 %)", dict(poids_semaine3=0.5, penalite_meme_equipe=0)),
             ("3 semaines + paires 10 pts", dict(poids_semaine3=0.5, penalite_meme_equipe=10)),
             ("3 semaines + paires 25 pts", dict(poids_semaine3=0.5, penalite_meme_equipe=25))]
for titre, v in variantes:
    cfg = dict(cfg0, **v)
    plan, base = a.meilleur_plan(joueurs, equipe, banque, prix_vente, gratuits, cap_dispo, jours, joue, gw_suiv, cfg)
    tr = [f"{e['name'].split(' - ')[-1]} {nom(x)}→{nom(y)}" for e, so, en in plan["transferts"] for x, y in a.paires(so, en, joueurs)]
    tr2 = [f"{e['name'].split(' - ')[-1]} {nom(x)}→{nom(y)}" for e, so, en in plan["transferts_suiv"] for x, y in a.paires(so, en, joueurs)]
    soirs = lambda k: "-".join(str(len(jp["titulaires"])) for jp in plan.get(k, []))
    pts = lambda k: sum(jp["points"] for jp in plan.get(k, []))
    print(f"== {titre}\n   transferts : {', '.join(tr) or 'aucun'} | semaine suivante : {', '.join(tr2) or 'aucun'}")
    print(f"   joueurs par soir : {soirs('plan')} | {soirs('plan2')} | {soirs('plan3')}")
    print(f"   points (non pondérés) : semaine {pts('plan'):.0f} + suivante {pts('plan2'):.0f} + d'après {pts('plan3'):.0f} = {pts('plan') + pts('plan2') + pts('plan3'):.0f}")
