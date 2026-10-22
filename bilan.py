"""Bilan des journées déjà jouées : où sont partis les points ?

    python3 bilan.py            # écrit le bilan sur la sortie standard

Pour chaque Gameday terminé :
  - ton score, la moyenne des joueurs et le meilleur score ;
  - tes 10 joueurs : titulaire ou banc, minutes, points réels, points projetés ;
  - le meilleur cinq possible avec ton effectif (après coup) : points laissés sur le banc ;
Puis, sur toute la ligue, la qualité des projections : biais, erreur moyenne, joueurs projetés
qui n'ont pas joué, plus grosses erreurs, et vérification du barème de points.
"""
import json, statistics as st, urllib.request
from pathlib import Path

ICI = Path(__file__).resolve().parent
API = "https://nbafantasy.nba.com/api/"
UA = {"User-Agent": "Mozilla/5.0 (assistant-nba-fantasy perso)"}


def get(chemin):
    req = urllib.request.Request(API + chemin, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def points_formule(s):
    # barème utilisé pour les projections (maj_priors.py)
    return s.get("points", 0) + 1.2 * s.get("rebounds", 0) + 1.5 * s.get("assists", 0) \
        + 3 * s.get("steals", 0) + 3 * s.get("blocks", 0)


def meilleur_cinq(liste):
    """liste = [(points, poste)] → meilleur total avec 5 titulaires max, 3 max par poste."""
    best = 0
    for n1 in range(0, 4):
        for n2 in range(0, 4):
            if n1 + n2 > 5:
                continue
            a = sorted((p for p, pos in liste if pos == 1), reverse=True)[:n1]
            b = sorted((p for p, pos in liste if pos == 2), reverse=True)[:n2]
            best = max(best, sum(a) + sum(b))
    return best


def main():
    cfg = json.loads((ICI / "config.json").read_text(encoding="utf-8"))
    eid = cfg.get("id_equipe")
    boot = get("bootstrap-static/")
    priors = json.loads((ICI / "priors.json").read_text(encoding="utf-8"))["joueurs"]
    el = {e["id"]: e for e in boot["elements"]}
    eq = {t["id"]: t["short_name"] for t in boot["teams"]}
    finis = [e for e in boot["events"] if e.get("finished") or e.get("data_checked")]
    if not finis:
        print("Aucun Gameday terminé pour l'instant.")
        return
    proj = lambda pid: priors.get(str(pid), {}).get("fppg", 2.59 * el[pid]["now_cost"] / 10 + 1.4)
    nom = lambda pid: f"{el[pid]['web_name']} ({eq[el[pid]['team']]})"

    tous = []          # (pid, event, proj, réel, minutes, points du jeu, points formule)
    exemple = None
    print("=" * 70)
    print("BILAN DES GAMEDAYS JOUÉS")
    print("=" * 70)
    for e in finis:
        live = get(f"event/{e['id']}/live/")
        stats = {x["id"]: x["stats"] for x in live["elements"]}
        exemple = exemple or next((s for s in stats.values() if s.get("minutes")), None)
        fixtures = get(f"fixtures/?event={e['id']}")
        equipes_jouent = {f["team_h"] for f in fixtures} | {f["team_a"] for f in fixtures}
        for pid, s in stats.items():
            if pid in el and el[pid]["team"] in equipes_jouent:
                tous.append((pid, e["id"], proj(pid), s.get("total_points", 0) / 10, s.get("minutes", 0),
                             s.get("total_points", 0), points_formule(s)))
        print(f"\n--- {e['name']} : moyenne des joueurs {e.get('average_entry_score', 0) / 10:.1f} | "
              f"meilleur {e.get('highest_score', 0) / 10:.1f}")
        if not eid:
            continue
        try:
            pk = get(f"entry/{eid}/event/{e['id']}/picks/")
        except Exception as ex:
            print(f"  (ton équipe n'est pas lisible pour ce Gameday : {ex})")
            continue
        h = pk.get("entry_history", {})
        print(f"  Ton score : {h.get('points', 0) / 10:.1f} | banc : {h.get('points_on_bench', 0) / 10:.1f} | "
              f"rang : {h.get('rank')} | transferts : {h.get('event_transfers')} (coût {h.get('event_transfers_cost')})")
        reel, proj_tit, liste, tit_sans_cap = 0.0, 0.0, [], 0.0
        for p in sorted(pk["picks"], key=lambda p: p["position"]):
            pid = p["element"]
            s = stats.get(pid, {})
            joue = el[pid]["team"] in equipes_jouent
            pts = s.get("total_points", 0) / 10
            liste.append((pts, el[pid]["element_type"]))
            role = "TITULAIRE" if p["multiplier"] > 0 else "banc"
            cap = " (CAPITAINE x%d)" % p["multiplier"] if p.get("is_captain") and p["multiplier"] > 1 else ""
            pr = proj(pid) if joue else 0
            if p["multiplier"] > 0:
                reel += pts * p["multiplier"]
                tit_sans_cap += pts
                proj_tit += pr * p["multiplier"]
            etat = f"{s.get('minutes', 0):>2} min" if joue else "pas de match"
            print(f"  {role:<9} {nom(pid):<28} {etat:<13} réel {pts:5.1f} | projeté {pr:5.1f}{cap}")
        best = meilleur_cinq(liste)
        print(f"  → Titulaires : {reel:.1f} pts réels pour {proj_tit:.1f} projetés ({reel - proj_tit:+.1f}).")
        print(f"  → Meilleur cinq possible après coup : {best:.1f} pts (hors capitaine), "
              f"soit {best - tit_sans_cap:.1f} pts laissés sur le banc.")

    # Qualité des projections sur toute la ligue (joueurs dont l'équipe jouait)
    print("\n" + "=" * 70)
    print("QUALITÉ DES PROJECTIONS (toute la ligue, joueurs projetés ≥ 20 pts)")
    print("=" * 70)
    gros = [t for t in tous if t[2] >= 20]
    joues = [t for t in gros if t[4] > 0]
    absents = [t for t in gros if t[4] == 0]
    if joues:
        ecarts = [t[3] - t[2] for t in joues]
        print(f"Matchs joués : {len(joues)} | biais moyen (réel − projeté) : {st.mean(ecarts):+.1f} pts | "
              f"erreur moyenne : {st.mean(abs(x) for x in ecarts):.1f} pts")
        if len(joues) > 2:
            print(f"Corrélation projeté/réel : {st.correlation([t[2] for t in joues], [t[3] for t in joues]):.2f}")
        mins = [t[4] for t in joues]
        print(f"Minutes moyennes : {st.mean(mins):.1f}")
    print(f"Projetés ≥ 20 pts mais 0 minute (absents / pas utilisés) : {len(absents)} sur {len(gros)}")
    for t in sorted(absents, key=lambda t: -t[2])[:12]:
        print(f"  - {nom(t[0])} (event {t[1]}) : projeté {t[2]:.1f}, statut actuel {el[t[0]]['status']}, "
              f"news : {(el[t[0]]['news'] or '-')[:60]}")
    print("Plus grosses surestimations :")
    for t in sorted(joues, key=lambda t: t[3] - t[2])[:12]:
        print(f"  - {nom(t[0])} (event {t[1]}) : projeté {t[2]:.1f}, réel {t[3]:.1f} en {t[4]} min")
    print("Plus grosses sous-estimations :")
    for t in sorted(joues, key=lambda t: t[2] - t[3])[:8]:
        print(f"  - {nom(t[0])} (event {t[1]}) : projeté {t[2]:.1f}, réel {t[3]:.1f} en {t[4]} min")

    # Barème : les points du jeu correspondent-ils à notre formule ?
    print("\nVérification du barème (points du jeu vs formule des projections) :")
    if exemple:
        print("  Statistiques fournies par le jeu :", sorted(exemple.keys()))
    ok = [t for t in tous if t[4] > 0]
    if ok:
        diff = [t[5] / 10 - t[6] for t in ok]
        print(f"  Écart moyen jeu − formule : {st.mean(diff):+.2f} pts (sur {len(ok)} matchs) ; "
              f"écart absolu moyen {st.mean(abs(x) for x in diff):.2f}")
        rapports = [t[5] / t[6] for t in ok if t[6] > 5]
        if rapports:
            print(f"  Rapport points du jeu / formule (médiane) : {st.median(rapports):.2f}")


if __name__ == "__main__":
    main()
