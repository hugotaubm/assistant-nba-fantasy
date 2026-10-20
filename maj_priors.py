"""Recalcule priors.json (projection d'avant-saison de chaque joueur).

    python3 maj_priors.py

Mélange pour chaque joueur :
  - 75 % : projection 2026-27 (ESPN pour toute la ligue, moyennée avec
    donnees/projections_extra.csv — HashtagBasketball, FanScout — quand le joueur y figure)
  - 25 % : points fantasy réels par match en 2025-26 (si au moins 25 matchs joués)
La fiabilité (risque de manquer un match) vient du nombre de matchs projeté.
Sans projection : 85 % du réel 2025-26 si au moins 25 matchs joués,
sinon une valeur prudente liée au prix.
"""
import csv, json, re, shutil, unicodedata, urllib.request
from datetime import datetime
from pathlib import Path

ICI = Path(__file__).resolve().parent
SAISON_ESPN = 2027          # ESPN nomme la saison 2026-27 « 2027 »
POIDS_PROJECTION = 0.75
MIN_MATCHS_SAISON_PASSEE = 25
DECOTE_SANS_PROJECTION = 0.85   # joueur non projeté par ESPN (hors rotation probable)
ESPN_URL = (f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{SAISON_ESPN}"
            "/segments/0/leaguedefaults/3?view=kona_player_info")


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    return re.sub(r"[^a-z]", "", s)


def points(pts, reb, ast, stl, blk):
    # barème NBA Fantasy (vérifié sur les totaux 2025-26 du jeu)
    return pts + 1.2 * reb + 1.5 * ast + 3 * stl + 3 * blk


def espn():
    req = urllib.request.Request(ESPN_URL, headers={
        "Accept": "application/json",
        "X-Fantasy-Filter": json.dumps({"players": {"limit": 1000, "sortPercOwned": {"sortPriority": 1, "sortAsc": False}}})})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)["players"]
    res = {}
    for x in data:
        p = x["player"]
        st = {s["id"]: s.get("averageStats") or {} for s in p.get("stats", [])}
        pr, ac = st.get(f"10{SAISON_ESPN}", {}), st.get(f"00{SAISON_ESPN - 1}", {})
        stats = lambda a: points(a.get("0", 0), a.get("6", 0), a.get("3", 0), a.get("2", 0), a.get("1", 0))
        res[norm(p["fullName"])] = dict(
            nom=p["fullName"], cle_courte=norm(p.get("firstName", ""))[:1] + norm(p.get("lastName", "")),
            proj=stats(pr) if pr.get("42") else None, gp_proj=pr.get("42"),
            reel_formule=stats(ac) if ac.get("42") else None, gp_reel=ac.get("42"))
    return res


def extra():
    chemin = ICI / "donnees" / "projections_extra.csv"
    res = {}
    if chemin.exists():
        for l in csv.DictReader(chemin.open(encoding="utf-8")):
            f = {k: float(l[k]) for k in ("pts", "reb", "ast", "stl", "blk")}
            res.setdefault(norm(l["name"]), []).append(points(**f))
    return res


def main():
    boot = json.loads((ICI / "donnees" / "bootstrap.json").read_text(encoding="utf-8"))
    ancien = json.loads((ICI / "priors.json").read_text(encoding="utf-8"))
    equipes = {t["id"]: t["short_name"] for t in boot["teams"]}
    E, X = espn(), extra()
    par_nom = {}
    for k, v in E.items():
        par_nom.setdefault(v["cle_courte"], []).append(k)   # repli : initiale + nom de famille (ex. « Alexandre » / « Alex » Sarr)

    joueurs, stats = {}, {"espn": 0, "reel": 0, "prix": 0}
    for e in boot["elements"]:
        pid = str(e["id"])
        k = norm(e["first_name"] + e["second_name"])
        if k not in E:
            cand = par_nom.get(norm(e["first_name"])[:1] + norm(e["second_name"]), [])
            k = cand[0] if len(cand) == 1 else k
        old = ancien["joueurs"].get(pid, {})
        info = dict(nom=e["web_name"], equipe=equipes[e["team"]])
        j = E.get(k)
        if j and j["proj"] is None and (j["gp_reel"] or 0) >= MIN_MATCHS_SAISON_PASSEE and e["total_points"]:
            # pas projeté par ESPN = rôle incertain : saison passée avec une décote
            reel = e["total_points"] / 10 / j["gp_reel"]
            joueurs[pid] = dict(info, fppg=round(DECOTE_SANS_PROJECTION * reel, 2), fiabilite=0.85,
                                reel_2026=round(reel, 1), source="réel 2025-26 décoté")
            stats["reel"] += 1
            continue
        if not j or j["proj"] is None:
            # aucune source fiable : valeur prudente liée au prix (jamais au-dessus de l'ancienne)
            selon_prix = round(2.59 * e["now_cost"] / 10 + 1.4, 2)
            joueurs[pid] = dict(info, fppg=min(old.get("fppg", selon_prix), selon_prix),
                                fiabilite=min(old.get("fiabilite", 0.92), 0.92), source="selon le prix")
            stats["prix"] += 1
            continue
        stats["espn"] += 1
        # bonus du jeu non couverts par le barème simple : on garde le ratio réel du joueur
        ratio = 1.0
        reel = None
        if j["gp_reel"] and j["reel_formule"]:
            tot_formule = (e["points_scored"] + 1.2 * e["rebounds"] + 1.5 * e["assists"]
                           + 3 * e["blocks"] + 3 * e["steals"])
            if tot_formule > 0:
                ratio = min(1.10, max(0.95, e["total_points"] / 10 / tot_formule))
            reel = e["total_points"] / 10 / j["gp_reel"]
        sources = [j["proj"]] + X.get(k, [])
        proj = ratio * sum(sources) / len(sources)
        if reel and j["gp_reel"] >= MIN_MATCHS_SAISON_PASSEE:
            fppg = POIDS_PROJECTION * proj + (1 - POIDS_PROJECTION) * reel
        else:
            fppg = proj
        fiab = min(0.97, max(0.55, j["gp_proj"] / 82))
        joueurs[pid] = dict(info, fppg=round(fppg, 2), fiabilite=round(fiab, 2),
                            proj_2027=round(proj, 1), reel_2026=round(reel, 1) if reel else None,
                            matchs_proj=j["gp_proj"], nb_sources=len(sources))

    # garde l'effet back-to-back mesuré par maj_b2b.py
    for pid, v in joueurs.items():
        v.update({k: x for k, x in ancien["joueurs"].get(pid, {}).items() if k.startswith("b2b") or k in ("malus_b2b", "age", "presence")})
    shutil.copy(ICI / "priors.json", ICI / f"priors_avant_{datetime.now():%Y%m%d_%H%M}.json")
    (ICI / "priors.json").write_text(json.dumps({
        "saison": "2026-27",
        "source": (f"{int(POIDS_PROJECTION * 100)} % projection 2026-27 (ESPN + HashtagBasketball/FanScout si dispo) "
                   f"+ {int(100 - POIDS_PROJECTION * 100)} % réel 2025-26 ; fiabilité = matchs projetés / 82 ; "
                   f"mis à jour le {datetime.now():%d/%m/%Y}"),
        "joueurs": joueurs, **({"b2b": ancien["b2b"]} if "b2b" in ancien else {})}, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"priors.json mis à jour : {stats['espn']} joueurs avec projection 2026-27, "
          f"{stats['reel']} d'après 2025-26 seulement, {stats['prix']} d'après leur prix.")


if __name__ == "__main__":
    main()
