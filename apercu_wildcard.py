"""Aperçu de la wildcard de la semaine prochaine : équipe refaite avant le 1er Gameday de la Gameweek
suivante (budget = valeur de revente + banque), comparée à l'équipe actuelle sans transfert.

    python3 apercu_wildcard.py
"""
import datetime as dt
import assistant as a

cfg = a.lire_config()
boot, fixtures, sched, mt, sources = a.charger(cfg, False)
gw, gw_suiv, jours, commencee = a.gameweek_courante(boot, dt.datetime.now(dt.timezone.utc))
ph = lambda debut: next((p for p in boot["phases"] if p["name"].lower().startswith("gameweek") and p["start_event"] == debut), None)
evs = lambda p: [e for e in boot["events"] if p["start_event"] <= e["id"] <= p["stop_event"]]
s1 = gw_suiv; s2 = ph(s1["stop_event"] + 1); s3 = s2 and ph(s2["stop_event"] + 1)
jours1 = evs(s1)
a.PROCHAIN[0] = jours1[0]["id"]
s2 = dict(s2, events=evs(s2)) if s2 else None
a.SEMAINE3[0] = evs(s3) if s3 else []
joue, matchs = a.construire_calendrier(boot, fixtures, sched)
a.JOUE[0] = joue
a.MALUS_B2B[0] = cfg["malus_back_to_back"]
saison = a.minutes_saison(boot, False)
joueurs = a.projeter(boot, cfg, commencee, saison)
try:
    a.defenses(joueurs, saison, matchs, cfg)
except Exception:
    pass
a.opportunites(joueurs, saison, joue, jours1 + (s2 or {}).get("events", []), cfg)
equipe, banque, prix_vente, _, _, _ = a.mon_equipe(mt, cfg, joueurs, boot, gw)
cfg = dict(cfg, temps_max_calcul=240, ecart_optimalite=0.0005)
args = (joueurs, equipe, banque, prix_vente, cfg["transferts_gratuits_par_defaut"], True, jours1, joue, s2, cfg)
garder = a.optimiser(*args, transferts=False)
wc = a.optimiser(*args, transferts=True, libre=True, joker=True)
nom = lambda q: f"{joueurs[q]['nom']} ({joueurs[q]['equipe']}, {joueurs[q]['prix'] / 10:.1f} M$, {joueurs[q]['proj']:.0f} pts/match)"
pts = lambda r: sum(jp["points"] for jp in r["plan"])
print(f"Wildcard avant {jours1[0]['name']} — budget {(banque + sum(prix_vente.get(q, joueurs[q]['prix']) for q in equipe)) / 10:.1f} M$")
print("ÉQUIPE :", " | ".join(nom(q) for q in sorted(wc["depart"], key=lambda q: (joueurs[q]["poste"], -joueurs[q]["prix"]))))
print("Sortent :", ", ".join(joueurs[q]["nom"] for q in equipe if q not in wc["depart"]) or "aucun")
print("Gardés :", ", ".join(joueurs[q]["nom"] for q in equipe if q in wc["depart"]) or "aucun")
print("Par soir (wildcard / équipe actuelle) :")
for jw, jg in zip(wc["plan"], garder["plan"]):
    print(f"  {jw['event']['name'].split(' - ')[-1]} : {len(jw['titulaires'])} joueurs ~{jw['points']:.0f} pts"
          + (f" (C {joueurs[jw['capitaine']]['nom']})" if jw["capitaine"] else "") + f" / {len(jg['titulaires'])} joueurs ~{jg['points']:.0f} pts")
print(f"Semaine : ~{pts(wc):.0f} pts avec la wildcard contre ~{pts(garder):.0f} sans ({pts(wc) - pts(garder):+.0f})")
print(f"Semaine d'après (sans transfert) : ~{sum(jp['points'] for jp in wc['plan2']):.0f} contre ~{sum(jp['points'] for jp in garder['plan2']):.0f}")
