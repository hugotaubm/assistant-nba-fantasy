"""Diagnostic : détail de la projection de quelques joueurs (pourquoi tel joueur est projeté à X).

    python3 diag.py L.Doncic V.Wembanyama
"""
import datetime as dt, json, sys
import assistant as a

cfg = a.lire_config()
boot, fixtures, sched, mt, sources = a.charger(cfg, False)
gw, gw_suiv, jours, commencee = a.gameweek_courante(boot, dt.datetime.now(dt.timezone.utc))
a.PROCHAIN[0] = jours[0]["id"]
joue, matchs = a.construire_calendrier(boot, fixtures, sched)
a.JOUE[0] = joue
a.MALUS_B2B[0] = cfg["malus_back_to_back"]
saison = a.minutes_saison(boot, False)
joueurs = a.projeter(boot, cfg, commencee, saison)
priors = json.loads((a.ICI / "priors.json").read_text(encoding="utf-8"))["joueurs"]
el = {e["id"]: e for e in boot["elements"]}
noms = [x.lower() for x in sys.argv[1:]] or ["l.doncic", "v.wembanyama"]
for q, p in joueurs.items():
    if p["nom"].lower() not in noms:
        continue
    e, s, v = el[q], saison.get(q, {}), priors.get(str(q), {})
    print(f"{p['nom']} ({p['equipe']}, {p['prix'] / 10} M$) : projection {p['proj']:.1f} pts/match | fiabilité {p['fiabilite']:.3f} "
          f"| dispo {p['dispo']} | calib {p['calib']:.3f} (groupe {p['rang']}, rang ESPN {p['rang_poste']}) | b2b {p['b2b']}")
    print(f"   avant-saison {v.get('fppg')} (minutes prévues {v.get('min_proj')}) | saison : {s.get('joues')} matchs sur {s.get('matchs_equipe')}, "
          f"{(s.get('minutes', 0) / max(s.get('joues', 1), 1)):.1f} min | ppg du jeu {float(e.get('points_per_game') or 0) / 10:.1f} | forme {float(e.get('form') or 0) / 10:.1f}")
    print(f"   derniers matchs : {[m[1] for m in s.get('matchs', [])][-8:]}")
    for ev in jours[:4]:
        d = (a.z(ev["deadline_time"]) - dt.timedelta(hours=4)).date()
        print(f"   {ev['name']} : {a.ev_jour(p, ev['id'], joue, d):.1f} pts attendus "
              f"(adversaire {a.ADVERSAIRE.get((q, ev['id']), '-') if hasattr(a, 'ADVERSAIRE') else '-'})")
