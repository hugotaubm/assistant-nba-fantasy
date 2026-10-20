"""Mesure l'effet des back-to-backs joueur par joueur (saison passée) et l'écrit dans priors.json.

    python3 maj_b2b.py

Pour chaque joueur, sur la saison régulière passée (feuilles de match ESPN) :
  - présence : joue-t-il le 2e soir d'un back-to-back aussi souvent qu'un match normal
    (en ne comptant que les matchs où il a joué le match précédent de son équipe) ?
  - rendement : points fantasy les soirs de back-to-back / les autres soirs.
Facteur brut = (présence × rendement en B2B) / (présence × rendement en moyenne).
Avec ~10-15 back-to-backs par joueur, le brut est bruité : on le rapproche de la moyenne de sa
tranche d'âge (rétrécissement), d'autant plus qu'il a peu de back-to-backs.
Résultat : champ « malus_b2b » de chaque joueur dans priors.json (utilisé par assistant.py).
"""
import datetime as dt, json, re, unicodedata, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zoneinfo import ZoneInfo

ICI = Path(__file__).resolve().parent
SAISON = 2026            # ESPN : 2026 = saison 2025-26
K_RETRECISSEMENT = 15    # nb de back-to-backs « équivalents » donnés à la moyenne de la tranche d'âge
BORNES = (0.6, 1.05)
NY = ZoneInfo("America/New_York")
ESPN_PROJ = ("https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/2027"
             "/segments/0/leaguedefaults/3?view=kona_player_info")


def get(url, entetes=None):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json", **(entetes or {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    return re.sub(r"[^a-z]", "", s)


def points(pts, reb, ast, stl, blk):
    return pts + 1.2 * reb + 1.5 * ast + 3 * stl + 3 * blk


def calendrier_equipe(eq_id):
    d = get(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{eq_id}/schedule?season={SAISON}")
    return {e["id"]: dt.datetime.fromisoformat(e["date"].replace("Z", "+00:00")).astimezone(NY).date()
            for e in d.get("events", []) if (e.get("seasonType") or {}).get("type") == 2}


def journal_joueur(espn_id):
    """{id_match: (id_équipe, points fantasy)} pour les matchs joués en saison régulière."""
    d = get(f"https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{espn_id}/gamelog?season={SAISON}")
    noms = d.get("names") or []
    col = {n: i for i, n in enumerate(noms)}
    res = {}
    for st in d.get("seasonTypes", []):
        if "Regular" not in st.get("displayName", ""):
            continue
        for cat in st.get("categories", []):
            for ev in cat.get("events", []):
                v = ev["stats"]
                try:
                    if float(v[col["minutes"]]) <= 0:
                        continue
                    fp = points(*(float(v[col[k]]) for k in ("points", "totalRebounds", "assists", "steals", "blocks")))
                except (KeyError, ValueError, IndexError):
                    continue
                info = d["events"].get(ev["eventId"], {})
                res[ev["eventId"]] = ((info.get("team") or {}).get("id"), fp)
    return res


def age_joueur(espn_id):
    return get(f"https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{espn_id}")["athlete"].get("age")


def mesurer(journal, calendriers):
    """Compte présence et rendement, en B2B et en général, sur les matchs qui suivent un match joué."""
    c = dict(n_b2b=0, joue_b2b=0, fp_b2b=0.0, n_tous=0, joue_tous=0, fp_tous=0.0)
    for eq in {t for t, _ in journal.values() if t}:
        cal = calendriers.get(eq) or {}
        matchs = sorted(cal.items(), key=lambda kv: kv[1])
        joues = [m for m, _ in matchs if m in journal and journal[m][0] == eq]
        if not joues:
            continue
        idx = {m: i for i, (m, _) in enumerate(matchs)}
        debut, fin = idx[joues[0]], idx[joues[-1]]
        for i in range(debut + 1, fin + 1):
            prec, cur = matchs[i - 1][0], matchs[i][0]
            if prec not in journal:          # on ne compte que les matchs qui suivent un match joué
                continue
            b2b = (matchs[i][1] - matchs[i - 1][1]).days == 1
            joue = cur in journal
            fp = journal[cur][1] if joue else 0.0
            c["n_tous"] += 1; c["joue_tous"] += joue; c["fp_tous"] += fp
            if b2b:
                c["n_b2b"] += 1; c["joue_b2b"] += joue; c["fp_b2b"] += fp
    return c


def facteur(c):
    """Espérance de points d'un soir de B2B / espérance d'un soir moyen (présence comprise)."""
    if c["n_b2b"] == 0 or c["n_tous"] == 0 or c["fp_tous"] == 0:
        return None
    return (c["fp_b2b"] / c["n_b2b"]) / (c["fp_tous"] / c["n_tous"])


def tranche(age):
    return "<25" if age < 25 else "25-29" if age < 30 else "30-33" if age < 34 else "34+"


def main():
    boot = json.loads((ICI / "donnees" / "bootstrap.json").read_text(encoding="utf-8"))
    priors = json.loads((ICI / "priors.json").read_text(encoding="utf-8"))
    espn = get(ESPN_PROJ, {"X-Fantasy-Filter": json.dumps({"players": {"limit": 1000, "sortPercOwned": {"sortPriority": 1, "sortAsc": False}}})})["players"]
    par_nom = {norm(x["player"]["fullName"]): x["player"]["id"] for x in espn}
    cible = {}
    for e in boot["elements"]:
        k = norm(e["first_name"] + e["second_name"])
        if k in par_nom and str(e["id"]) in priors["joueurs"]:
            cible[e["id"]] = (par_nom[k], e)
    print(f"Calendriers des 30 équipes et feuilles de match de {len(cible)} joueurs…")
    with ThreadPoolExecutor(8) as ex:
        calendriers = dict(zip(range(1, 31), ex.map(lambda t: calendrier_equipe(t), range(1, 31))))
        calendriers = {str(k): v for k, v in calendriers.items()}
        journaux = dict(zip(cible, ex.map(lambda pid: _sur(journal_joueur, cible[pid][0]), cible)))
        ages = dict(zip(cible, ex.map(lambda pid: _sur(age_joueur, cible[pid][0]), cible)))

    aujourdhui = dt.date.today()
    mesures = {}
    for pid, (espn_id, e) in cible.items():
        if not journaux.get(pid):
            continue
        c = mesurer(journaux[pid], calendriers)
        if c["n_b2b"] and facteur(c) is not None:
            mesures[pid] = (c, tranche(ages.get(pid) or 27))
    # moyenne de chaque tranche d'âge (tous joueurs confondus, pondérée par le volume)
    moy = {}
    for t in ("<25", "25-29", "30-33", "34+"):
        cs = [c for c, tt in mesures.values() if tt == t]
        tot = {k: sum(c[k] for c in cs) for k in ("n_b2b", "fp_b2b", "n_tous", "fp_tous", "joue_b2b", "joue_tous")}
        moy[t] = (facteur(tot) or 0.95, tot)
    for pid, (c, t) in mesures.items():
        brut = facteur(c)
        m = (c["n_b2b"] * brut + K_RETRECISSEMENT * moy[t][0]) / (c["n_b2b"] + K_RETRECISSEMENT)
        priors["joueurs"][str(pid)].update(
            malus_b2b=round(min(BORNES[1], max(BORNES[0], m)), 3), b2b_brut=round(brut, 3), b2b_n=c["n_b2b"],
            b2b_presence=round(c["joue_b2b"] / c["n_b2b"], 2), presence=round(c["joue_tous"] / c["n_tous"], 2),
            age=ages.get(pid))
    for pid in cible:   # sans saison passée (rookies…) : moyenne de la tranche d'âge
        if pid not in mesures and ages.get(pid):
            priors["joueurs"][str(pid)].update(malus_b2b=round(moy[tranche(ages[pid])][0], 3), age=ages[pid],
                                               b2b_n=0)
    priors["b2b"] = {t: dict(facteur=round(f, 3), presence_b2b=round(tot["joue_b2b"] / max(tot["n_b2b"], 1), 3),
                             presence=round(tot["joue_tous"] / max(tot["n_tous"], 1), 3), n_b2b=tot["n_b2b"])
                     for t, (f, tot) in moy.items()}
    priors["b2b"]["_source"] = f"saison régulière {SAISON - 1}-{str(SAISON)[2:]} (ESPN), mis à jour le {aujourdhui:%d/%m/%Y}"
    (ICI / "priors.json").write_text(json.dumps(priors, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"{len(mesures)} joueurs mesurés. Moyennes par âge :")
    for t, (f, tot) in moy.items():
        print(f"  {t:>6} : x{f:.3f}  (présence B2B {tot['joue_b2b']}/{tot['n_b2b']}, "
              f"en général {tot['joue_tous']}/{tot['n_tous']})")


def _sur(f, *a):
    try:
        return f(*a)
    except Exception:
        return None


if __name__ == "__main__":
    main()
