"""Rapport quotidien pour la ligue Yahoo (H2H 9 catégories : FG%, FT%, 3PM, PTS, REB, AST, STL, BLK, TO).

Pour chaque joueur de joueurs_yahoo.txt :
  - statut de blessure lu sur NBA Fantasy (bootstrap-static) ;
  - sur les 7 et 15 derniers jours (nba_api : module live, cdn.nba.com ; repli sur stats.nba.com) : matchs joués, minutes et moyennes des 9 catégories.
Écrit rapport_yahoo.md (un tableau, une ligne par joueur ; chaque case donne « 7 j · 15 j »).

    python3 rapport_yahoo.py              # rapport tout de suite
    python3 rapport_yahoo.py --joueurs "Luka Garza, Danny Wolf"  # autres joueurs, affichés seulement
    python3 rapport_yahoo.py --si-besoin  # seulement s'il est au moins 10 h à Paris et pas encore fait aujourd'hui
"""
import datetime as dt, json, re, sys, time, unicodedata, urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ICI = Path(__file__).resolve().parent
LISTE = ICI / "joueurs_yahoo.txt"
SORTIE = ICI / "rapport_yahoo.md"
BOOTSTRAP = "https://nbafantasy.nba.com/api/bootstrap-static/"
UA = {"User-Agent": "Mozilla/5.0 (assistant-nba-fantasy perso)"}
PARIS = ZoneInfo("Europe/Paris")
FENETRES = (7, 15)
HEURE = 10  # heure de Paris du rapport (mode --si-besoin)
STATUTS = {"a": "OK", "d": "Incertain", "i": "Blessé", "s": "Suspendu", "u": "Indisponible", "n": "Hors effectif"}
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def cle(nom):
    """Nom normalisé pour relier les sources : sans accents, ponctuation ni suffixes (Jr., III…)."""
    n = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode().lower()
    n = re.sub(r"[.'’]", "", n)
    n = re.sub(r"[^a-z ]", " ", n)
    return " ".join(m for m in n.split() if m not in ("jr", "sr", "ii", "iii", "iv"))


def lire_liste():
    lignes = LISTE.read_text(encoding="utf-8").splitlines()
    return [l.strip() for l in lignes if l.strip() and not l.lstrip().startswith("#")]


def avec_essais(f, essais=3, pause=10):
    for i in range(essais):
        try:
            return f()
        except Exception as ex:
            if i == essais - 1:
                raise
            print(f"  essai {i + 1} échoué ({ex!r}), nouvel essai dans {pause} s")
            time.sleep(pause)


def blessures():
    """{nom normalisé: (équipe, statut lisible, nouvelle)} d'après NBA Fantasy."""
    def lire():
        with urllib.request.urlopen(urllib.request.Request(BOOTSTRAP, headers=UA), timeout=30) as r:
            return json.load(r)
    d = avec_essais(lire)
    equipes = {t["id"]: t.get("short_name") or t.get("name") for t in d.get("teams", [])}
    res = {}
    for e in d["elements"]:
        statut = STATUTS.get(e.get("status"), e.get("status") or "?")
        chance = e.get("chance_of_playing_next_round")
        if chance is not None and chance < 100 and e.get("status") != "a":
            statut += f" ({chance} %)"
        res[cle(f"{e['first_name']} {e['second_name']}")] = (equipes.get(e["team"], ""), statut, (e.get("news") or "").strip())
    return res


def saison(jour):
    a = jour.year if jour.month >= 8 else jour.year - 1
    return f"{a}-{(a + 1) % 100:02d}"


CALENDRIER = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"


def _minutes(iso):
    """« PT34M12.00S » -> 34.2"""
    m = re.match(r"PT(?:(\d+)M)?(?:([\d.]+)S)?", iso or "")
    return (int(m.group(1) or 0) + float(m.group(2) or 0) / 60) if m else 0.0


_CAL = {}


def calendrier():
    """Calendrier de la saison (cdn.nba.com), lu une seule fois."""
    if "cal" not in _CAL:
        import requests
        from nba_api.live.nba.library.http import NBALiveHTTP
        # cdn.nba.com refuse les clients inconnus : mêmes en-têtes de navigateur que nba_api.live
        entetes = {**NBALiveHTTP.headers, "Accept-Encoding": "gzip, deflate", "Accept": "application/json, */*"}

        def lire():
            r = requests.get(CALENDRIER, headers=entetes, timeout=60)
            r.raise_for_status()
            return r.json()
        _CAL["cal"] = avec_essais(lire)
    return _CAL["cal"]


def ce_soir(jour):
    """Matchs de la nuit qui suit (date US = date du jour) : {équipe: « @BKN 01:00 » / « MEM 02:00 »}, heure de Paris."""
    res = {}
    for jd in calendrier()["leagueSchedule"]["gameDates"]:
        for g in jd["games"]:
            if g["gameDateEst"][:10] != jour.isoformat() or not g["gameId"].startswith("002"):
                continue
            heure = dt.datetime.fromisoformat(g["gameDateTimeUTC"].replace("Z", "+00:00")).astimezone(PARIS).strftime("%H:%M")
            dom, ext = g["homeTeam"]["teamTricode"], g["awayTeam"]["teamTricode"]
            res[dom] = f"{ext} {heure}"
            res[ext] = f"@{dom} {heure}"
    return res


def semaine(jour):
    """Matchs restants d'ici dimanche (inclus, dates US), par équipe : la semaine Yahoo va du lundi au dimanche."""
    dimanche = jour + dt.timedelta(days=6 - jour.weekday())
    res = {}
    for jd in calendrier()["leagueSchedule"]["gameDates"]:
        for g in jd["games"]:
            d = dt.date.fromisoformat(g["gameDateEst"][:10])
            if jour <= d <= dimanche and g["gameId"].startswith("002"):
                for camp in ("homeTeam", "awayTeam"):
                    res[g[camp]["teamTricode"]] = res.get(g[camp]["teamTricode"], 0) + 1
    return res


def matchs_live(debut, fin):
    """Feuilles de match via nba_api.live (cdn.nba.com, joignable depuis GitHub Actions)."""
    from concurrent.futures import ThreadPoolExecutor
    from nba_api.live.nba.endpoints import boxscore

    cal = calendrier()
    a_lire = []  # (id du match, date US)
    for jd in cal["leagueSchedule"]["gameDates"]:
        for g in jd["games"]:
            date_us = dt.date.fromisoformat(g["gameDateEst"][:10])
            # saison régulière (id 002…) ; matchs terminés (gameStatus 3) de la fenêtre
            if g["gameId"].startswith("002") and g.get("gameStatus") == 3 and debut <= date_us <= fin:
                a_lire.append((g["gameId"], date_us))

    def feuille(m):
        gid, date_us = m
        d = avec_essais(lambda: boxscore.BoxScore(gid, timeout=30).get_dict()["game"])
        lignes = []
        for camp in ("homeTeam", "awayTeam"):
            for j in d[camp]["players"]:
                st = j.get("statistics") or {}
                if j.get("played") != "1":
                    continue
                lignes.append(dict(PLAYER_NAME=j["name"], GAME_ID=gid, GAME_DATE=date_us.isoformat(),
                                   TEAM_ABBREVIATION=d[camp].get("teamTricode"),
                                   MIN=_minutes(st.get("minutes")), FGM=st.get("fieldGoalsMade"),
                                   FGA=st.get("fieldGoalsAttempted"), FTM=st.get("freeThrowsMade"),
                                   FTA=st.get("freeThrowsAttempted"), FG3M=st.get("threePointersMade"),
                                   PTS=st.get("points"), REB=st.get("reboundsTotal"), AST=st.get("assists"),
                                   STL=st.get("steals"), BLK=st.get("blocks"), TOV=st.get("turnovers")))
        return lignes
    with ThreadPoolExecutor(6) as ex:
        feuilles = list(ex.map(feuille, a_lire))
    print(f"  {len(a_lire)} matchs lus sur cdn.nba.com")
    return [l for f in feuilles for l in f]


def matchs_stats(jour, debut, fin):
    """Feuilles de match via nba_api.stats (stats.nba.com, souvent bloqué depuis les serveurs cloud)."""
    from nba_api.stats.endpoints import playergamelogs
    return playergamelogs.PlayerGameLogs(
        season_nullable=saison(jour), season_type_nullable="Regular Season",
        date_from_nullable=debut.strftime("%m/%d/%Y"), date_to_nullable=fin.strftime("%m/%d/%Y"),
        timeout=30).get_normalized_dict()["PlayerGameLogs"]


def matchs(jour):
    """Feuilles de match (saison régulière) des 15 derniers jours, tous joueurs : {nom normalisé: [lignes]}.
    Dates des matchs à l'heure américaine : au réveil à Paris, les matchs de la nuit sont « hier »."""
    debut = jour - dt.timedelta(days=max(FENETRES))
    fin = jour - dt.timedelta(days=1)
    try:
        lignes = matchs_live(debut, fin)
    except Exception as ex:
        print(f"  cdn.nba.com non lu ({ex!r}) ; essai sur stats.nba.com")
        lignes = matchs_stats(jour, debut, fin)
    res = {}
    for l in lignes:
        res.setdefault(cle(l["PLAYER_NAME"]), {})[l["GAME_ID"]] = l
    return {k: list(v.values()) for k, v in res.items()}


def moyennes(lignes, jour, n):
    depuis = jour - dt.timedelta(days=n)
    g = [l for l in lignes if dt.date.fromisoformat(l["GAME_DATE"][:10]) >= depuis and (l.get("MIN") or 0) > 0]
    if not g:
        return None
    s = {k: sum(l.get(k) or 0 for l in g) for k in ("MIN", "FGM", "FGA", "FTM", "FTA", "FG3M", "PTS", "REB", "AST", "STL", "BLK", "TOV")}
    nb = len(g)
    return dict(MJ=nb, MIN=s["MIN"] / nb,
                FG=s["FGM"] / s["FGA"] if s["FGA"] else None, FT=s["FTM"] / s["FTA"] if s["FTA"] else None,
                **{k: s[k] / nb for k in ("FG3M", "PTS", "REB", "AST", "STL", "BLK", "TOV")})


COLONNES = [("MJ", "MJ"), ("MIN", "MIN"), ("FG", "FG%"), ("FT", "FT%"), ("FG3M", "3PM"), ("PTS", "PTS"),
            ("REB", "REB"), ("AST", "AST"), ("STL", "STL"), ("BLK", "BLK"), ("TOV", "TO")]


def fmt(m, k):
    if m is None:
        return "–"
    v = m[k]
    if v is None:
        return "–"
    if k == "MJ":
        return str(v)
    if k in ("FG", "FT"):
        return f"{v:.3f}".lstrip("0")
    return f"{v:.1f}"


def rapport(jour, noms, bl, logs, erreur_stats=None, soir=None, sem=None):
    titre = f"# Rapport Yahoo — {JOURS[jour.weekday()]} {jour.day} {MOIS[jour.month - 1]} {jour.year}"
    # repère du mode --si-besoin ; absent si les stats manquent, pour réessayer au passage suivant
    repere = "<!-- date: incomplet -->" if erreur_stats else f"<!-- date: {jour.isoformat()} -->"
    out = [titre, repere, "",
           "Chaque case : moyenne sur les **7 derniers jours · 15 derniers jours** (matchs joués : MJ). "
           "FG% et FT% calculés sur le total des tirs. « Ce soir » : match de la nuit qui vient "
           "(@ = à l'extérieur), heure de Paris. « Sem. » : matchs restants d'ici dimanche, ce soir compris.", ""]
    if erreur_stats:
        out += [f"> ⚠️ Statistiques NBA indisponibles aujourd'hui ({erreur_stats}).", ""]
    out.append("| Joueur | Éq. | Statut | Ce soir | Sem. | " + " | ".join(t for _, t in COLONNES) + " |")
    out.append("|---|---|---|---|---:|" + "---:|" * len(COLONNES))
    notes, absents = [], []
    for nom in noms:
        k = cle(nom)
        equipe, statut, news = bl.get(k, ("", "?", ""))
        if k not in bl:
            absents.append(nom)
        if news:
            notes.append(f"- **{nom}** : {news}")
        m7, m15 = (moyennes(logs.get(k, []), jour, n) for n in FENETRES)
        cases = ["–" if m7 is None and m15 is None else f"{fmt(m7, c)} · {fmt(m15, c)}" for c, _ in COLONNES]
        # équipe du dernier match joué (NBA Fantasy tarde à suivre les transferts)
        recents = sorted(logs.get(k, []), key=lambda l: l["GAME_DATE"])
        if recents and recents[-1].get("TEAM_ABBREVIATION"):
            equipe = recents[-1]["TEAM_ABBREVIATION"]
        match = "?" if soir is None else soir.get(equipe, "–")
        reste = "?" if sem is None else sem.get(equipe, 0)
        out.append(f"| {nom} | {equipe} | {statut} | {match} | {reste} | " + " | ".join(cases) + " |")
    if notes:
        out += ["", "**Blessures / nouvelles**", ""] + notes
    if absents:
        out += ["", f"_Non trouvés sur NBA Fantasy : {', '.join(absents)}._"]
    maj = dt.datetime.now(PARIS).strftime("%d/%m/%Y %H:%M")
    out += ["", f"_Mis à jour le {maj} (heure de Paris). Sources : NBA Fantasy (statuts), feuilles de match NBA via nba_api._", ""]
    return "\n".join(out)


def main():
    maintenant = dt.datetime.now(PARIS)
    jour = maintenant.date()
    if "--si-besoin" in sys.argv:
        # passages programmés (cron en UTC, souvent en retard) : un seul rapport par jour, pas avant 10 h à Paris
        deja = SORTIE.exists() and f"<!-- date: {jour.isoformat()} -->" in SORTIE.read_text(encoding="utf-8")
        if maintenant.hour < HEURE or deja:
            print(f"Rien à faire ({'rapport du jour déjà fait' if deja else f'avant {HEURE} h à Paris'}).")
            return 0
    # --joueurs "Nom 1, Nom 2" : tableau des joueurs donnés (ex. joueurs libres), affiché sans toucher au rapport
    autres = sys.argv[sys.argv.index("--joueurs") + 1] if "--joueurs" in sys.argv else ""
    noms = [n.strip() for n in autres.split(",") if n.strip()] or lire_liste()
    print(f"{len(noms)} joueurs, rapport du {jour}")
    bl = blessures()
    print(f"  statuts NBA Fantasy : {len(bl)} joueurs lus")
    erreur = None
    try:
        logs = matchs(jour)
        print(f"  feuilles de match : {sum(map(len, logs.values()))} lignes sur {max(FENETRES)} jours")
    except Exception as ex:
        logs, erreur = {}, f"{type(ex).__name__}"
        print(f"  stats NBA non lues : {ex!r}")
    try:
        soir, sem = ce_soir(jour), semaine(jour)
        print(f"  ce soir : {len(soir) // 2} matchs")
    except Exception as ex:
        soir = sem = None
        print(f"  calendrier de ce soir non lu : {ex!r}")
    if autres:
        print(rapport(jour, noms, bl, logs, erreur, soir, sem))
        return 1 if erreur else 0
    SORTIE.write_text(rapport(jour, noms, bl, logs, erreur, soir, sem), encoding="utf-8")
    print(f"  écrit : {SORTIE.name}")
    sans_match = [n for n in noms if cle(n) not in logs]
    if sans_match and not erreur:
        print(f"  aucun match sur {max(FENETRES)} jours : {', '.join(sans_match)}")
    return 1 if erreur else 0


if __name__ == "__main__":
    sys.exit(main())
