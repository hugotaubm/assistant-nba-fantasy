"""Rôle de chaque joueur dans son équipe (à lancer une fois par jour) : hiérarchie et présaison.

    python3 maj_roles.py

Pour chaque joueur projeté (ESPN) :
  - rang dans la hiérarchie de son équipe (« depth chart » ESPN), au poste où il est le mieux placé :
    1 = titulaire, 2 = premier remplaçant, 3 et plus = fin de rotation (risque de ne pas jouer) ;
  - minutes en présaison (matchs et moyenne), utiles pour les remplaçants : un joueur à 12 min en
    présaison n'en jouera pas 25 en saison.
Écrit rang_poste, devant (joueurs devant lui), presaison_matchs, presaison_min dans priors.json.
assistant.py s'en sert (voir role_et_minutes()).
"""
import json, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import maj_priors as M

ICI = Path(__file__).resolve().parent
SAISON = 2027   # ESPN : 2027 = saison 2026-27


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as r:
        return json.load(r)


def hierarchie(eq_id):
    """{nom: (meilleur rang, poste, joueurs devant)} pour une équipe ESPN (id 1 à 30)."""
    try:
        pos = get(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{eq_id}/depthcharts")["depthchart"][0]["positions"]
    except Exception:
        return {}
    res = {}
    for p, v in pos.items():
        noms = [a.get("displayName") for a in v.get("athletes", [])]
        for r, n in enumerate(noms, 1):
            if n not in res or r < res[n][0]:
                res[n] = (r, p.upper(), noms[:r - 1])
    return res


def presaison(espn_id):
    """(matchs, minutes moyennes) de présaison, ou None."""
    try:
        d = get(f"https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{espn_id}/gamelog?season={SAISON}")
    except Exception:
        return None
    col = {c: i for i, c in enumerate(d.get("names", []))}
    for st in d.get("seasonTypes", []):
        if "Preseason" in st.get("displayName", ""):
            mins = []
            for cat in st.get("categories", []):
                for ev in cat.get("events", []):
                    try:
                        mins.append(float(ev["stats"][col["minutes"]]))
                    except (KeyError, ValueError, IndexError):
                        pass
            if mins:
                return len(mins), sum(mins) / len(mins)
    return None


def main():
    boot = json.loads((ICI / "donnees" / "bootstrap.json").read_text(encoding="utf-8"))
    priors = json.loads((ICI / "priors.json").read_text(encoding="utf-8"))
    E = M.espn()
    ids = {k: None for k in E}
    req = urllib.request.Request(M.ESPN_URL, headers={"Accept": "application/json", "X-Fantasy-Filter": json.dumps(
        {"players": {"limit": 1000, "sortPercOwned": {"sortPriority": 1, "sortAsc": False}}})})
    with urllib.request.urlopen(req, timeout=60) as r:
        for x in json.load(r)["players"]:
            ids[M.norm(x["player"]["fullName"])] = (x["player"]["id"], x["player"]["fullName"])
    with ThreadPoolExecutor(8) as ex:
        hier = {}
        for h in ex.map(hierarchie, range(1, 31)):
            hier.update(h)
        cibles = {}
        for e in boot["elements"]:
            k = M.norm(e["first_name"] + e["second_name"])
            if ids.get(k) and str(e["id"]) in priors["joueurs"]:
                cibles[e["id"]] = ids[k]
        pres = dict(zip(cibles, ex.map(lambda pid: presaison(cibles[pid][0]), cibles)))
    n = 0
    for pid, (espn_id, nom) in cibles.items():
        v = priors["joueurs"][str(pid)]
        h = hier.get(nom)
        if h:
            v.update(rang_poste=h[0], poste_espn=h[1], devant=h[2][:3])
        p = pres.get(pid)
        if p:
            v.update(presaison_matchs=p[0], presaison_min=round(p[1], 1))
        n += bool(h or p)
    priors["roles"] = {"_source": f"ESPN (hiérarchie + présaison), mis à jour le {date.today():%d/%m/%Y}"}
    (ICI / "priors.json").write_text(json.dumps(priors, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"Rôles mis à jour pour {n} joueurs.")


if __name__ == "__main__":
    main()
