"""Planificateur : lancé toutes les 10 min (launchd ou GitHub Actions), il décide s'il faut calculer.

    python3 planificateur.py                          # décision réelle (et calcul si besoin)
    python3 planificateur.py --simuler                # montre les décisions pour les 3 prochaines deadlines
    python3 planificateur.py --maintenant 2026-10-21T21:00:00Z --simuler

Règles (pour la prochaine deadline) :
  - entre 100 et 70 min avant (cloud : 150 et 60) : calcul complet (une fois) → notification « à faire ».
    Un passage en retard le rattrape tant qu'il reste au moins 15 min (cloud : 8 min).
  - entre 30 et 15 min avant (cloud : 50 et 15) : calcul de contrôle (une fois, au moins 20 min après
    le complet) → notification seulement si le conseil a changé, ou en priorité haute si ton équipe
    sur le site n'est pas en ordre
  - plus tard sans calcul fait : on saute, avec une ligne au journal
  - calcul de secours vers 12h s'il n'y en a pas eu depuis 12 h
lancer_assistant.sh garde le verrou : jamais deux calculs en même temps.
"""
import argparse, datetime as dt, json, os, subprocess, sys, urllib.request
from pathlib import Path

ICI = Path(__file__).resolve().parent
RAPPORT = ICI / "rapport"
ETAT = RAPPORT / "planif.json"
NOTIFS = RAPPORT / "notifs.json"
JOURNAL = RAPPORT / "planificateur.log"
ADRESSE = os.environ.get("ADRESSE_PAGE", "https://hugos-macbook-pro.tail81f2b6.ts.net")
NUAGE = os.environ.get("NUAGE") == "1"   # GitHub Actions : lancements moins ponctuels → fenêtres plus larges
FENETRE_COMPLET = (60, 150) if NUAGE else (70, 100)    # minutes avant la deadline
FENETRE_CONTROLE = (15, 50) if NUAGE else (15, 30)
TROP_TARD = 8 if NUAGE else 15   # en dessous, un calcul n'arriverait plus à temps
ECART_CONTROLE = 20              # minutes minimum entre le calcul complet et le contrôle


def z(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def lire(chemin, defaut):
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except Exception:
        return defaut


def ecrire(chemin, donnees):
    RAPPORT.mkdir(exist_ok=True)
    chemin.write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")


def log(msg, maintenant):
    RAPPORT.mkdir(exist_ok=True)
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(f"{maintenant.astimezone():%Y-%m-%d %H:%M} {msg}\n")
    print(msg)


def deadlines(maintenant):
    """Deadlines à venir (bootstrap retéléchargé s'il a plus de 12 h)."""
    chemin = ICI / "donnees" / "bootstrap.json"
    age = dt.datetime.now().timestamp() - chemin.stat().st_mtime if chemin.exists() else 1e9
    if age > 12 * 3600:
        try:
            req = urllib.request.Request("https://nbafantasy.nba.com/api/bootstrap-static/",
                                         headers={"User-Agent": "Mozilla/5.0 (assistant-nba-fantasy perso)"})
            with urllib.request.urlopen(req, timeout=60) as r:
                chemin.write_bytes(r.read())
        except Exception as ex:
            log(f"bootstrap non mis à jour ({ex.__class__.__name__}) : ancien fichier utilisé", maintenant)
    boot = json.loads(chemin.read_text(encoding="utf-8"))
    evs = sorted(boot["events"], key=lambda e: z(e["deadline_time"]))
    return [e for e in evs if z(e["deadline_time"]) > maintenant]


def decider(maintenant, etat, prochaines):
    """Renvoie (action, event, minutes) avec action dans complet / controle / saute / secours / rien."""
    if prochaines:
        e = prochaines[0]
        m = (z(e["deadline_time"]) - maintenant).total_seconds() / 60
        cle = str(e["id"])
        # Rattrapage : un passage en retard (Mac réveillé tard, GitHub qui saute des passages)
        # fait quand même le calcul complet, tant qu'il reste le temps d'agir.
        if TROP_TARD <= m <= FENETRE_COMPLET[1] and cle not in etat["complet"]:
            return "complet", e, m
        fait = etat["complet"].get(cle)
        if (FENETRE_CONTROLE[0] <= m <= FENETRE_CONTROLE[1] and cle not in etat["controle"]
                and fait and maintenant - z(fait) >= dt.timedelta(minutes=ECART_CONTROLE)):
            return "controle", e, m
        if 0 < m < TROP_TARD and cle not in etat["complet"] and cle not in etat["controle"] and cle not in etat["sautes"]:
            return "saute", e, m
    dernier = z(etat["dernier_calcul"]) if etat.get("dernier_calcul") else None
    local = maintenant.astimezone()
    if (local.hour >= 12 and etat.get("secours") != local.date().isoformat()
            and (dernier is None or maintenant - dernier > dt.timedelta(hours=12))):
        return "secours", None, None
    return "rien", None, None


def notifier(cfg, titre, message, priorite="default", tags="basketball"):
    """Notification ntfy (sujet secret de config.json). Un échec ne bloque jamais le calcul."""
    sujet = os.environ.get("NTFY_SUJET") or cfg.get("ntfy_sujet")
    if not sujet:
        return "pas de sujet ntfy configuré"
    corps = json.dumps({"topic": sujet, "title": titre, "message": message, "priority": {"default": 3, "high": 4, "max": 5}[priorite],
                        "tags": tags.split(","), "click": ADRESSE}).encode()
    try:
        req = urllib.request.Request("https://ntfy.sh/", data=corps, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return f"notification envoyée ({r.status})"
    except Exception as ex:
        return f"échec de la notification ({ex.__class__.__name__})"


def calculer():
    subprocess.run(["/bin/bash", str(ICI / "lancer_assistant.sh")])


def apres_calcul(action, e, m, cfg, maintenant):
    """Choisit la notification à envoyer, sans jamais envoyer deux fois la même."""
    plan = lire(RAPPORT / "dernier_plan.json", {})
    if not plan or not e or str(plan.get("prochaine")) != str(e["id"]):
        return "pas de plan pour cette deadline : pas de notification"
    notifs = lire(NOTIFS, {})
    deja = notifs.setdefault(str(e["id"]), {})
    heure = z(e["deadline_time"]).astimezone().strftime("%Hh%M")
    resume, alertes = plan.get("resume", ""), plan.get("alertes", [])
    direct = plan.get("source_direct", False)   # priorité haute seulement si l'équipe est lue en direct (cookie)
    titre, prio, tags = None, "default", "basketball"
    if action == "complet" and "a" not in deja:
        titre = f"{e['name'].split(' - ')[-1]} : à faire avant {heure}"
        if alertes and direct:
            prio, tags = "high", "warning"
    elif action == "controle":
        if alertes and direct and m is not None and m < 30 and deja.get("c") != alertes:
            titre, prio, tags = f"⚠️ Équipe pas en ordre ! Deadline {heure}", "high", "warning"
            deja["c"] = alertes
        elif deja.get("resume") and deja["resume"] != resume:
            titre, tags = f"🔄 Nouveau conseil avant {heure}", "arrows_counterclockwise"
            if plan.get("changements"):
                resume = plan["changements"] + "\n" + resume
    if not titre or deja.get("resume_envoye") == resume:
        return "rien de nouveau : pas de notification"
    res = notifier(cfg, titre, resume, prio, tags)
    if res.startswith("notification envoyée"):
        deja.update(resume=plan.get("resume", ""), resume_envoye=resume)
        if action == "complet":
            deja["a"] = maintenant.isoformat()
        ecrire(NOTIFS, notifs)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--maintenant", help="(test) heure UTC simulée, ex. 2026-10-21T21:00:00Z")
    ap.add_argument("--simuler", action="store_true", help="montre les décisions sans rien lancer")
    ap.add_argument("--test-notif", action="store_true", help="envoie une notification de test")
    ap.add_argument("--forcer", action="store_true", help="calcule tout de suite (bouton « Recalculer »)")
    args = ap.parse_args()
    maintenant = z(args.maintenant) if args.maintenant else dt.datetime.now(dt.timezone.utc)
    cfg = {**lire(ICI / "config.json", {}), **lire(ICI / "config_local.json", {})}
    if args.test_notif:
        print(notifier(cfg, "Test NBA Fantasy", "Les notifications de ton assistant fonctionnent 🏀"))
        return
    etat = lire(ETAT, {})
    for k in ("complet", "controle", "sautes"):
        etat.setdefault(k, {})
    prochaines = deadlines(maintenant)

    if args.simuler:
        vide = {"complet": {}, "controle": {}, "sautes": {}, "dernier_calcul": maintenant.isoformat(), "secours": None}
        for e in prochaines[:3]:
            dl = z(e["deadline_time"])
            print(f"{e['name']} — deadline {dl.astimezone():%a %d/%m %H:%M}")
            for avant in (110, 100, 90, 80, 70, 60, 30, 20, 10):
                t = dl - dt.timedelta(minutes=avant)
                if t < maintenant:
                    continue
                act, ev, m = decider(t, vide, [x for x in prochaines if z(x["deadline_time"]) > t])
                if act in ("complet", "controle", "saute"):
                    vide[{"complet": "complet", "controle": "controle", "saute": "sautes"}[act]][str(ev["id"])] = t.isoformat()
                if act in ("complet", "controle", "secours"):
                    vide["dernier_calcul"] = t.isoformat()
                if act == "secours":
                    vide["secours"] = t.astimezone().date().isoformat()
                print(f"   {t.astimezone():%H:%M} (J-{avant:>3} min) → {act}")
        return

    action, e, m = ("manuel", None, None) if args.forcer else decider(maintenant, etat, prochaines)
    if action == "rien":
        return
    if action == "saute":
        etat["sautes"][str(e["id"])] = maintenant.isoformat()
        ecrire(ETAT, etat)
        log(f"{e['name']} : deadline dans {m:.0f} min, trop tard pour un calcul utile → sauté", maintenant)
        return
    log(f"calcul {action}" + (f" pour {e['name']} (deadline dans {m:.0f} min)" if e else ""), maintenant)
    calculer()
    etat["dernier_calcul"] = dt.datetime.now(dt.timezone.utc).isoformat()
    if action == "secours":
        etat["secours"] = maintenant.astimezone().date().isoformat()
    elif action != "manuel":
        etat[action][str(e["id"])] = maintenant.isoformat()
    ecrire(ETAT, etat)
    if e:
        log("  " + apres_calcul(action, e, m, cfg, maintenant), maintenant)


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:   # le planificateur ne doit jamais rester bloqué : on note et on attend le prochain passage
        log(f"erreur du planificateur : {ex!r}", dt.datetime.now(dt.timezone.utc))
        sys.exit(0)
