"""Blessures vues par ESPN, pour corriger la date de retour du jeu.

Le jeu affiche souvent « expected back <prochain match> » par défaut, même pour une blessure de
plusieurs semaines. ESPN donne pour chaque joueur blessé un statut (Out, Day-To-Day…), parfois une
date de retour, et un commentaire (« expected to miss 2-3 weeks », « out for the season »…).
On en tire une date de retour estimée ; assistant.py garde la plus tardive des deux sources.

    python3 blessures.py      # affiche ce qui est lu (test)
"""
import datetime as dt, json, re, unicodedata, urllib.request
from pathlib import Path

ICI = Path(__file__).resolve().parent
URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
CACHE = ICI / "rapport" / "blessures.json"
UA = {"User-Agent": "Mozilla/5.0 (assistant-nba-fantasy perso)"}
MOTS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "eight": 8, "ten": 10, "a": 1, "a couple of": 2, "several": 3, "few": 2}
NOMBRE = r"(\d+|one|two|three|four|five|six|eight|ten|a couple of|several|a few|few|a)"


def cle(nom):
    """Nom normalisé pour relier ESPN et le jeu : sans accents, ponctuation ni suffixes (Jr., III…)."""
    n = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode().lower()
    n = re.sub(r"[^a-z ]", " ", n)
    return " ".join(m for m in n.split() if m not in ("jr", "sr", "ii", "iii", "iv"))


def _nombre(x):
    x = x.strip()
    return int(x) if x.isdigit() else MOTS.get(x.replace("a few", "few"), 2)


def duree_commentaire(texte):
    """Durée d'absence (jours) lue dans un commentaire ESPN, ou None. Fourchette « 2-3 weeks » : le milieu."""
    t = (texte or "").lower()
    if re.search(r"(for the|rest of the|remainder of the) season|season-ending|season ending", t):
        return 180
    # la durée doit suivre un mot d'absence (« miss », « out », « re-evaluated »…) : les commentaires
    # parlent aussi des matchs passés (« 30 points in two days »)
    m = re.search(r"(?:miss|out|sidelined|re-?evaluated|absent|shelved)[^.]{0,40}?\b" + NOMBRE
                  + r"(?:\s*(?:-|to|or)\s*(\d+))?\s*(?:more\s+)?(week|day|month)s?", t)
    if not m:
        return None
    a = _nombre(m.group(1))
    b = int(m.group(2)) if m.group(2) else a
    n = (a + b) / 2
    return round(n * {"day": 1, "week": 7, "month": 30}[m.group(3)])


def lire_espn():
    req = urllib.request.Request(URL, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.load(r)
    res = {}
    for equipe in d.get("injuries", []):
        for b in equipe.get("injuries", []):
            ath = b.get("athlete") or {}
            nom = ath.get("displayName") or ""
            if not nom:
                continue
            det = b.get("details") or {}
            court, long_ = b.get("shortComment") or "", b.get("longComment") or ""
            date_info = (b.get("date") or "")[:10]
            retour = None
            if det.get("returnDate"):
                try:
                    retour = dt.date.fromisoformat(det["returnDate"][:10])
                except ValueError:
                    pass
            jours = duree_commentaire(court + " " + long_)
            estime = None
            if jours and date_info:
                try:
                    estime = dt.date.fromisoformat(date_info) + dt.timedelta(days=jours)
                except ValueError:
                    pass
            res[cle(nom)] = dict(nom=nom, statut=b.get("status") or (b.get("type") or {}).get("description"),
                                 blessure=" ".join(x for x in (det.get("side"), det.get("location"), det.get("type")) if x and x != "Not Specified"),
                                 retour_espn=retour and retour.isoformat(), retour_commentaire=estime and estime.isoformat(),
                                 commentaire=court[:300], date=date_info)
    return res


def blessures():
    """Blessures ESPN (cache si ESPN ne répond pas). Renvoie {nom normalisé: infos}."""
    try:
        res = lire_espn()
        CACHE.write_text(json.dumps({"lu": dt.datetime.now(dt.timezone.utc).isoformat(), "joueurs": res},
                                    ensure_ascii=False, indent=1), encoding="utf-8")
        return res
    except Exception as ex:
        print(f"  (blessures ESPN non lues : {ex!r} ; cache utilisé)")
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))["joueurs"]
        except Exception:
            return {}


def retour_estime(info):
    """Date de retour la plus prudente selon ESPN (date annoncée ou durée du commentaire)."""
    dates = [dt.date.fromisoformat(x) for x in (info.get("retour_espn"), info.get("retour_commentaire")) if x]
    return max(dates) if dates else None


if __name__ == "__main__":
    b = blessures()
    print(f"{len(b)} joueurs blessés lus sur ESPN")
    for k, v in list(b.items())[:15]:
        print(f"  {v['nom']:<24} {v['statut']:<12} retour ESPN {v['retour_espn']} | d'après le commentaire {v['retour_commentaire']} | {v['commentaire'][:100]}")
