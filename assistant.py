#!/usr/bin/env python3
"""
Assistant NBA Fantasy (Salary Cap Edition)
------------------------------------------
Chaque jour : récupère les données de l'API NBA Fantasy, projette les points de chaque
joueur sur les Gamedays restants de la Gameweek, puis propose :
  - le cinq de départ du jour,
  - le meilleur moment pour le capitaine,
  - les transferts à faire (et quand),
  - les alertes blessures.

Usage :
    python assistant.py                # récupère les données en ligne
    python assistant.py --hors-ligne   # réutilise les derniers fichiers de ./donnees
    python assistant.py --pas-de-navigateur
"""
import argparse, datetime as dt, json, os, re, sys, webbrowser, html
from pathlib import Path

import numpy as np
from scipy.optimize import milp, LinearConstraint, Bounds
from scipy.sparse import lil_matrix

ICI = Path(__file__).resolve().parent
DONNEES = ICI / "donnees"
DONNEES.mkdir(exist_ok=True)
BASE = "https://nbafantasy.nba.com/api"
NBA_SCHEDULE = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"
UA = {"User-Agent": "Mozilla/5.0 (assistant-nba-fantasy perso)"}
try:
    from zoneinfo import ZoneInfo
    PARIS = ZoneInfo("Europe/Paris")
except Exception:  # pragma: no cover
    PARIS = dt.timezone(dt.timedelta(hours=1))
B2B = set()          # (équipe, event) = 2e match d'un back-to-back, rempli par construire_calendrier
MALUS_B2B = [0.92]   # remplacé par config.json « malus_back_to_back »


# ----------------------------------------------------------------------------- utils
def lire_config():
    cfg = json.loads((ICI / "config.json").read_text(encoding="utf-8"))
    local = ICI / "config_local.json"   # réglages secrets ou propres au Mac, hors du dépôt GitHub
    if local.exists():
        cfg.update(json.loads(local.read_text(encoding="utf-8")))
    cfg.setdefault("transferts_gratuits_par_defaut", 2)
    cfg.setdefault("poids_futur", 2.0)
    cfg.setdefault("duree_blessure_matchs", 4)   # durée moyenne d'une absence (matchs) → risque par match
    cfg.setdefault("taux_recuperation", 0.8)     # part de la perte récupérée en remplaçant un blessé
    cfg.setdefault("nb_candidats", 150)         # joueurs étudiés par l'optimiseur (les mieux projetés + l'effectif)
    cfg.setdefault("bonus_attente", 0.5)        # pts par jour de retard d'un transfert : à gain égal, on attend
    cfg.setdefault("temps_max_calcul", 100)     # secondes max par optimisation
    cfg.setdefault("seuil_nouvelle_equipe", 20)
    cfg.setdefault("poids_presence_avant_saison", 2)   # matchs « fictifs » donnés à la fiabilité d'avant-saison
    cfg.setdefault("poids_minutes_avant_saison", 3)    # matchs « fictifs » donnés aux minutes projetées
    cfg.setdefault("poids_points_avant_saison", 8)     # matchs « fictifs » donnés à la projection d'avant-saison
    cfg.setdefault("plafond_minutes", 1.3)             # hausse max de la projection quand un joueur joue plus que prévu
    cfg.setdefault("poids_forme", 0.25)                # part de la forme récente (à partir de 5 matchs)
    cfg.setdefault("fiabilite_rang", {"3": 0.9, "4+": 0.75})   # 3e ou au-delà dans la hiérarchie de son poste
    cfg.setdefault("seuil_joker", 150)          # gain (pts, semaine + suivante pondérée) à partir duquel le joker vaut le coup
    cfg.setdefault("idees", [])                 # tes idées à tester, ex. "D.Wolf>J.Hayes@6" (vendre>acheter@jour)
    cfg.setdefault("calibration_auto", True)    # corrige les projections avec leurs erreurs passées (bilan.py)
    cfg.setdefault("seuil_changement_plan", 5)  # pts mini pour changer un transfert déjà conseillé
    cfg.setdefault("force_fort", 25)            # badge 🟢 Fort à partir de ce gain (pts)
    cfg.setdefault("force_leger", 8)            # badge 🟡 Léger à partir de ce gain, sinon ⚪ Facultatif # pts de gain mini pour proposer une autre équipe avant la 1re deadline
    cfg.setdefault("imposer_au_depart", [])
    cfg.setdefault("malus_back_to_back", 0.92)
    cfg.setdefault("projection_min", 12)
    cfg.setdefault("joueurs_exclus", [])
    cfg.setdefault("joueurs_bloques", [])
    cfg.setdefault("ajustements", {})
    cfg.setdefault("equipe_manuelle", [])
    return cfg


def z(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def paris(t):
    return t.astimezone(PARIS).strftime("%a %d/%m %Hh%M").replace(
        "Mon", "lun.").replace("Tue", "mar.").replace("Wed", "mer.").replace(
        "Thu", "jeu.").replace("Fri", "ven.").replace("Sat", "sam.").replace("Sun", "dim.")


def lire_requete_curl(chemin):
    """Lit une requête copiée depuis le navigateur ("Copier en tant que cURL") : URL + en-têtes."""
    import shlex
    texte = chemin.read_text(encoding="utf-8").replace("\\\n", " ").replace("^\n", " ").replace("^", "")
    jetons = shlex.split(texte)
    url, entetes, i = None, {}, 0
    while i < len(jetons):
        j = jetons[i]
        if j in ("-H", "--header") and i + 1 < len(jetons):
            nom, _, val = jetons[i + 1].partition(":")
            entetes[nom.strip()] = val.strip(); i += 2; continue
        if j in ("-b", "--cookie") and i + 1 < len(jetons):
            entetes["Cookie"] = jetons[i + 1]; i += 2; continue
        if j.startswith("http"):
            url = j
        i += 1
    for inutile in [k for k in entetes if k.lower() in ("accept-encoding", "content-length", "host")]:
        del entetes[inutile]
    return url, entetes


def telecharger(nom, url, cookie=None, obligatoire=True, entetes_sup=None):
    """Télécharge un JSON et le garde en cache. En cas d'échec, reprend le cache."""
    import requests
    chemin = DONNEES / f"{nom}.json"
    entetes = dict(UA)
    if entetes_sup:
        entetes.update(entetes_sup)
    if cookie:
        entetes["Cookie"] = cookie
    try:
        r = requests.get(url, headers=entetes, timeout=30)
        r.raise_for_status()
        data = r.json()
        chemin.write_text(json.dumps(data), encoding="utf-8")
        return data, "en ligne"
    except Exception as ex:
        if chemin.exists():
            age = dt.datetime.now() - dt.datetime.fromtimestamp(chemin.stat().st_mtime)
            print(f"  ! {nom} : échec du téléchargement ({ex}). Cache utilisé (âge {age}).")
            return json.loads(chemin.read_text(encoding="utf-8")), f"cache ({age.days} j)"
        if obligatoire:
            sys.exit(f"Impossible de récupérer {nom} : {ex}")
        return None, f"indisponible ({ex.__class__.__name__})"


def lire_cache(nom):
    chemin = DONNEES / f"{nom}.json"
    return (json.loads(chemin.read_text(encoding="utf-8")), "cache") if chemin.exists() else (None, "absent")


# ----------------------------------------------------------------------------- données
def charger(cfg, hors_ligne):
    get = (lambda n, u, **k: lire_cache(n)) if hors_ligne else telecharger
    boot, s_boot = get("bootstrap", f"{BASE}/bootstrap-static/")
    if boot is None:
        sys.exit("Pas de fichier bootstrap. Lance sans --hors-ligne ou place donnees/bootstrap.json.")
    fixtures, s_fix = get("fixtures", f"{BASE}/fixtures/", obligatoire=False)
    sched, s_sched = (None, "non utilisé")
    if not fixtures:
        sched, s_sched = get("calendrier_nba", NBA_SCHEDULE, obligatoire=False)
    mt, s_mt = (None, "non configuré")
    fichier_req = ICI / "requete_mon_equipe.txt"
    if fichier_req.exists() and fichier_req.stat().st_size > 20:
        url, entetes = lire_requete_curl(fichier_req)
        if url and "my-team" in url:
            if hors_ligne:
                mt, s_mt = lire_cache("mon_equipe")
            else:
                mt, s_mt = telecharger("mon_equipe", url, obligatoire=False, entetes_sup=entetes)
        else:
            print("  ! requete_mon_equipe.txt ne contient pas une requête « my-team ». Revois l'étape de copie.")
    cookie = lire_cookie(cfg)
    if mt is None and cfg.get("id_equipe") and cookie:
        mt, s_mt = equipe_cookie(cfg["id_equipe"], cookie, hors_ligne)
    if mt is None:
        # Copie manuelle de la réponse « my-team » : valable si elle date d'après la dernière deadline passée
        fichier_mt = DONNEES / "mon_equipe.json"
        passees = [z(e["deadline_time"]) for e in boot["events"] if z(e["deadline_time"]) <= dt.datetime.now(dt.timezone.utc)]
        if fichier_mt.exists():
            quand = dt.datetime.fromtimestamp(fichier_mt.stat().st_mtime, dt.timezone.utc)
            if not passees or quand > max(passees):
                mt, s_mt = json.loads(fichier_mt.read_text(encoding="utf-8")), f"fichier mon_equipe.json ({paris(quand)})"
                mt["_copie"] = quand.astimezone(PARIS).strftime("%Hh%M")
            else:
                print("  ! donnees/mon_equipe.json date d'avant la dernière deadline : ignoré.")
        if mt is None and cfg.get("id_equipe"):
            if passees:
                mt, s_mt = equipe_publique(cfg, boot, get)
            else:
                s_mt = "pas encore public (avant la 1re deadline) : equipe_manuelle utilisée"
                print("  ! Équipe pas encore publique avant la 1re deadline : equipe_manuelle utilisée.")
    sources = {"joueurs": s_boot, "calendrier (fantasy)": s_fix, "calendrier (NBA)": s_sched, "mon équipe": s_mt}
    return boot, fixtures, sched, mt, sources


def construire_calendrier(boot, fixtures, sched):
    """Renvoie {id_equipe_fantasy: set(id_event)} et la liste des matchs."""
    events = sorted(boot["events"], key=lambda e: e["id"])
    deadlines = [(e["id"], z(e["deadline_time"])) for e in events]

    def event_de(t):
        ev = None
        for eid, dl in deadlines:
            if dl <= t:
                ev = eid
            else:
                break
        return ev

    joue, matchs = {}, []
    if fixtures:
        for f in fixtures:
            ev = f.get("event")
            t = z(f["kickoff_time"]) if f.get("kickoff_time") else None
            if ev is None and t:
                ev = event_de(t)
            if ev is None:
                continue
            for eq in (f["team_h"], f["team_a"]):
                joue.setdefault(eq, set()).add(ev)
            matchs.append((ev, t, f["team_h"], f["team_a"]))
    elif sched:
        par_code = {t["code"]: t["id"] for t in boot["teams"]}
        for jour in sched.get("leagueSchedule", {}).get("gameDates", []):
            for g in jour.get("games", []):
                s = g.get("gameDateTimeUTC") or g.get("gameDateUTC")
                if not s:
                    continue
                t = z(s if s.endswith("Z") or "+" in s else s + "Z")
                h = par_code.get(g["homeTeam"].get("teamId"))
                a = par_code.get(g["awayTeam"].get("teamId"))
                ev = event_de(t)
                if h is None or a is None or ev is None:
                    continue
                for eq in (h, a):
                    joue.setdefault(eq, set()).add(ev)
                matchs.append((ev, t, h, a))
    else:
        sys.exit("Aucun calendrier disponible (ni fixtures fantasy, ni calendrier NBA).")
    # 2e match d'un back-to-back : l'équipe a joué la veille (date locale américaine)
    NY = ZoneInfo("America/New_York")
    jours_eq = {}
    for ev, t, h, a in matchs:
        if t:
            for eq in (h, a):
                jours_eq.setdefault(eq, {})[t.astimezone(NY).date()] = ev
    B2B.clear()
    for eq, jj in jours_eq.items():
        B2B.update((eq, ev) for d, ev in jj.items() if d - dt.timedelta(days=1) in jj)
    return joue, matchs


def gameweek_courante(boot, maintenant):
    events = sorted(boot["events"], key=lambda e: e["id"])
    a_venir = [e for e in events if z(e["deadline_time"]) > maintenant]
    if not a_venir:
        sys.exit("La saison semble terminée.")
    prochain = a_venir[0]["id"]
    gw = next(p for p in boot["phases"] if p["name"].lower().startswith("gameweek")
              and p["start_event"] <= prochain <= p["stop_event"])
    gw_suiv = next((p for p in boot["phases"] if p["name"].lower().startswith("gameweek")
                    and p["start_event"] == gw["stop_event"] + 1), None)
    jours = [e for e in events if prochain <= e["id"] <= gw["stop_event"]]
    saison_commencee = any(e.get("finished") for e in events)
    return gw, gw_suiv, jours, saison_commencee


# ----------------------------------------------------------------------------- projections
def minutes_saison(boot, hors_ligne):
    """Pour chaque joueur, sur les Gamedays terminés : matchs de son équipe, matchs où il est entré en jeu,
    minutes totales (routes publiques /event/N/live/, gardées en cache une fois le Gameday terminé)."""
    import requests
    res = {}
    equipe = {e["id"]: e["team"] for e in boot["elements"]}
    maintenant = dt.datetime.now(dt.timezone.utc)
    for ev in (e for e in boot["events"] if z(e["deadline_time"]) < maintenant):
        chemin = DONNEES / f"live_{ev['id']}.json"   # gardé en cache seulement une fois le Gameday validé
        if chemin.exists() and ev.get("finished"):
            live = json.loads(chemin.read_text(encoding="utf-8"))
        elif hors_ligne:
            continue
        else:
            try:
                r = requests.get(f"{BASE}/event/{ev['id']}/live/", headers=UA, timeout=30)
                r.raise_for_status()
                live = r.json()
                if ev.get("finished"):
                    chemin.write_text(json.dumps(live), encoding="utf-8")
            except Exception as ex:
                print(f"  ! minutes du {ev['name']} indisponibles ({ex.__class__.__name__})")
                continue
        stats = {x["id"]: x["stats"] for x in live.get("elements", [])}
        ont_joue = {equipe[pid] for pid, st in stats.items() if st.get("minutes", 0) > 0 and pid in equipe}
        for pid, eq in equipe.items():
            if eq in ont_joue:
                m = stats.get(pid, {}).get("minutes", 0)
                r_ = res.setdefault(pid, dict(matchs_equipe=0, joues=0, minutes=0))
                r_["matchs_equipe"] += 1
                r_["joues"] += m > 0
                r_["minutes"] += m
    return res


def groupe_rang(rang):
    """Groupe de calibration d'un joueur selon son rang dans la hiérarchie ESPN de son poste."""
    return "1" if rang == 1 else "2" if rang == 2 else "3+" if rang else "?"


def lire_calibration(cfg):
    """Facteurs calculés par bilan.py : points réels / points projetés par le modèle, par groupe de rang."""
    if not cfg.get("calibration_auto"):
        return {}
    try:
        return json.loads((ICI / "rapport" / "calibration.json").read_text(encoding="utf-8"))["facteurs"]
    except Exception:
        return {}


def projeter(boot, cfg, saison_commencee, saison=None):
    priors = json.loads((ICI / "priors.json").read_text(encoding="utf-8"))["joueurs"]
    equipes = {t["id"]: t["short_name"] for t in boot["teams"]}
    calibration = lire_calibration(cfg)
    joueurs = {}
    for e in boot["elements"]:
        pid = e["id"]
        prix = e["now_cost"] / 10
        prior = priors.get(str(pid), {}).get("fppg", 2.59 * prix + 1.4)
        fiab = priors.get(str(pid), {}).get("fiabilite", 0.92)
        b2b = priors.get(str(pid), {}).get("malus_b2b")   # effet mesuré sur la saison passée (maj_b2b.py)
        # Saison en cours : un joueur qui n'entre pas en jeu alors que son équipe joue (choix de l'entraîneur)
        # voit sa probabilité de jouer baisser tout de suite ; ses minutes réelles corrigent sa projection.
        v = priors.get(str(pid), {})
        s = (saison or {}).get(pid)
        if s and s["matchs_equipe"]:
            k = cfg["poids_presence_avant_saison"]
            fiab = (s["joues"] + k * fiab) / (s["matchs_equipe"] + k)
        # Minutes : minutes réelles de la saison + présaison (un demi-match chacune, seulement pour les
        # remplaçants : les titulaires y jouent peu exprès), comparées aux minutes prévues avant la saison.
        joues, minutes = (s["joues"], s["minutes"]) if s else (0, 0)
        rang = v.get("rang_poste")
        if rang and rang > 1 and v.get("presaison_matchs") and v.get("presaison_min"):
            joues += 0.5 * v["presaison_matchs"]
            minutes += 0.5 * v["presaison_matchs"] * v["presaison_min"]
        if joues and v.get("min_proj"):
            # le rôle observé (minutes) recale la projection d'avant-saison : un remplaçant devenu titulaire
            # (blessure d'un coéquipier) monte vite, un joueur sorti de la rotation baisse vite
            w = joues / (joues + cfg["poids_minutes_avant_saison"])
            prior *= (1 - w) + w * min(cfg["plafond_minutes"], (minutes / joues) / v["min_proj"])
        # Points réels de la saison, mélangés à la projection d'avant-saison (recalée sur les minutes)
        proj, g_cur = prior, 0
        if saison_commencee:
            ppg = float(e.get("points_per_game") or 0) / 10
            tot = (e.get("total_points") or 0) / 10
            g_cur = tot / ppg if ppg > 0 else 0
            if g_cur > 0:
                w = g_cur / (g_cur + cfg["poids_points_avant_saison"])
                proj = w * ppg + (1 - w) * prior
                forme = float(e.get("form") or 0) / 10
                if g_cur >= 5 and forme > 0:
                    proj = (1 - cfg["poids_forme"]) * proj + cfg["poids_forme"] * forme
        proj *= cfg["ajustements"].get(e["web_name"], 1.0)
        # Hiérarchie de l'équipe (ESPN) : en fin de rotation, risque de ne pas entrer en jeu
        # Calibration : erreurs passées du modèle pour les joueurs du même rang (voir bilan.py)
        grp = groupe_rang(rang)
        calib = calibration.get(grp, 1.0)
        proj *= calib
        if rang and rang >= 4:
            fiab *= cfg["fiabilite_rang"]["4+"]
        elif rang == 3:
            fiab *= cfg["fiabilite_rang"]["3"]
        statut = e["status"]
        chance = e.get("chance_of_playing_next_round")
        if statut in ("i", "u", "s", "n") or e.get("removed"):
            dispo = 0.0
        elif chance is not None:
            dispo = chance / 100
        else:
            dispo = 1.0
        retour = None
        news = e.get("news") or ""
        if "expected back" in news:
            try:
                retour = dt.date.fromisoformat(news.split("expected back")[1].strip()[:10])
            except ValueError:
                pass
        joueurs[pid] = dict(id=pid, nom=e["web_name"], nom_complet=f"{e['first_name']} {e['second_name']}",
                            equipe_id=e["team"], equipe=equipes[e["team"]], poste=e["element_type"],
                            prix=e["now_cost"], proj=proj, dispo=dispo, fiabilite=fiab, b2b=b2b, retour=retour, statut=statut,
                            news=news, g=g_cur, possede=float(e.get("selected_by_percent") or 0),
                            rang=grp, calib=calib)
    return joueurs


def enregistrer_projections(ev, joueurs, joue):
    """Garde les points attendus de chaque joueur pour le prochain Gameday (dernier calcul avant la deadline),
    sans la calibration, pour que bilan.py mesure les erreurs du modèle après coup."""
    date = (z(ev["deadline_time"]) - dt.timedelta(hours=4)).date()
    proj = {}
    for pid, p in joueurs.items():
        v = ev_jour(p, ev["id"], joue, date)
        if v > 0:
            proj[str(pid)] = [round(v / p["calib"], 2), p["rang"]]
    dossier = ICI / "rapport" / "projections"
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / f"{ev['id']}.json").write_text(json.dumps(
        {"event": ev["id"], "calcul": dt.datetime.now(dt.timezone.utc).isoformat(), "projections": proj}), encoding="utf-8")


def ev_jour(p, ev_id, joue, date_event):
    if ev_id not in joue.get(p["equipe_id"], ()):
        return 0.0
    if p["retour"] and p["retour"] > date_event:
        return 0.0
    v = p["proj"] * p["dispo"] * p["fiabilite"]
    if (p["equipe_id"], ev_id) in B2B:   # 2e soir d'affilée : effet propre au joueur si mesuré, sinon valeur par défaut
        v *= p["b2b"] if p.get("b2b") else MALUS_B2B[0] - (0.04 if p["fiabilite"] < 0.8 or p["retour"] else 0)
    return v   # fiabilité = risque de repos / pépins (≈0,92, moins pour les joueurs fragiles)


def lire_cookie(cfg):
    """Cookie de connexion : secret GitHub NBA_COOKIE (cloud) ou secret_cookie.txt (Mac). Jamais affiché."""
    if os.environ.get("NBA_COOKIE", "").strip():
        c = os.environ["NBA_COOKIE"].strip()
        return c.split(":", 1)[1].strip() if c.lower().startswith("cookie:") else c
    f = ICI / "secret_cookie.txt"
    if f.exists():
        c = f.read_text(encoding="utf-8").strip()
        if c.lower().startswith("cookie:"):
            c = c.split(":", 1)[1].strip()
        if c:
            return c
    return cfg.get("cookie")


def equipe_cookie(eid, cookie, hors_ligne):
    """Route my-team (connecté) : seule source qui voit tes titulaires et transferts AVANT la deadline."""
    if hors_ligne:
        mt, s = lire_cache("my_team_api")
        return (mt, "my-team (cache)") if mt else (None, s)
    import requests
    try:
        r = requests.get(f"{BASE}/my-team/{eid}/", headers=dict(UA, Cookie=cookie), timeout=30)
    except Exception as ex:
        print(f"  ! my-team inaccessible ({ex.__class__.__name__}) : autre source utilisée.")
        return None, f"my-team inaccessible ({ex.__class__.__name__})"
    if r.status_code in (401, 403):
        corps = r.text[:300].lower()
        genre = ("page de blocage (Cloudflare ?)" if "<html" in corps or "cloudflare" in corps
                 else "réponse de l'API : " + re.sub(r"[^a-z .:'é-]", "", corps)[:80])
        print(f"  ! my-team refusé (code {r.status_code}, {genre}). Autre source utilisée.")
        print("    Cookie expiré ou insuffisant : refais l'étape « cookie » du LISEZMOI_launchd.md.")
        return None, "cookie expiré : refais l'étape « cookie » du LISEZMOI_launchd.md"
    if not r.ok:
        return None, f"my-team : erreur {r.status_code}"
    mt = r.json()
    (DONNEES / "my_team_api.json").write_text(json.dumps(mt), encoding="utf-8")
    mt["_source"] = "my-team (connecté, à jour en direct)"
    return mt, mt["_source"]


def equipe_publique(cfg, boot, get):
    """Équipe lue sur les routes publiques du jeu (seulement id_equipe, pas de cookie).

    picks du dernier Gameday passé + transferts faits depuis (ils n'apparaissent dans les picks qu'à la
    deadline suivante). Renvoie un dict au format de « my-team »."""
    eid = cfg["id_equipe"]
    maintenant = dt.datetime.now(dt.timezone.utc)
    passe = max((e for e in boot["events"] if z(e["deadline_time"]) <= maintenant), key=lambda e: e["id"])
    picks, s1 = get("picks_publics", f"{BASE}/entry/{eid}/event/{passe['id']}/picks/", obligatoire=False)
    transferts, _ = get("transferts_publics", f"{BASE}/entry/{eid}/transfers/", obligatoire=False)
    histo, _ = get("historique_public", f"{BASE}/entry/{eid}/history/", obligatoire=False)
    if not picks or not picks.get("picks"):
        print(f"  ! Picks publics introuvables pour le Gameday {passe['id']} : equipe_manuelle utilisée.")
        return None, f"picks publics indisponibles ({s1})"
    elements = {e["id"]: e for e in boot["elements"]}
    transferts = transferts if isinstance(transferts, list) else []
    equipe = [p["element"] for p in picks["picks"]]
    roles = {p["element"]: (p.get("multiplier", 0), p.get("is_captain", False)) for p in picks["picks"]}
    banque = (picks.get("entry_history") or {}).get("bank") or 0
    achats = {}   # prix d'achat
    for t in sorted(transferts, key=lambda t: t.get("time") or ""):
        achats[t["element_in"]] = t["element_in_cost"]
        if t["event"] > passe["id"] and t["element_out"] in equipe:   # transfert pour un Gameday à venir
            equipe[equipe.index(t["element_out"])] = t["element_in"]
            banque += t["element_out_cost"] - t["element_in_cost"]
    frais = boot["game_settings"].get("transfers_sell_on_fee", 0.5)
    def vente(pid):
        e = elements[pid]
        achat = achats.get(pid, e["now_cost"] - (e.get("cost_change_start") or 0))
        return achat + int((e["now_cost"] - achat) * (1 - frais)) if e["now_cost"] > achat else e["now_cost"]
    # Gameweek du prochain Gameday : transferts déjà faits et chips joués
    prochain = min((e for e in boot["events"] if z(e["deadline_time"]) > maintenant), key=lambda e: e["id"], default=passe)
    phase = next(p for p in boot["phases"] if p["start_event"] <= prochain["id"] <= p["stop_event"]
                 and p["stop_event"] - p["start_event"] < 10)
    dans_gw = lambda ev: phase["start_event"] <= ev <= phase["stop_event"]
    faits = sum(1 for t in transferts if dans_gw(t["event"]))
    joues = [c for c in (histo or {}).get("chips", []) if dans_gw(c.get("event") or 0)]
    wildcard = any(c.get("name") == "wildcard" for c in joues)
    mt = dict(picks=[dict(element=pid, selling_price=vente(pid), multiplier=roles.get(pid, (0, False))[0],
                          is_captain=roles.get(pid, (0, False))[1]) for pid in equipe],
              _precedent=passe["name"],
              transfers=dict(bank=banque, made=faits, limit=None if wildcard else cfg["transferts_gratuits_par_defaut"],
                             status="unlimited" if wildcard else "cost"),
              chips=[dict(name="phcapt", start_event=phase["start_event"], stop_event=phase["stop_event"],
                          status_for_entry="played" if any(c.get("name") == "phcapt" for c in joues) else "available")])
    mt["_source"] = f"API publique (picks du {passe['name']} + {faits} transfert(s) cette semaine)"
    return mt, mt["_source"]


# ----------------------------------------------------------------------------- mon équipe
def mon_equipe(mt, cfg, joueurs, boot, gw):
    banque, prix_vente, gratuits, capitaine_dispo = None, {}, cfg["transferts_gratuits_par_defaut"], True
    if mt is not None and not mt.get("picks"):
        print("  ! La réponse « my-team » ne contient pas d'équipe (session expirée ?). Recopie la requête. Équipe manuelle utilisée.")
    if mt and mt.get("picks"):
        ids = [p["element"] for p in mt["picks"]]
        for p in mt["picks"]:
            if p.get("selling_price") is not None:
                prix_vente[p["element"]] = p["selling_price"]
        tr = mt.get("transfers") or {}
        if tr.get("bank") is not None:
            banque = tr["bank"]
        if tr.get("status") == "unlimited" or (tr.get("limit") is None and tr.get("status") not in (None, "cost")):
            gratuits = 15
        elif tr.get("limit") is not None:
            gratuits = max(0, tr["limit"] - (tr.get("made") or 0))
        for c in mt.get("chips") or []:
            if c.get("name") == "phcapt":
                s, f = c.get("start_event"), c.get("stop_event")
                if s is not None and f is not None and not (s <= gw["start_event"] <= f or s <= gw["stop_event"] <= f):
                    continue
                if c.get("status_for_entry") not in (None, "available"):
                    capitaine_dispo = False
        source = mt.get("_source", "my-team (picks, banque et transferts du site)")
    else:
        noms = cfg["equipe_manuelle"]
        if len(noms) != 10:
            sys.exit("Équipe introuvable : crée requete_mon_equipe.txt (voir LISEZMOI) ou liste 10 joueurs dans 'equipe_manuelle'.")
        index = {}
        for p in joueurs.values():
            for cle in (p["nom"].lower(), p["nom_complet"].lower()):
                index.setdefault(cle, []).append(p["id"])
        ids = []
        for n in noms:
            trouve = index.get(n.lower())
            if not trouve:
                sys.exit(f"Joueur introuvable dans equipe_manuelle : {n!r} (utilise le nom affiché dans le jeu, ex. 'T.Maxey').")
            ids.append(trouve[0])
        if cfg.get("capitaine_deja_utilise_cette_semaine"):
            capitaine_dispo = False
        if cfg.get("transferts_restants_cette_semaine") is not None:
            gratuits = cfg["transferts_restants_cette_semaine"]
        source = "config.json (equipe_manuelle)"
    if banque is None:
        banque = round(cfg.get("banque", 0) * 10)
    return ids, banque, prix_vente, gratuits, capitaine_dispo, source


# ----------------------------------------------------------------------------- optimisation
def optimiser(joueurs, equipe, banque, prix_vente, gratuits, cap_dispo, jours, joue, gw_suiv, cfg,
              transferts=True, libre=False, assurance=None, interdits=(), forcer=(), jours_transfert=None,
              entree_jour0=False, joker=False, plein_suiv=False):
    """Plan jour par jour sur la Gameweek en cours + la suivante (pondérée par poids_futur).

    Variables : effectif de chaque jour (s), entrées (in), titulaires (y), capitaine (c).
    Le modèle choisit seul le jour de chaque transfert (regroupés ou non) ; au plus `gratuits`
    transferts gratuits cette semaine et transferts_gratuits_par_defaut la suivante, au-delà -100 pts.
    libre=True (avant la 1re deadline) : l'effectif du 1er jour est choisi librement.
    transferts=False : aucun transfert (référence « ne rien faire »).
    interdits : joueurs qu'on s'interdit d'acheter cette semaine (mesure de la force d'un conseil).
    forcer : [(sortant, entrant, id_event)] transferts imposés (stabilité du conseil d'un calcul à l'autre).
    entree_jour0 : impose au moins un transfert avant la prochaine deadline (voir option_maintenant).
    plein_suiv=True : 5 titulaires imposés chaque jour de la semaine suivante (voir option_plein).
    joker=True (avec libre=True) : équipe refaite avant la prochaine deadline avec ton vrai budget
    (valeur de revente + banque), sans joueur imposé (voir option_joker).
    assurance : {id_event: [V1, V2, …]} = valeur, à partir de ce jour, d'avoir encore au moins 1, 2, …
    transferts en réserve pour remplacer un blessé (voir valeur_reserve). Le transfert qui fait passer
    la réserve de k à k-1 coûte V_k du jour où il est fait."""
    exclus = {n.lower() for n in cfg["joueurs_exclus"]}
    bloques = {n.lower() for n in cfg["joueurs_bloques"]}
    imposes = {n.lower() for n in cfg.get("imposer_au_depart", [])} if libre and not joker else set()
    S0 = set(equipe)
    valeur = lambda p: p["proj"] * p["dispo"] * p["fiabilite"]
    ok = [p for p in joueurs.values() if p["dispo"] > 0 and p["proj"] >= cfg["projection_min"] and p["nom"].lower() not in exclus]
    garder = {p["id"] for p in sorted(ok, key=valeur, reverse=True)[:cfg["nb_candidats"]]}
    garder |= {p["id"] for p in sorted(ok, key=lambda p: valeur(p) / max(p["prix"], 1), reverse=True)[:40]}
    forces_in = {e_ for _, e_, _ in forcer}
    cand = [p for p in joueurs.values() if p["id"] in S0 or p["id"] in garder or p["id"] in forces_in
            or p["nom"].lower() in imposes]
    n = len(cand)

    nb_suiv = {}
    if gw_suiv:
        for eq, evs in joue.items():
            nb_suiv[eq] = sum(1 for ev in evs if gw_suiv["start_event"] <= ev <= gw_suiv["stop_event"])
    # semaine suivante : seulement si son calendrier est complet
    jours_suiv = gw_suiv.get("events", []) if (gw_suiv and sum(nb_suiv.values()) >= 60 and cfg["poids_futur"] > 0) else []
    tous = list(jours) + list(jours_suiv)
    sem = [0] * len(jours) + [1] * len(jours_suiv)
    poids = [1.0 if w == 0 else cfg["poids_futur"] for w in sem]
    dates = {e["id"]: (z(e["deadline_time"]) - dt.timedelta(hours=4)).date() for e in tous}
    D = len(tous)

    idx, c = {}, 0
    def add(key):
        nonlocal c
        idx[key] = c; c += 1
    for d in range(D):
        for i in range(n):
            add(("s", i, d)); add(("in", i, d))
            if ev_jour(cand[i], tous[d]["id"], joue, dates[tous[d]["id"]]) > 0:
                add(("y", i, d)); add(("c", i, d))
    for w in (0, 1):
        add(("hit", w))
    libres = {0: gratuits, 1: cfg["transferts_gratuits_par_defaut"]}
    if assurance and transferts:
        for d in range(D):
            for k in range(1, min(libres[sem[d]], 3) + 1):
                add(("u", sem[d], k, d))   # u = 1 si au moins k transferts faits cette semaine à la fin du jour d
    N = c
    obj = np.zeros(N); lb = np.zeros(N); ub = np.ones(N); integ = np.zeros(N)
    rows, lo, hi = [], [], []
    def row(co, l, h): rows.append(co); lo.append(l); hi.append(h)

    cout = lambda p: prix_vente.get(p["id"], p["prix"]) if p["id"] in S0 else p["prix"]
    budget = banque + sum(prix_vente.get(pid, joueurs[pid]["prix"]) for pid in S0)
    if libre:
        budget, cout = (budget if joker else max(budget, 1000)), (lambda p: p["prix"])
    dernier_jour = {w: max(d for d in range(D) if sem[d] == w) for w in set(sem)}
    for d in range(D):
        S = {i: idx[("s", i, d)] for i in range(n)}
        for v in S.values():
            integ[v] = 1
        row({S[i]: cout(p) for i, p in enumerate(cand)}, 0, budget)
        for pos in (1, 2):
            row({S[i]: 1 for i, p in enumerate(cand) if p["poste"] == pos}, 5, 5)
        for eq in {p["equipe_id"] for p in cand}:
            row({S[i]: 1 for i, p in enumerate(cand) if p["equipe_id"] == eq}, 0, 2)
        for i, p in enumerate(cand):
            v_in = idx[("in", i, d)]
            if d == 0 and libre:
                ub[v_in] = 0                      # 1er jour : changements gratuits et illimités
                if p["nom"].lower() in imposes:
                    lb[S[i]] = 1
            elif d == 0:
                row({v_in: 1, S[i]: -1}, -(1 if p["id"] in S0 else 0), np.inf)   # in >= s - s0
            else:
                row({v_in: 1, S[i]: -1, idx[("s", i, d - 1)]: 1}, 0, np.inf)        # in >= s(d) - s(d-1)
            if p["id"] in S0 and p["nom"].lower() in bloques:
                lb[S[i]] = 1
            if sem[d] == 0 and p["id"] in interdits and p["id"] not in S0:
                ub[S[i]] = 0
            for so, en, ev in forcer:
                if sem[d] == 0 and tous[d]["id"] >= ev:
                    if p["id"] == en:
                        lb[S[i]] = 1
                    elif p["id"] == so:
                        ub[S[i]] = 0
            # petit bonus d'attente : à gain égal, on attend (plus d'infos sur les blessures)
            obj[v_in] = cfg["bonus_attente"] * (dernier_jour[sem[d]] - d)
        if (not transferts and not (d == 0 and libre)) or (
                jours_transfert is not None and sem[d] == 0 and tous[d]["id"] not in jours_transfert):
            for i in range(n):
                ub[idx[("in", i, d)]] = 0   # jours_transfert : jours autorisés pour les transferts de cette semaine
    # Réserve pour blessure : le transfert qui fait passer la réserve de r à r-1 coûte V_r du jour où il est fait.
    # Avec u(k,d) = « au moins k transferts faits à la fin du jour d » : coût = Σ_d V_r(d) (u(k,d) - u(k,d-1)),
    # réécrit Σ_d u(k,d) (V_r(d) - V_r(d+1)) ≥ 0 car V_r décroît au fil de la semaine.
    for key, v in [(key, v) for key, v in idx.items() if key[0] == "u"]:
        _, w, k, d = key
        integ[v] = 1
        cumul = {idx[("in", i, dd)]: 1 for dd in range(D) if sem[dd] == w and dd <= d for i in range(n)}
        row({**cumul, v: -20}, -np.inf, k - 1)
        r = libres[w] - k + 1
        val = lambda dd: (assurance.get(tous[dd]["id"]) or [0] * 3)[r - 1] if dd < D and sem[dd] == w else 0.0
        obj[v] = poids[d] * max(0.0, val(d) - val(d + 1))
    for w, g in ((0, gratuits), (1, cfg["transferts_gratuits_par_defaut"])):
        h = idx[("hit", w)]
        ub[h] = 10 if transferts else 0; integ[h] = 1
        obj[h] = 100 * (1.0 if w == 0 else cfg["poids_futur"])
        co = {idx[("in", i, d)]: 1 for d in range(D) if sem[d] == w for i in range(n)}
        if co:
            co[h] = -1
            row(co, -np.inf, g)
    if entree_jour0 and transferts and not libre:
        row({idx[("in", i, 0)]: 1 for i in range(n)}, 1, np.inf)

    for d, e in enumerate(tous):
        ys = [i for i in range(n) if ("y", i, d) in idx]
        for i in ys:
            v = poids[d] * ev_jour(cand[i], e["id"], joue, dates[e["id"]])
            obj[idx[("y", i, d)]] = -v; obj[idx[("c", i, d)]] = -v
            row({idx[("y", i, d)]: 1, idx[("s", i, d)]: -1}, -np.inf, 0)
            row({idx[("c", i, d)]: 1, idx[("y", i, d)]: -1}, -np.inf, 0)
        if ys:
            row({idx[("y", i, d)]: 1 for i in ys}, 5 if (plein_suiv and sem[d] == 1) else 0, 5)
            for pos in (1, 2):
                row({idx[("y", i, d)]: 1 for i in ys if cand[i]["poste"] == pos}, 0, 3)
    for w in set(sem):   # un capitaine par Gameweek
        cs = [v for kk, v in idx.items() if kk[0] == "c" and sem[kk[2]] == w]
        if cs:
            row({v: 1 for v in cs}, 0, 1 if (cap_dispo or w == 1) else 0)

    A = lil_matrix((len(rows), N))
    for r, co in enumerate(rows):
        for jj, v in co.items():
            A[r, jj] = v
    res = milp(obj, constraints=LinearConstraint(A.tocsr(), lo, hi), integrality=integ,
               bounds=Bounds(lb, ub), options={"time_limit": cfg["temps_max_calcul"], "mip_rel_gap": 0.002})
    if res.x is None:
        return None
    x = res.x
    effectifs = [[cand[i]["id"] for i in range(n) if x[idx[("s", i, d)]] > .5] for d in range(D)]
    depart = effectifs[0] if libre else list(equipe)
    jours_plan = []
    for d, e in enumerate(tous):
        tit = [cand[i]["id"] for i in range(n) if ("y", i, d) in idx and x[idx[("y", i, d)]] > .5]
        cap = next((cand[i]["id"] for i in range(n) if ("c", i, d) in idx and x[idx[("c", i, d)]] > .5), None)
        avant = depart if d == 0 else effectifs[d - 1]
        jours_plan.append(dict(event=e, titulaires=tit, capitaine=cap, effectif=effectifs[d],
                               sortants=[q for q in avant if q not in effectifs[d]],
                               entrants=[q for q in effectifs[d] if q not in avant],
                               b2b=[q for q in tit if (joueurs[q]["equipe_id"], e["id"]) in B2B],
                               points=sum(ev_jour(joueurs[q], e["id"], joue, dates[e["id"]]) for q in tit)
                               + (ev_jour(joueurs[cap], e["id"], joue, dates[e["id"]]) if cap else 0)))
    plan, plan2 = jours_plan[:len(jours)], jours_plan[len(jours):]
    final = plan[-1]["effectif"]
    hits = int(round(x[idx[("hit", 0)]]))
    hits2 = int(round(x[idx[("hit", 1)]]))
    return dict(final=final, depart=depart, plan=plan, plan2=plan2, pts_semaine=sum(p["points"] for p in plan),
                score=-res.fun, hits=hits, hits2=hits2, sortants=[p for p in depart if p not in final],
                entrants=[p for p in final if p not in depart],
                transferts=[(jp["event"], jp["sortants"], jp["entrants"]) for jp in plan if jp["entrants"]],
                transferts_suiv=[(jp["event"], jp["sortants"], jp["entrants"]) for jp in plan2 if jp["entrants"]])


def points_projetes(r, cfg):
    """Points projetés d'un plan : cette semaine + suivante pondérée, moins les transferts payants des deux."""
    return (r["pts_semaine"] + cfg["poids_futur"] * sum(jp["points"] for jp in r["plan2"])
            - 100 * r["hits"] - 100 * cfg["poids_futur"] * r.get("hits2", 0))


def valeur_reserve(base, joueurs, joue, cfg, libres):
    """Valeur, jour par jour, d'avoir encore 1, 2, … transferts en réserve jusqu'à la fin de la semaine.

    Calculée sur le plan « sans transfert » : si un joueur se blesse au match du jour t, une réserve permet
    de le remplacer dès le jour suivant. On récupère alors taux_recuperation × ce qu'il aurait apporté
    au-delà de ton meilleur remplaçant du banc, sur ses soirs de titulaire (sur ses duree_blessure_matchs
    prochains matchs). Les soirs où tu as 6+ joueurs, un blessé coûte donc peu ; les soirs à 5 ou moins, beaucoup.
    Risque de blessure par match = (1 - fiabilité) / duree_blessure_matchs.
    Nombre de blessures ~ Poisson(Λ) : V_k = gain moyen par blessure × P(au moins k blessures)."""
    import math
    L, r = cfg["duree_blessure_matchs"], cfg["taux_recuperation"]
    res = {}
    for semaine, nb in ((base["plan"], libres[0]), (base["plan2"], libres[1])):
        if not semaine:
            continue
        date = lambda jp: (z(jp["event"]["deadline_time"]) - dt.timedelta(hours=4)).date()
        val = lambda q, jp: ev_jour(joueurs[q], jp["event"]["id"], joue, date(jp))
        # apport de chaque titulaire au-delà du meilleur remplaçant du banc, jour par jour
        apport = []
        for jp in semaine:
            banc = [val(q, jp) for q in jp["effectif"] if q not in jp["titulaires"]]
            meilleur_banc = max(banc, default=0.0)
            apport.append({q: max(0.0, val(q, jp) - meilleur_banc) for q in jp["titulaires"]})
        gains, risques = [0.0] * len(semaine), [0.0] * len(semaine)
        for t, jp in enumerate(semaine):
            for q in jp["effectif"]:
                if val(q, jp) <= 0:
                    continue   # ne joue pas ce soir-là : pas de risque de blessure
                lam = (1 - joueurs[q]["fiabilite"]) / L
                suite = [apport[u].get(q, 0.0) for u in range(t + 1, len(semaine))
                         if val(q, semaine[u]) > 0][:L]
                gains[t] += lam * r * sum(suite)
                risques[t] += lam
        for d, jp in enumerate(semaine):
            A, lam = sum(gains[d:]), sum(risques[d:])
            moyen = A / lam if lam > 0 else 0.0
            p = math.exp(-lam)
            proba, cumul = [], p
            for k in range(1, min(nb, 3) + 1):
                proba.append(max(0.0, 1 - cumul))           # P(N >= k)
                cumul += p * lam ** k / math.factorial(k)
            res[jp["event"]["id"]] = [moyen * q for q in proba] + [0.0] * 3
    return res


def meilleur_plan(*args, libre=False):
    base = optimiser(*args, transferts=False, libre=libre)
    cfg = args[9]
    base["assurance"] = valeur_reserve(base, args[0], args[7], cfg, {0: args[4], 1: cfg["transferts_gratuits_par_defaut"]}) if base else None
    plan = optimiser(*args, transferts=True, libre=libre, assurance=base and base["assurance"])
    # Comme le conseille NBA.com : si le gain est minime, on ne fait rien (marge pour les blessures)
    if plan is None or (base and plan["score"] - base["score"] < 3.0 and plan["entrants"]):
        plan = base
    return plan, base


# ----------------------------------------------------------------------------- suivi du conseil
def paires(sortants, entrants, joueurs):
    """Associe chaque sortant à un entrant du même poste (pour l'affichage)."""
    return list(zip(sorted(sortants, key=lambda q: joueurs[q]["poste"]), sorted(entrants, key=lambda q: joueurs[q]["poste"])))


def option_maintenant(plan, args_plan, base, cfg, joueurs):
    """Quand des places de titulaires restent vides au prochain jour et qu'aucun transfert n'y est prévu,
    compare le plan avec « au moins un transfert dès ce jour-là », pour montrer l'arbitrage :
    points gagnés tout de suite contre transfert(s) gardé(s) en réserve pour un blessé."""
    j0 = plan["plan"][0]
    if j0["entrants"] or len(j0["titulaires"]) >= 5 or args_plan[4] <= 0:
        return ""
    f = optimiser(*args_plan, transferts=True, assurance=base["assurance"], entree_jour0=True)
    if not f:
        return ""
    pts = lambda r: points_projetes(r, cfg)
    jour = lambda ev: ev["name"].split(" - ")[-1]
    tr = " ; ".join(f"{jour(ev)} : " + ", ".join(f"{nom(joueurs, a)} → {nom(joueurs, b)}" for a, b in paires(so, en, joueurs))
                    for ev, so, en in f["transferts"])
    d_pts, d_score = pts(f) - pts(plan), f["score"] - plan["score"]
    verdict = "les deux se valent, à toi de choisir" if d_score > -5 else "l'assistant préfère attendre"
    return (f"Option « transférer dès {jour(j0['event'])} » (seulement {len(j0['titulaires'])} titulaire(s) ce jour-là) : {tr}. "
            f"Points projetés {d_pts:+.0f} par rapport au plan conseillé, mais avec moins de transferts en réserve "
            f"pour remplacer un blessé : bilan {d_score:+.0f} pts → {verdict}.")


def option_joker(plan, args_plan, base, cfg, joueurs):
    """À titre indicatif : ce que rapporterait une équipe refaite de zéro (joker) avant la prochaine deadline,
    comparée au plan conseillé, sur cette semaine et la suivante (pondérée)."""
    f = optimiser(*args_plan, transferts=True, libre=True, assurance=base["assurance"], joker=True)
    if not f:
        return ""
    pts = lambda r: points_projetes(r, cfg)
    gain = pts(f) - pts(plan)
    equipe = args_plan[1]
    changes = len([q for q in f["depart"] if q not in equipe])
    entrants = ", ".join(nom(joueurs, q) for q in sorted(f["depart"], key=lambda q: -joueurs[q]["proj"]) if q not in equipe)
    avis = ("✅ le joker vaut le coup maintenant" if gain >= cfg["seuil_joker"]
            else f"garde-le (seuil conseillé : +{cfg['seuil_joker']} pts)")
    return (f"Joker (indicatif) : une équipe refaite avant la prochaine deadline rapporterait {gain:+.0f} pts "
            f"sur cette semaine et la suivante, avec {changes} joueur(s) changé(s) ({entrants}) → {avis}.")


def valeurs_equipe(equipe, joueurs, jours, gw_suiv, joue, cfg):
    """Points attendus de chacun de tes joueurs d'ici la fin de la semaine et la semaine suivante,
    du moins utile au plus utile (repère pour savoir de qui se séparer en premier)."""
    date = lambda e: (z(e["deadline_time"]) - dt.timedelta(hours=4)).date()
    suiv = (gw_suiv or {}).get("events", [])
    lignes = []
    for q in equipe:
        p = joueurs[q]
        v1 = [ev_jour(p, e["id"], joue, date(e)) for e in jours]
        v2 = [ev_jour(p, e["id"], joue, date(e)) for e in suiv]
        total = sum(v1) + cfg["poids_futur"] * sum(v2)
        lignes.append(dict(id=q, nom=nom(joueurs, q), prix=p["prix"] / 10, proj=p["proj"], fiab=p["fiabilite"],
                           n1=sum(1 for e in jours if e["id"] in joue.get(p["equipe_id"], ())), pts1=sum(v1),
                           n2=sum(1 for e in suiv if e["id"] in joue.get(p["equipe_id"], ())), pts2=sum(v2),
                           total=total, par_m=total / max(p["prix"] / 10, 1)))
    return sorted(lignes, key=lambda l: l["par_m"])


def tester_idees(plan, args_plan, base, cfg, joueurs, boot, saison):
    """Teste les transferts proposés par toi (config "idees" : "Sortant>Entrant@jour", plusieurs transferts
    séparés par « + ») contre le plan conseillé. Le reste (autres transferts, semaine suivante, usage de
    l'argent économisé) est optimisé autour de ton idée."""
    joueurs_, equipe, jours = args_plan[0], args_plan[1], args_plan[6]
    par_nom = {}
    for q, p in joueurs_.items():
        par_nom.setdefault(p["nom"].lower(), []).append(q)
    elements = {e["id"]: e for e in boot["elements"]}
    pts = lambda r: points_projetes(r, cfg)
    lignes = []
    for idee in cfg.get("idees", []):
        try:
            forces = []
            for morceau in idee.split("+"):
                noms, _, jour = morceau.partition("@")
                so_nom, en_nom = (x.strip().lower() for x in noms.split(">"))
                so = next(q for q in par_nom.get(so_nom, []) if q in equipe)
                en = next(q for q in par_nom.get(en_nom, []) if q not in equipe)
                ev = next((e for e in jours if e["name"].endswith(f"Day {jour.strip()}")), jours[0]) if jour else jours[0]
                forces.append((so, en, ev["id"]))
        except (StopIteration, ValueError):
            lignes.append(f"Idée « {idee} » : joueur ou jour introuvable (format : Sortant>Entrant@numéro du jour).")
            continue
        f = optimiser(*args_plan, transferts=True, assurance=base["assurance"], forcer=forces)
        e = elements[en]
        s_ = (saison or {}).get(en) or {}
        stats = (f"{s_.get('joues', 0)} match(s) joué(s), {float(e.get('points_per_game') or 0) / 10:.1f} pts/match"
                 + (f" en {s_['minutes'] / s_['joues']:.0f} min" if s_.get("joues") else ""))
        if not f:
            lignes.append(f"Idée {nom(joueurs, so)} → {nom(joueurs, en)} ({ev['name'].split(' - ')[-1]}) : impossible "
                          f"(budget, poste ou 3e joueur de la même équipe).")
            continue
        imposes_ = {(a, b) for a, b, _ in forces}
        autres = [(e_["name"].split(" - ")[-1], a, b) for e_, so_l, en_l in f["transferts"] for a, b in paires(so_l, en_l, joueurs)
                  if (a, b) not in imposes_]
        suiv = [(e_["name"].split(" - ")[-1], a, b) for e_, so_l, en_l in f["transferts_suiv"] for a, b in paires(so_l, en_l, joueurs)]
        nom_jour = {e_["id"]: e_["name"].split(" - ")[-1] for e_ in jours}
        titre = " + ".join(f"{nom(joueurs, a)} → {nom(joueurs, b)} ({nom_jour[ev_]})" for a, b, ev_ in forces)
        banque, prix_vente = args_plan[2], args_plan[3]
        reste = (banque + sum(prix_vente.get(q, joueurs[q]["prix"]) for q in f["sortants"])
                 - sum(joueurs[q]["prix"] for q in f["entrants"])) / 10
        try:
            creux_txt = creux(f, joueurs, args_plan[7], boot, args_plan[8])
        except Exception as ex:
            creux_txt = f"non calculés ({ex.__class__.__name__})"
        lignes.append(
            f"Ton idée {titre} : "
            f"{pts(f) - pts(plan):+.0f} pts projetés par rapport au plan conseillé (bilan {f['score'] - plan['score']:+.0f}). "
            f"{e['web_name']} : {joueurs[en]['proj']:.1f} pts/match projetés, fiabilité {joueurs[en]['fiabilite']:.2f} ; "
            f"cette saison {stats}. Banque en fin de semaine : {reste:.1f} M$."
            + (" Avec, en plus : " + ", ".join(f"{d} : {nom(joueurs, a, False)} → {nom(joueurs, b, False)}" for d, a, b in autres) + "."
               if autres else "")
            + (" Semaine suivante : " + ", ".join(f"{d} : {nom(joueurs, a, False)} → {nom(joueurs, b, False)}" for d, a, b in suiv) + "."
               if suiv else "")
            + f" Jours creux — {creux_txt}.")
    return lignes


def option_plein(plan, args_plan, base, cfg, joueurs):
    """Si la semaine suivante a des places vides : le meilleur plan qui les comble toutes (5 titulaires
    chaque jour), avec les mêmes transferts disponibles, comparé au plan conseillé."""
    vides = sum(5 - len(jp["titulaires"]) for jp in plan.get("plan2") or [])
    if not vides:
        return ""
    f = optimiser(*args_plan, transferts=True, assurance=base["assurance"], plein_suiv=True)
    if not f:
        return (f"Combler les {vides} place(s) vide(s) de la semaine suivante : impossible avec tes transferts "
                f"(pas assez de joueurs qui jouent ces jours-là dans ton budget).")
    pts = lambda r: points_projetes(r, cfg)
    tr = lambda r: " ; ".join(f"{e_['name'].split(' - ')[-1]} : " + ", ".join(
        f"{nom(joueurs, a, False)} → {nom(joueurs, b, False)}" for a, b in paires(so, en, joueurs))
        for e_, so, en in r["transferts"] + r["transferts_suiv"])
    pts2 = lambda r: sum(jp["points"] for jp in r["plan2"])
    return (f"Combler les {vides} place(s) vide(s) de la semaine suivante est possible : {tr(f)}"
            + (f" (dont {f['hits'] + f['hits2']} transfert(s) payant(s) à -100 pts)" if f["hits"] + f["hits2"] else "")
            + f". Semaine suivante {pts2(f) - pts2(plan):+.0f} pts, au total {pts(f) - pts(plan):+.0f} pts "
            f"par rapport au plan conseillé (cette semaine + suivante pondérée).")


def creux(r, joueurs, joue, boot, gw_suiv):
    """Jours creux d'un plan : places vides de la semaine suivante (plan jour par jour), puis, pour la
    semaine d'après (calendrier seulement, effectif final sans nouveau transfert), le nombre de joueurs
    qui jouent chaque jour et les places qu'on ne pourra pas remplir (5 titulaires, 3 max par poste)."""
    vides2 = [(jp["event"]["name"].split(" - ")[-1], 5 - len(jp["titulaires"])) for jp in r.get("plan2") or []
              if len(jp["titulaires"]) < 5]
    txt = ("semaine suivante : " + (", ".join(f"{d} {v} vide(s)" for d, v in vides2) if vides2 else "aucune place vide"))
    if not gw_suiv:
        return txt
    gw3 = next((p for p in boot["phases"] if p["name"].lower().startswith("gameweek")
                and p["start_event"] == gw_suiv["stop_event"] + 1), None)
    if not gw3:
        return txt
    final = (r["plan2"][-1]["effectif"] if r.get("plan2") else r["final"])
    jours3, total_vides, matchs = [], 0, 0
    for ev in range(gw3["start_event"], gw3["stop_event"] + 1):
        jouent = [q for q in final if ev in joue.get(joueurs[q]["equipe_id"], ())]
        matchs += len(jouent)
        possibles = min(5, min(3, sum(joueurs[q]["poste"] == 1 for q in jouent)) + min(3, sum(joueurs[q]["poste"] == 2 for q in jouent)))
        total_vides += 5 - possibles
        jours3.append(f"{len(jouent)}")
    return (txt + f" | semaine d'après ({gw3['name']}, sans transfert) : {matchs} matchs pour ton effectif, "
            f"{total_vides} place(s) vide(s) ; joueurs dispo par jour : {'-'.join(jours3)}")


def quand_txt(ev):
    """« ce soir » si la deadline tombe aujourd'hui (heure de Paris), sinon « le Day N »."""
    d = z(ev["deadline_time"]).astimezone(PARIS).date()
    return "ce soir" if d == dt.datetime.now(PARIS).date() else f"le {ev['name'].split(' - ')[-1]}"


def alertes_equipe(mt, plan, joueurs, joue):
    """Écarts entre ton équipe sur le site et le conseil pour la prochaine deadline.

    Renvoie (alertes sûres, alertes « à vérifier », note). Titulaires et capitaine ne sont sûrs qu'avec
    le cookie (my-team en direct) ; d'après une copie (mon_equipe.json), ils sont seulement « à vérifier »."""
    if not mt or not mt.get("picks") or "multiplier" not in mt["picks"][0]:
        return [], [], "titulaires non vérifiables (ajoute le cookie, voir LISEZMOI_launchd.md)"
    j0 = plan["plan"][0]
    ev = j0["event"]
    quand = quand_txt(ev)
    reel = {p["element"]: p for p in mt["picks"]}
    precedent = mt.get("_precedent")
    al = []
    # transferts conseillés avant cette deadline mais pas encore faits
    for so, en in paires(j0.get("sortants", []), j0.get("entrants", []), joueurs):
        if en not in reel:
            al.append(f"Transfert à faire avant cette deadline : {joueurs[so]['nom']} → {joueurs[en]['nom']}")
    titulaires_reels = [q for q, p in reel.items() if p.get("multiplier", 0) > 0 and q in joueurs]
    for q in reel:
        p = joueurs.get(q)
        if p and (p["dispo"] < 1 or p["statut"] != "a") and (q in titulaires_reels or q in j0["titulaires"]):
            al.append(f"{p['nom']} : {p['news'] or 'statut ' + p['statut']} ({int(p['dispo'] * 100)} % de chances de jouer)")
    if precedent:   # picks publics = composition du Gameday passé : on ne peut pas juger les titulaires de ce soir
        return al, [], f"titulaires et capitaine non vérifiables avant la deadline sans cookie (équipe lue : {precedent})"
    sures = al
    al = []
    for q in titulaires_reels:
        if ev["id"] not in joue.get(joueurs[q]["equipe_id"], ()):
            al.append(f"{joueurs[q]['nom']} est titulaire mais {joueurs[q]['equipe']} ne joue pas {quand}")
    for q in j0["titulaires"]:
        if q in reel and q not in titulaires_reels:
            al.append(f"{joueurs[q]['nom']} joue {quand} mais est sur ton banc (conseillé titulaire)")
    actif = any(c.get("name") == "phcapt" and c.get("is_pending") for c in mt.get("chips") or [])
    cap_reel = next((q for q, p in reel.items() if p.get("is_captain")), None)
    cap_jour = next((jp for jp in plan["plan"] if jp["capitaine"]), None)
    if actif and j0["capitaine"] is None:
        garde = f" pour le {cap_jour['event']['name'].split(' - ')[-1]} ({joueurs[cap_jour['capitaine']]['nom']})" if cap_jour else ""
        al.append(f"Capitaine activé {quand} alors que le conseil est de le garder{garde}")
    elif j0["capitaine"] and not actif:
        al.append(f"Active le capitaine {quand} sur {joueurs[j0['capitaine']]['nom']}")
    elif actif and cap_reel and cap_reel != j0["capitaine"]:
        al.append(f"Capitaine sur {joueurs.get(cap_reel, {}).get('nom', '?')}, le conseil est {joueurs[j0['capitaine']]['nom']}")
    if mt.get("_copie"):
        return sures, al, f"titulaires et capitaine d'après ton équipe copiée à {mt['_copie']} : à vérifier sur le site"
    return sures + al, [], ""


def badge(gain, cfg):
    return ("🟢 Fort" if gain >= cfg["force_fort"] else "🟡 Léger" if gain >= cfg["force_leger"] else "⚪ Facultatif")


def forces_conseils(plan, args_plan, libre, cfg, joueurs, joue):
    """Gain de chaque transfert (on relance le calcul sans lui) et du capitaine (estimation directe)."""
    forces = {}
    for ev, so_l, en_l in plan["transferts"]:
        for so, en in paires(so_l, en_l, joueurs):
            alt = optimiser(*args_plan, transferts=True, libre=libre, assurance=plan.get("assurance"), interdits={en})
            gain = plan["score"] - alt["score"] if alt else 0.0
            forces[(ev["id"], so, en)] = (gain, badge(gain, cfg))
    cap_jour = next((jp for jp in plan["plan"] if jp["capitaine"]), None)
    if cap_jour:
        date = lambda jp: (z(jp["event"]["deadline_time"]) - dt.timedelta(hours=4)).date()
        v = lambda q, jp: ev_jour(joueurs[q], jp["event"]["id"], joue, date(jp))
        autre = max((v(q, jp) for jp in plan["plan"] if jp is not cap_jour for q in jp["titulaires"]), default=0.0)
        gain = v(cap_jour["capitaine"], cap_jour) - autre   # par rapport au meilleur autre jour possible
        forces["capitaine"] = (gain, badge(gain, cfg) if gain >= 1 else "⚪ Au choix (autre jour ≈ pareil)")
    return forces


def instantane(plan, boot, gw, joueurs):
    """Ce qu'on garde d'un calcul pour le comparer au suivant (rapport/dernier_plan.json)."""
    cap = next((jp for jp in plan["plan"] if jp["capitaine"]), None)
    return dict(calcul=dt.datetime.now(dt.timezone.utc).isoformat(), gw=gw["id"], prochaine=plan["plan"][0]["event"]["id"],
                titulaires=plan["plan"][0]["titulaires"], capitaine=[cap["capitaine"], cap["event"]["id"]] if cap else None,
                transferts=[[ev["id"], so, en] for ev, so_l, en_l in plan["transferts"] for so, en in paires(so_l, en_l, joueurs)],
                score=plan["score"],
                statuts={str(e["id"]): [e["status"], e["news"], e["now_cost"]] for e in boot["elements"]})


def changements(prec, plan, joueurs, boot, gw):
    """« Changements depuis le calcul de HH:MM : … » avec la raison probable."""
    if not prec or prec.get("gw") != gw["id"]:
        return None
    nouv = instantane(plan, boot, gw, joueurs)
    diffs = []
    tr_a = {(t[1], t[2]) for t in prec["transferts"]}
    tr_n = {(t[1], t[2]) for t in nouv["transferts"]}
    for so, en in tr_n - tr_a:
        diffs.append(f"nouveau transfert {joueurs[so]['nom']} → {joueurs[en]['nom']}")
    for so, en in tr_a - tr_n:
        if so in joueurs and en in joueurs:
            diffs.append(f"plus de transfert {joueurs[so]['nom']} → {joueurs[en]['nom']}")
    jours_a = {(t[1], t[2]): t[0] for t in prec["transferts"]}
    for t in nouv["transferts"]:
        if (t[1], t[2]) in jours_a and jours_a[(t[1], t[2])] != t[0]:
            diffs.append(f"{joueurs[t[1]]['nom']} → {joueurs[t[2]]['nom']} déplacé")
    if prec.get("capitaine") != nouv["capitaine"] and nouv["capitaine"]:
        diffs.append(f"capitaine : {joueurs[nouv['capitaine'][0]]['nom']}")
    if prec.get("prochaine") == nouv["prochaine"] and set(prec["titulaires"]) != set(nouv["titulaires"]):
        diffs.append("titulaires modifiés")
    if not diffs:
        return None
    impliques = {q for t in prec["transferts"] + nouv["transferts"] for q in t[1:]} | set(prec["titulaires"]) | set(nouv["titulaires"])
    raisons = []
    for q in impliques:
        a, n = prec["statuts"].get(str(q)), nouv["statuts"].get(str(q))
        if a and n and (a[0] != n[0] or a[1] != n[1]) and q in joueurs:
            raisons.append(f"{joueurs[q]['nom']} : {n[1] or 'statut ' + n[0]}")
        elif a and n and a[2] != n[2] and q in joueurs:
            raisons.append(f"prix de {joueurs[q]['nom']} {a[2] / 10:.1f} → {n[2] / 10:.1f} M$")
    heure = dt.datetime.fromisoformat(prec["calcul"]).astimezone(PARIS).strftime("%Hh%M")
    raison = "; ".join(raisons) if raisons else "pas de nouvelle info : simple écart entre plans presque équivalents"
    return f"Changements depuis le calcul de {heure} : {', '.join(diffs)}. Raison probable : {raison}."


def resume_notif(plan, joueurs, alertes, forces, a_verifier=()):
    """Texte court de l'encadré, pour la notification (sans donnée personnelle)."""
    j0 = plan["plan"][0]
    tit = ", ".join(joueurs[q]["nom"] + (" (B2B)" if (joueurs[q]["equipe_id"], j0["event"]["id"]) in B2B else "")
                    for q in j0["titulaires"]) or "aucun"
    tr = [f"{joueurs[so]['nom']}→{joueurs[en]['nom']}" for so, en in paires(j0.get("sortants", []), j0.get("entrants", []), joueurs)]
    cap_jour = next((jp for jp in plan["plan"] if jp["capitaine"]), None)
    if cap_jour is j0:
        cap = f"activer sur {joueurs[j0['capitaine']]['nom']}"
    elif cap_jour:
        cap = f"non, garder pour {cap_jour['event']['name'].split(' - ')[-1]} ({joueurs[cap_jour['capitaine']]['nom']})"
    else:
        cap = "non"
    lignes = [f"✅ {tit}", f"🔁 {', '.join(tr) if tr else 'Aucun transfert'}", f"⭐ Capitaine : {cap}"]
    lignes += [f"⚠️ {a}" for a in alertes] + [f"🔶 À vérifier : {a}" for a in a_verifier]
    return "\n".join(lignes)


# ----------------------------------------------------------------------------- rapport
def nom(joueurs, pid, avec_equipe=True):
    p = joueurs[pid]
    return f"{p['nom']} ({p['equipe']})" if avec_equipe else p["nom"]


def rapport(joueurs, equipe, banque, gratuits, cap_dispo, gw, jours, joue, matchs, plan, base, sources, src_equipe, boot,
            actuelle=None, suivi=None):
    suivi = suivi or {}
    forces = suivi.get("forces", {})
    maintenant = dt.datetime.now(dt.timezone.utc)
    j0 = plan["plan"][0]
    dl0 = z(j0["event"]["deadline_time"])
    lignes = []
    P = lignes.append
    P(f"=== {gw['name']} — prochaine deadline : {j0['event']['name']} le {paris(dl0)} (heure de Paris) ===")
    P(f"Équipe lue depuis : {src_equipe} | Banque : {banque/10:.1f} M$ | Transferts gratuits restants : {gratuits} | Capitaine dispo : {'oui' if cap_dispo else 'non'}")
    P("")
    if actuelle is not None:
        P("▶ ÉQUIPE DE DÉPART À VALIDER AVANT LA 1RE DEADLINE (changements gratuits et illimités)")
        for pid in sorted(equipe, key=lambda q: (joueurs[q]["poste"], -joueurs[q]["prix"])):
            p = joueurs[pid]
            nouveau = "" if pid in actuelle else "   (nouveau)"
            P(f"  {'BC' if p['poste']==1 else 'FC'}  {nom(joueurs, pid):<28} {p['prix']/10:5.1f} M$  proj. {p['proj']:.1f}{nouveau}")
        retires = [q for q in actuelle if q not in equipe]
        if retires:
            P("  À retirer de ton équipe actuelle : " + ", ".join(nom(joueurs, q) for q in retires))
        P(f"  Coût : {sum(joueurs[q]['prix'] for q in equipe)/10:.1f} M$")
        P("")
    if suivi.get("alertes"):
        P("⚠ À CORRIGER SUR LE SITE AVANT LA DEADLINE")
        for a in suivi["alertes"]:
            P(f"  - {a}")
        P("")
    if suivi.get("a_verifier"):
        P("🔶 À VÉRIFIER SUR LE SITE")
        for a in suivi["a_verifier"]:
            P(f"  - {a}")
    if suivi.get("note_alertes"):
        P(f"  ({suivi['note_alertes']})")
    if suivi.get("changements"):
        P(suivi["changements"])
    if suivi.get("stabilite"):
        P(suivi["stabilite"])
    if suivi.get("maintenant"):
        P(suivi["maintenant"])
    if suivi.get("joker"):
        P(suivi["joker"])
    if suivi.get("ligue"):
        P("🏆 " + suivi["ligue"])
    if suivi.get("creux"):
        P("📅 Jours creux du plan conseillé — " + suivi["creux"])
    if suivi.get("plein"):
        P("🧩 " + suivi["plein"])
    for l in suivi.get("idees", []):
        P("💭 " + l)
    alertes = [pid for pid in equipe if joueurs[pid]["dispo"] < 1 or joueurs[pid]["news"]]
    if alertes:
        P("⚠ ALERTES")
        for pid in alertes:
            p = joueurs[pid]
            P(f"  - {nom(joueurs, pid)} : {p['news'] or 'statut ' + p['statut']} (chance de jouer {int(p['dispo']*100)} %)")
        P("")
    P("▶ CINQ DE DÉPART POUR LE PROCHAIN GAMEDAY")
    for pid in sorted(j0["titulaires"], key=lambda q: joueurs[q]["poste"]):
        p = joueurs[pid]
        cap = "  ← CAPITAINE" if pid == j0["capitaine"] else ""
        P(f"  {'BC' if p['poste']==1 else 'FC'}  {nom(joueurs, pid):<28} proj. {p['proj']:.1f}{cap}")
    if len(j0["titulaires"]) < 5:
        P(f"  (seulement {len(j0['titulaires'])} de tes joueurs jouent ce jour-là)")
    P("")
    P("▶ TRANSFERTS")
    if not plan["transferts"]:
        P("  Aucun transfert recommandé cette semaine (gain attendu trop faible).")
    else:
        for ev, sortants, entrants in plan["transferts"]:
            urgent = " ← MAINTENANT" if ev["id"] == j0["event"]["id"] else ""
            P(f"  Avant la deadline de {ev['name']} ({paris(z(ev['deadline_time']))}){urgent} :")
            for s_, e_ in paires(sortants, entrants, joueurs):
                f = forces.get((ev["id"], s_, e_))
                force = f"  [{f[1]} : +{f[0]:.0f} pts]" if f else ""
                P(f"  - Vendre {nom(joueurs, s_):<26} → Acheter {nom(joueurs, e_)} ({joueurs[e_]['prix']/10:.1f} M$, proj. {joueurs[e_]['proj']:.1f}){force}")
        if plan["hits"]:
            P(f"  ⚠ Inclut {plan['hits']} transfert(s) payant(s) (-100 pts chacun), jugé(s) rentable(s).")
        P(f"  Gain attendu (cette semaine + suivante pondérée) : +{plan['score']-base['score']:.0f} pts vs ne rien faire")
        P("  Relance l'assistant avant chaque deadline : le conseil est recalculé avec les dernières blessures.")
    if plan.get("transferts_suiv"):
        P("  Prévu la semaine suivante (indicatif) : " + " ; ".join(
            f"{ev['name'].split(' - ')[-1]} : " + ", ".join(f"{nom(joueurs, a_, False)}→{nom(joueurs, b_, False)}"
            for a_, b_ in zip(sorted(so, key=lambda q: joueurs[q]["poste"]), sorted(en, key=lambda q: joueurs[q]["poste"])))
            for ev, so, en in plan["transferts_suiv"]))
    P("")
    if suivi and suivi.get("valeurs"):
        P("▶ TES JOUEURS, DU MOINS UTILE AU PLUS UTILE (points attendus ; semaine suivante pondérée × "
          f"{suivi['poids_futur']})")
        for l in suivi["valeurs"]:
            P(f"  {l['nom']:<28} {l['prix']:4.1f} M$ | {l['proj']:4.1f} pts/match, fiabilité {l['fiab']:.2f} | "
              f"cette semaine {l['n1']} m. {l['pts1']:4.0f} pts | suivante {l['n2']} m. {l['pts2']:4.0f} pts | "
              f"{l['par_m']:4.1f} pts/M$")
        P("")
    def ligne_jour(jp):
        e = jp["event"]
        noms = [nom(joueurs, q, False) + (" (C)" if q == jp["capitaine"] else "")
                + (" (B2B)" if (joueurs[q]["equipe_id"], e["id"]) in B2B else "") for q in jp["titulaires"]]
        vides = 5 - len(jp["titulaires"])
        entres = (" ← après " + ", ".join(f"{nom(joueurs, a, False)}→{nom(joueurs, b, False)}"
                                          for a, b in paires(jp["sortants"], jp["entrants"], joueurs))) if jp["entrants"] else ""
        P(f"  {e['name'].split('-')[-1].strip():<6} deadline {paris(z(e['deadline_time']))} : {', '.join(noms) or '—'}"
          f"{f'  ({vides} place(s) vide(s))' if vides else ''}  [~{jp['points']:.0f} pts]{entres}")

    P("▶ PLAN JOUR PAR JOUR (cette Gameweek)")
    for jp in plan["plan"]:
        ligne_jour(jp)
    if plan.get("plan2"):
        vides = sum(5 - len(jp["titulaires"]) for jp in plan["plan2"])
        P("")
        P(f"▶ SEMAINE SUIVANTE, JOUR PAR JOUR (indicatif, avec les transferts prévus) : {vides} place(s) vide(s) au total")
        for jp in plan["plan2"]:
            ligne_jour(jp)
    cap_jour = next((jp for jp in plan["plan"] if jp["capitaine"]), None)
    if cap_jour and cap_jour is not j0:
        f = forces.get("capitaine")
        P(f"  → Garde ton capitaine pour {cap_jour['event']['name']} ({nom(joueurs, cap_jour['capitaine'])})."
          + (f"  [{f[1]} : +{f[0]:.0f} pts]" if f else ""))
    P("")
    P(f"Projection Gameweek (jours restants) : ~{plan['pts_semaine']:.0f} pts  |  sans transfert : ~{base['pts_semaine']:.0f} pts")
    P("Sources : " + ", ".join(f"{k} = {v}" for k, v in sources.items()))
    texte = "\n".join(lignes)

    import rapport_html
    page = rapport_html.rendre(dict(
        joueurs=joueurs, equipe=equipe, plan=plan, base=base, jours=jours, matchs=matchs, joue=joue,
        sources=sources, src_equipe=src_equipe, gw=gw, banque=banque, gratuits=gratuits, cap_dispo=cap_dispo,
        tz=PARIS, sigles={t["id"]: t["short_name"] for t in boot["teams"]}, actuelle=actuelle,
        elements={e["id"]: e for e in boot["elements"]}, equipes_nba={t["id"]: t["code"] for t in boot["teams"]}, b2b=B2B,
        suivi=suivi))
    return texte, page


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Assistant quotidien NBA Fantasy")
    ap.add_argument("--hors-ligne", action="store_true", help="n'utilise que les fichiers de ./donnees")
    ap.add_argument("--pas-de-navigateur", action="store_true", help="n'ouvre pas le rapport HTML")
    ap.add_argument("--maintenant", help="(test) date/heure UTC simulée, ex. 2026-10-20T12:00:00Z")
    args = ap.parse_args()

    cfg = lire_config()
    print("Récupération des données…")
    boot, fixtures, sched, mt, sources = charger(cfg, args.hors_ligne)
    maintenant = z(args.maintenant) if args.maintenant else dt.datetime.now(dt.timezone.utc)
    gw, gw_suiv, jours, saison_commencee = gameweek_courante(boot, maintenant)
    if gw_suiv:
        gw_suiv = dict(gw_suiv, events=[e for e in boot["events"] if gw_suiv["start_event"] <= e["id"] <= gw_suiv["stop_event"]])
    joue, matchs = construire_calendrier(boot, fixtures, sched)
    MALUS_B2B[0] = cfg["malus_back_to_back"]
    saison = minutes_saison(boot, args.hors_ligne) if saison_commencee else {}
    joueurs = projeter(boot, cfg, saison_commencee, saison)
    equipe, banque, prix_vente, gratuits, cap_dispo, src_equipe = mon_equipe(mt, cfg, joueurs, boot, gw)
    premier = min(e["id"] for e in boot["events"])
    construction = jours[0]["id"] == premier
    if construction:
        # Avant la 1re deadline : changements illimités, puis transferts normaux pendant la semaine
        gratuits = cfg["transferts_gratuits_par_defaut"]
        print("Avant la 1re deadline : changements gratuits, une autre équipe de départ est aussi évaluée.")
    print("Optimisation (jusqu'à deux minutes)…")
    actuelle = list(equipe)
    args_plan = (joueurs, equipe, banque, prix_vente, gratuits, cap_dispo, jours, joue, gw_suiv, cfg)
    plan, base = meilleur_plan(*args_plan)
    if construction:
        # Avant la 1re deadline : une autre équipe de départ n'est proposée que si elle rapporte nettement plus
        # que ton équipe actuelle (avec ses transferts) ; sinon on reste sur ton équipe.
        libre = optimiser(*args_plan, transferts=True, libre=True, assurance=base["assurance"])
        # comparaison sur les seuls points projetés (sans la valeur fictive des transferts gardés)
        pts = lambda r: points_projetes(r, cfg)
        if libre and pts(libre) - pts(plan) >= cfg["seuil_nouvelle_equipe"]:
            plan = libre
            budget = max(banque + sum(prix_vente.get(p, joueurs[p]["prix"]) for p in actuelle), 1000)
            equipe = plan["depart"]
            banque = budget - sum(joueurs[p]["prix"] for p in equipe)
        else:
            construction = False
            if libre:
                print(f"  (Une autre équipe de départ ne rapporterait que {pts(libre) - pts(plan):+.0f} pts : on garde la tienne.)")
    plan["assurance"] = base["assurance"]
    # Stabilité : on garde les transferts du calcul précédent si le nouveau plan ne gagne presque rien de plus
    fichier_plan = ICI / "rapport" / "dernier_plan.json"
    try:
        prec = json.loads(fichier_plan.read_text(encoding="utf-8"))
    except Exception:
        prec = None
    stabilite = ""
    if prec and prec.get("gw") == gw["id"] and not construction:
        anciens = [(so, en, ev) for ev, so, en in prec["transferts"]
                   if ev >= jours[0]["id"] and so in equipe and en not in equipe and en in joueurs]
        nouveaux = {(so, en, ev["id"]) for ev, so_l, en_l in plan["transferts"] for so, en in paires(so_l, en_l, joueurs)}
        if anciens and set(anciens) != nouveaux:
            f = optimiser(*args_plan, transferts=True, assurance=base["assurance"], forcer=anciens)
            if f and plan["score"] - f["score"] < cfg["seuil_changement_plan"]:
                stabilite = (f"(Conseil précédent conservé : le nouveau plan ne gagnait que "
                             f"{plan['score'] - f['score']:+.0f} pts.)")
                f["assurance"] = base["assurance"]
                plan = f
    t_force = dt.datetime.now()
    forces = forces_conseils(plan, args_plan, construction, cfg, joueurs, joue)
    try:
        enregistrer_projections(jours[0], joueurs, joue)
    except Exception as ex:
        print(f"  (projections non enregistrées : {ex!r})")
    try:   # classement de ta ligue, tenu à jour par bilan.py
        lg = json.loads((ICI / "rapport" / "ligue.json").read_text(encoding="utf-8"))
        h, d_ = lg["historique"], lg["dernier"]
        avant = h[-2]["rang"] - d_["rang"] if len(h) > 1 else 0
        ligue_txt = (f"Ligue {lg['nom']} : {d_['rang']}e sur {d_['nb']}"
                     + (f" ({'+' if avant > 0 else ''}{avant} depuis le {h[-2]['date'][8:10]}/{h[-2]['date'][5:7]})" if avant else "")
                     + (f", {d_['ecart_devant']:.0f} pts du rang juste devant, {d_['ecart_premier']:.0f} pts du 1er"
                        if d_["rang"] > 1 else ", en tête !"))
    except Exception:
        ligue_txt = ""
    try:
        creux_txt = creux(plan, joueurs, joue, boot, gw_suiv)
    except Exception as ex:
        creux_txt = ""
        print(f"  (jours creux non calculés : {ex!r})")
    try:
        plein_txt = "" if construction else option_plein(plan, args_plan, base, cfg, joueurs)
    except Exception as ex:
        plein_txt = ""
        print(f"  (option « places vides » non calculée : {ex!r})")
    try:
        idees = tester_idees(plan, args_plan, base, cfg, joueurs, boot, saison)
    except Exception as ex:
        idees = []
        print(f"  (idées non testées : {ex!r})")
    try:   # simple éclairage : ne doit jamais faire échouer le calcul
        joker_txt = "" if construction else option_joker(plan, args_plan, base, cfg, joueurs)
    except Exception as ex:
        joker_txt = ""
        print(f"  (option joker non calculée : {ex!r})")
    try:   # simple éclairage : ne doit jamais faire échouer le calcul
        maintenant_txt = "" if construction else option_maintenant(plan, args_plan, base, cfg, joueurs)
    except Exception as ex:
        maintenant_txt = ""
        print(f"  (option « transférer maintenant » non calculée : {ex!r})")
    alertes, a_verifier, note_alertes = alertes_equipe(mt, plan, joueurs, joue)
    suivi = dict(forces=forces, alertes=alertes, a_verifier=a_verifier, note_alertes=note_alertes, stabilite=stabilite,
                 maintenant=maintenant_txt, joker=joker_txt, idees=idees, plein=plein_txt,
                 creux=creux_txt, ligue=ligue_txt, poids_futur=cfg["poids_futur"],
                 valeurs=valeurs_equipe(equipe, joueurs, jours, gw_suiv, joue, cfg),
                 changements=changements(prec, plan, joueurs, boot, gw), source_equipe=src_equipe)
    print(f"  (force des conseils : {(dt.datetime.now() - t_force).seconds} s)")
    texte, page = rapport(joueurs, equipe, banque, gratuits, cap_dispo, gw, jours, joue, matchs, plan, base, sources, src_equipe, boot,
                          actuelle=actuelle if construction else None, suivi=suivi)
    j0 = plan["plan"][0]
    snap = instantane(plan, boot, gw, joueurs)
    snap.update(resume=resume_notif(plan, joueurs, alertes, forces, a_verifier), alertes=alertes, a_verifier=a_verifier,
                source_direct=src_equipe.startswith("my-team (connecté"), changements=suivi["changements"],
                deadline=j0["event"]["deadline_time"], prochaine_nom=j0["event"]["name"])
    fichier_plan.parent.mkdir(exist_ok=True)
    fichier_plan.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    print("\n" + texte)
    sortie = ICI / "rapport.html"
    sortie.write_text(page, encoding="utf-8")
    print(f"\nRapport enregistré : {sortie}")
    if not args.pas_de_navigateur:
        webbrowser.open(sortie.as_uri())


if __name__ == "__main__":
    main()
