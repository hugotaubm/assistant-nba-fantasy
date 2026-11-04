"""Rapport quotidien pour la ligue Yahoo (H2H 9 catégories : FG%, FT%, 3PM, PTS, REB, AST, STL, BLK, TO).

Pour chaque joueur de joueurs_yahoo.txt :
  - statut de blessure lu sur NBA Fantasy (bootstrap-static) ;
  - sur les 7 et 15 derniers jours (nba_api) : matchs joués, minutes et moyennes des 9 catégories.
Écrit rapport_yahoo.md (un tableau, une ligne par joueur ; chaque case donne « 7 j · 15 j »).

    python3 rapport_yahoo.py              # rapport tout de suite
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


def matchs(jour):
    """Feuilles de match (saison régulière) des 15 derniers jours, tous joueurs : {nom normalisé: [lignes]}."""
    from nba_api.stats.endpoints import playergamelogs
    debut = jour - dt.timedelta(days=max(FENETRES))
    fin = jour - dt.timedelta(days=1)
    def lire():
        return playergamelogs.PlayerGameLogs(
            season_nullable=saison(jour), season_type_nullable="Regular Season",
            date_from_nullable=debut.strftime("%m/%d/%Y"), date_to_nullable=fin.strftime("%m/%d/%Y"),
            timeout=60).get_normalized_dict()["PlayerGameLogs"]
    res = {}
    for l in avec_essais(lire):
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


def rapport(jour, noms, bl, logs, erreur_stats=None):
    titre = f"# Rapport Yahoo — {JOURS[jour.weekday()]} {jour.day} {MOIS[jour.month - 1]} {jour.year}"
    out = [titre, f"<!-- date: {jour.isoformat()} -->", "",
           "Chaque case : moyenne sur les **7 derniers jours · 15 derniers jours** (matchs joués : MJ). "
           "FG% et FT% calculés sur le total des tirs.", ""]
    if erreur_stats:
        out += [f"> ⚠️ Statistiques NBA indisponibles aujourd'hui ({erreur_stats}).", ""]
    out.append("| Joueur | Éq. | Statut | " + " | ".join(t for _, t in COLONNES) + " |")
    out.append("|---|---|---|" + "---:|" * len(COLONNES))
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
        out.append(f"| {nom} | {equipe} | {statut} | " + " | ".join(cases) + " |")
    if notes:
        out += ["", "**Blessures / nouvelles**", ""] + notes
    if absents:
        out += ["", f"_Non trouvés sur NBA Fantasy : {', '.join(absents)}._"]
    maj = dt.datetime.now(PARIS).strftime("%d/%m/%Y %H:%M")
    out += ["", f"_Mis à jour le {maj} (heure de Paris). Sources : NBA Fantasy (statuts), stats.nba.com via nba_api._", ""]
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
    noms = lire_liste()
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
    SORTIE.write_text(rapport(jour, noms, bl, logs, erreur), encoding="utf-8")
    print(f"  écrit : {SORTIE.name}")
    sans_match = [n for n in noms if cle(n) not in logs]
    if sans_match and not erreur:
        print(f"  aucun match sur {max(FENETRES)} jours : {', '.join(sans_match)}")
    return 1 if erreur else 0


if __name__ == "__main__":
    sys.exit(main())
