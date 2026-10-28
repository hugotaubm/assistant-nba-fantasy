"""Bilan des journées déjà jouées : où sont partis les points ?

    python3 bilan.py            # écrit le bilan sur la sortie standard

Pour chaque Gameday terminé :
  - ton score, la moyenne des joueurs et le meilleur score ;
  - tes 10 joueurs : titulaire ou banc, minutes, points réels, points projetés ;
  - le meilleur cinq possible avec ton effectif (après coup) : points laissés sur le banc ;
Puis, sur toute la ligue, la qualité des projections : biais, erreur moyenne, joueurs projetés
qui n'ont pas joué, plus grosses erreurs, et vérification du barème de points.

Calibration : assistant.py enregistre avant chaque deadline les points attendus par le modèle
(rapport/projections/<event>.json, sans calibration). Ici, on les compare aux points réels par groupe
de rang (titulaire, 1er remplaçant, fin de rotation) et on écrit rapport/calibration.json, que
assistant.py applique ensuite aux projections. Les facteurs sont tirés vers 1 tant qu'il y a peu de
matchs (CALIB_K) et bornés (CALIB_MIN, CALIB_MAX).
"""
import json, statistics as st, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ICI = Path(__file__).resolve().parent
API = "https://nbafantasy.nba.com/api/"
UA = {"User-Agent": "Mozilla/5.0 (assistant-nba-fantasy perso)"}
CALIB_K = 400                  # pts projetés « fictifs » à 100 % : environ 15 matchs avant de trop bouger
CALIB_MIN, CALIB_MAX = 0.75, 1.15


def projections_modele(event_id):
    try:
        return json.loads((ICI / "rapport" / "projections" / f"{event_id}.json").read_text(encoding="utf-8"))["projections"]
    except Exception:
        return None


def get(chemin):
    req = urllib.request.Request(API + chemin, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def points_formule(s):
    # barème utilisé pour les projections (maj_priors.py)
    return s.get("points_scored", s.get("points", 0)) + 1.2 * s.get("rebounds", 0) + 1.5 * s.get("assists", 0) \
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
    # Gameday terminé : validé par le jeu, ou deadline passée et tous ses matchs finis (le jeu ne le
    # valide que quelques heures plus tard)
    maintenant = datetime.now(timezone.utc)
    finis = []
    for e in boot["events"]:
        if e.get("finished") or e.get("data_checked"):
            finis.append(e)
        elif datetime.fromisoformat(e["deadline_time"].replace("Z", "+00:00")) < maintenant:
            fx = get(f"fixtures/?event={e['id']}")
            if fx and all(f.get("finished") or f.get("finished_provisional") for f in fx):
                finis.append(e)
    if not finis:
        print("Aucun Gameday terminé pour l'instant.")
        return
    proj = lambda pid: priors.get(str(pid), {}).get("fppg", 2.59 * el[pid]["now_cost"] / 10 + 1.4)
    nom = lambda pid: f"{el[pid]['web_name']} ({eq[el[pid]['team']]})"

    tous = []          # (pid, event, proj, réel, minutes, points du jeu, points formule)
    soirees = []       # tes soirées, pour le graphique de la page (rapport/soirees.json)
    calib = {}         # groupe → [réel, projeté par le modèle, matchs]
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
        modele = projections_modele(e["id"])
        if modele:
            for pid_s, (v, grp) in modele.items():
                c = calib.setdefault(grp, [0.0, 0.0, 0])
                c[0] += stats.get(int(pid_s), {}).get("total_points", 0) / 10
                c[1] += v
                c[2] += 1
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
        soirees.append(dict(event=e["id"], nom=e["name"], date=e["deadline_time"][:10], score=h.get("points", 0) / 10,
                            moyenne=e.get("average_entry_score", 0) / 10, meilleur=e.get("highest_score", 0) / 10,
                            rang=h.get("rank")))
        print(f"  Ton score : {h.get('points', 0) / 10:.1f} | banc : {h.get('points_on_bench', 0) / 10:.1f} | "
              f"rang : {h.get('rank')} | transferts : {h.get('event_transfers')} (coût {h.get('event_transfers_cost')})")
        # Remplacements automatiques du jeu (un titulaire à 0 minute remplacé par un joueur du banc)
        subs = pk.get("automatic_subs") or []
        entres = {a["element_in"] for a in subs}
        sortis = {a["element_out"] for a in subs}
        for a in subs:
            print(f"  Remplacement automatique : {nom(a['element_out'])} → {nom(a['element_in'])}")
        reel, proj_tit, liste, tit_sans_cap = 0.0, 0.0, [], 0.0
        for p in sorted(pk["picks"], key=lambda p: p["position"]):
            if p["element"] in entres and p["multiplier"] == 0:
                p = dict(p, multiplier=1)
            elif p["element"] in sortis:
                p = dict(p, multiplier=0)
            pid = p["element"]
            s = stats.get(pid, {})
            joue = el[pid]["team"] in equipes_jouent
            pts = s.get("total_points", 0) / 10
            liste.append((pts, el[pid]["element_type"]))
            role = ("ENTRÉ" if p["element"] in entres else "TITULAIRE") if p["multiplier"] > 0 else (
                "SORTI" if p["element"] in sortis else "banc")
            cap = " (CAPITAINE x%d)" % p["multiplier"] if p.get("is_captain") and p["multiplier"] > 1 else ""
            pr = (modele.get(str(pid), [0])[0] if modele else proj(pid)) if joue else 0
            if p["multiplier"] > 0:
                reel += pts * p["multiplier"]
                tit_sans_cap += pts
                proj_tit += pr * p["multiplier"]
            etat = f"{s.get('minutes', 0):>2} min" if joue else "pas de match"
            print(f"  {role:<9} {nom(pid):<28} {etat:<13} réel {pts:5.1f} | projeté {pr:5.1f}{cap}")
        best = meilleur_cinq(liste)
        print(f"  → Titulaires : {reel:.1f} pts réels pour {proj_tit:.1f} projetés ({reel - proj_tit:+.1f}) "
              f"[{'projection du modèle' if modele else 'projection d avant-saison, modèle non enregistré'}].")
        print(f"  → Meilleur cinq possible après coup : {best:.1f} pts (hors capitaine), "
              f"soit {best - tit_sans_cap:.1f} pts laissés sur le banc.")

    if soirees:
        (ICI / "rapport" / "soirees.json").write_text(json.dumps(soirees, ensure_ascii=False), encoding="utf-8")

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
    def groupe(titre, cle):
        print(titre)
        par = {}
        for t in gros:
            par.setdefault(cle(t), []).append(t)
        for k in sorted(par, key=str):
            g = par[k]
            j = [t for t in g if t[4] > 0]
            if not j:
                continue
            print(f"  {k:<22} {len(g):>3} matchs | 0 min : {len(g) - len(j):>2} | biais {st.mean(t[3] - t[2] for t in j):+5.1f} "
                  f"| réel/projeté {sum(t[3] for t in j) / sum(t[2] for t in j):.2f} | minutes {st.mean(t[4] for t in j):4.1f}")
    prix = lambda t: el[t[0]]["now_cost"] / 10
    groupe("Par prix :", lambda t: "< 7 M$" if prix(t) < 7 else "7-10 M$" if prix(t) < 10 else "10-15 M$" if prix(t) < 15 else "≥ 15 M$")
    rang = lambda t: priors.get(str(t[0]), {}).get("rang_poste")
    groupe("Par rang dans la hiérarchie ESPN (1 = titulaire) :", lambda t: f"rang {rang(t)}" if rang(t) else "rang inconnu")
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

    # Calibration à partir des projections réellement utilisées par le modèle
    print("\n" + "=" * 70)
    print("CALIBRATION DU MODÈLE (points réels / points attendus, par rang)")
    print("=" * 70)
    facteurs = {}
    for grp, (r, pr_, n) in sorted(calib.items()):
        f = min(CALIB_MAX, max(CALIB_MIN, (r + CALIB_K) / (pr_ + CALIB_K)))
        facteurs[grp] = round(f, 3)
        print(f"  rang {grp:<3} : {n:>4} joueurs-matchs | réel {r:7.0f} / attendu {pr_:7.0f} = {r / pr_ if pr_ else 0:.2f} "
              f"→ facteur appliqué {f:.3f}")
    if facteurs:
        (ICI / "rapport" / "calibration.json").write_text(json.dumps(
            {"facteurs": facteurs, "detail": {g: [round(a, 1), round(b, 1), n] for g, (a, b, n) in calib.items()},
             "k": CALIB_K}, ensure_ascii=False), encoding="utf-8")
    else:
        print("  Pas encore de projections du modèle enregistrées : la calibration démarre au prochain Gameday.")

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



def ligue(cfg):
    """Ton classement dans ta ligue (config "ligue_id"), gardé jour après jour dans rapport/ligue.json.
    Le dépôt et la page sont publics : on ne garde aucun nom (ni de joueur ni d'équipe) des autres membres."""
    lid, eid = cfg.get("ligue_id"), cfg.get("id_equipe")
    if not (lid and eid):
        return
    print("\n" + "=" * 70)
    resultats, nom_ligue, page = [], "", 1
    while page <= 50:
        d = get(f"leagues-classic/{lid}/standings/?page_standings={page}")
        nom_ligue = d.get("league", {}).get("name", "")
        resultats += d.get("standings", {}).get("results", [])
        if not d.get("standings", {}).get("has_next"):
            break
        page += 1
    moi = next((r for r in resultats if r["entry"] == eid), None)
    print(f"LIGUE {nom_ligue.upper()}")
    print("=" * 70)
    if not moi:
        print("  Ton équipe n'apparaît pas dans le classement de cette ligue.")
        return
    tri = sorted(resultats, key=lambda r: r["rank"])
    premier = tri[0]
    devant = next((r for r in reversed(tri) if r["rank"] < moi["rank"]), None)
    derriere = next((r for r in tri if r["rank"] > moi["rank"]), None)
    evol = (moi.get("last_rank") or moi["rank"]) - moi["rank"]
    print(f"  Rang : {moi['rank']} / {len(tri)}"
          + (f" ({'+' if evol > 0 else ''}{evol} depuis la dernière journée)" if moi.get("last_rank") else "")
          + f" | total {moi['total'] / 10:.0f} pts | dernière journée {moi.get('event_total', 0) / 10:.0f} pts")
    if premier["entry"] != eid:
        print(f"  Écart avec le 1er : {(premier['total'] - moi['total']) / 10:.0f} pts")
    if devant:
        print(f"  Écart avec le rang juste devant ({devant['rank']}e) : {(devant['total'] - moi['total']) / 10:.0f} pts")
    if derriere:
        print(f"  Avance sur le rang juste derrière ({derriere['rank']}e) : {(moi['total'] - derriere['total']) / 10:.0f} pts")
    chemin = ICI / "rapport" / "ligue.json"
    try:
        hist = json.loads(chemin.read_text(encoding="utf-8"))
    except Exception:
        hist = {"historique": []}
    point = {"date": datetime.now().strftime("%Y-%m-%d"), "rang": moi["rank"], "nb": len(tri), "total": moi["total"] / 10,
             "ecart_premier": (premier["total"] - moi["total"]) / 10,
             "ecart_devant": (devant["total"] - moi["total"]) / 10 if devant else 0}
    hist["historique"] = [h for h in hist["historique"] if h["date"] != point["date"]] + [point]
    # Chips déjà joués (wildcard, All-Star = « rich », capitaine…) par les équipes devant toi, d'après
    # l'historique public de chaque équipe, une fois par jour. Seuls les totaux sont gardés.
    jk = hist.get("jetons") or {}
    if jk.get("date") != point["date"]:
        devant_ids = [r["entry"] for r in tri if r["rank"] < moi["rank"]]
        par_chip, lus = {}, 0
        for k, e_id in enumerate(devant_ids):
            try:
                chips = get(f"entry/{e_id}/history/").get("chips", [])
            except Exception:
                continue
            lus += 1
            for nom_chip in {c.get("name") for c in chips}:
                d_ = par_chip.setdefault(nom_chip, {"equipes": 0, "par_event": {}})
                d_["equipes"] += 1
                ev = max(c.get("event") or 0 for c in chips if c.get("name") == nom_chip)
                d_["par_event"][str(ev)] = d_["par_event"].get(str(ev), 0) + 1
            if k % 10 == 9:
                time.sleep(1)   # ménage le site
        jk = dict(date=point["date"], devant=len(devant_ids), lus=lus, par_chip=par_chip)
    w = (jk.get("par_chip") or {}).get("wildcard", {})
    jokers = dict(date=jk.get("date"), devant=jk.get("devant"), lus=jk.get("lus"), joues=w.get("equipes", 0),
                  par_event=w.get("par_event", {}))
    # Joueurs possédés par les équipes devant toi (composition publique du dernier Gameday commencé),
    # une fois par Gameday. Seuls les totaux par joueur NBA sont gardés.
    pos = hist.get("possession") or {}
    try:
        boot = get("bootstrap-static/")
        maint = datetime.now(timezone.utc)
        passes = [e for e in boot["events"] if datetime.fromisoformat(e["deadline_time"].replace("Z", "+00:00")) < maint]
        ev_cour = max(passes, key=lambda e: e["id"])["id"] if passes else None
    except Exception:
        boot, ev_cour = None, None
    if ev_cour and (pos.get("event") != ev_cour or pos.get("date") != point["date"]):
        devant_ids = [r["entry"] for r in tri if r["rank"] < moi["rank"]]
        compte, capitaines, lus = {}, {}, 0
        for k, e_id in enumerate(devant_ids):
            try:
                pk = get(f"entry/{e_id}/event/{ev_cour}/picks/")
            except Exception:
                continue
            lus += 1
            for p_ in pk.get("picks", []):
                compte[str(p_["element"])] = compte.get(str(p_["element"]), 0) + 1
                if p_.get("is_captain"):
                    capitaines[str(p_["element"])] = capitaines.get(str(p_["element"]), 0) + 1
            if k % 10 == 9:
                time.sleep(1)
        pos = dict(event=ev_cour, date=point["date"], lus=lus, compte=compte, capitaines=capitaines)
    hist.update(nom=nom_ligue, dernier=point, jokers=jokers, jetons=jk, possession=pos)
    chemin.write_text(json.dumps(hist, ensure_ascii=False), encoding="utf-8")
    if pos.get("lus") and boot:
        el = {str(e["id"]): e for e in boot["elements"]}
        eqs = {t["id"]: t["short_name"] for t in boot["teams"]}
        top = sorted(pos["compte"].items(), key=lambda kv: -kv[1])[:15]
        print(f"  Joueurs les plus présents chez les {pos['lus']} équipes devant toi (Gameday {pos['event']}) : "
              + ", ".join(f"{el[k]['web_name']} ({eqs[el[k]['team']]}) {v}" for k, v in top if k in el))
    noms_chips = {"wildcard": "Wildcard", "rich": "All-Star", "phcapt": "Capitaine"}
    # Le capitaine (phcapt) se rejoue chaque semaine : son décompte « déjà joué » n'apprend rien, on ne l'affiche pas.
    for nom_chip, d_ in sorted((jk.get("par_chip") or {}).items()):
        if nom_chip == "phcapt":
            continue
        print(f"  {noms_chips.get(nom_chip, nom_chip)} : déjà joué par {d_['equipes']} des {jk['lus']} équipes devant toi "
              f"({100 * d_['equipes'] / jk['lus']:.0f} %) ; par Gameday : "
              + ", ".join(f"event {k} : {v}" for k, v in sorted(d_["par_event"].items(), key=lambda kv: int(kv[0]))))
    if jk.get("lus") and "rich" not in (jk.get("par_chip") or {}):
        print(f"  All-Star : joué par aucune des {jk['lus']} équipes devant toi")



def statuts_du_jeu():
    """Ce que le jeu fournit pour les joueurs incertains ou blessés (statut, chances de jouer, news)."""
    boot = get("bootstrap-static/")
    eq = {t["id"]: t["short_name"] for t in boot["teams"]}
    print("\n" + "=" * 70)
    print("STATUTS DU JEU (joueurs non disponibles à 100 %)")
    print("=" * 70)
    comptes = {}
    for e in boot["elements"]:
        if e["status"] == "a" and not e.get("news"):
            continue
        cle = (e["status"], e.get("chance_of_playing_this_round"), e.get("chance_of_playing_next_round"))
        comptes.setdefault(cle, []).append(f"{e['web_name']} ({eq[e['team']]}) : {(e.get('news') or '-')[:70]}")
    for (st_, c1, c2), l in sorted(comptes.items(), key=lambda kv: -len(kv[1])):
        print(f"  statut {st_} | chances ce Gameday {c1} | prochain {c2} : {len(l)} joueurs")
        for x in l[:4]:
            print(f"      {x}")



def comparer_scenario(cfg):
    """« Et si… » : points réels d'un scénario enregistré (rapport/scenario_wildcard.json : titulaires et
    capitaine par Gameday) comparés à ceux de ton équipe réelle, Gameday par Gameday (y compris en cours)."""
    chemin = ICI / "rapport" / "scenario_wildcard.json"
    eid = cfg.get("id_equipe")
    if not chemin.exists() or not eid:
        return
    sc = json.loads(chemin.read_text(encoding="utf-8"))
    boot = get("bootstrap-static/")
    par_nom = {}
    for e in boot["elements"]:
        par_nom.setdefault(e["web_name"], []).append(e["id"])
    maint = datetime.now(timezone.utc)
    print("\n" + "=" * 70)
    print(f"ET SI… {sc.get('nom', '')}".upper())
    print("=" * 70)
    tot_s = tot_r = 0.0
    for ev_id, d in sorted(sc["events"].items(), key=lambda kv: int(kv[0])):
        ev = next((e for e in boot["events"] if e["id"] == int(ev_id)), None)
        if not ev or datetime.fromisoformat(ev["deadline_time"].replace("Z", "+00:00")) > maint:
            continue
        live = {x["id"]: x["stats"].get("total_points", 0) / 10 for x in get(f"event/{ev_id}/live/")["elements"]}
        pts_s = 0.0
        for n in d["titulaires"]:
            pid = (par_nom.get(n) or [None])[0]
            v = live.get(pid, 0.0)
            pts_s += v * (2 if n == d.get("capitaine") else 1)
        try:
            pk = get(f"entry/{eid}/event/{ev_id}/picks/")
            subs = pk.get("automatic_subs") or []
            entres, sortis = {a["element_in"] for a in subs}, {a["element_out"] for a in subs}
            pts_r = sum(live.get(p["element"], 0.0) * (1 if p["element"] in entres and p["multiplier"] == 0 else
                                                        0 if p["element"] in sortis else p["multiplier"]) for p in pk["picks"])
        except Exception:
            continue
        tot_s += pts_s; tot_r += pts_r
        etat = "terminé" if ev.get("finished") or ev.get("data_checked") else "en cours"
        print(f"  {ev['name']} ({etat}) : scénario {pts_s:.0f} pts | toi {pts_r:.0f} pts | écart {pts_s - pts_r:+.0f}")
    print(f"  TOTAL : scénario {tot_s:.0f} | toi {tot_r:.0f} | écart {tot_s - tot_r:+.0f} "
          "(sans les remplacements automatiques du scénario)")


if __name__ == "__main__":
    main()
    try:
        comparer_scenario(json.loads((ICI / "config.json").read_text(encoding="utf-8")))
    except Exception as ex:
        print(f"\n(comparaison du scénario indisponible : {ex!r})")
    try:
        statuts_du_jeu()
    except Exception as ex:
        print(f"\n(statuts indisponibles : {ex!r})")
    try:
        ligue(json.loads((ICI / "config.json").read_text(encoding="utf-8")))
    except Exception as ex:
        print(f"\n(classement de la ligue indisponible : {ex!r})")
