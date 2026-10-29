"""Agir sur ton équipe NBA Fantasy à ta place (GitHub Actions, avec le secret NBA_COOKIE).

    python3 agir.py sonde                 # lecture seule : accès au compte, méthodes acceptées par le site
    python3 agir.py test_sauvegarde       # réenregistre ton équipe À L'IDENTIQUE (aucun changement)
    python3 agir.py wildcard              # simulation : affiche ce qui serait envoyé, n'envoie rien
    python3 agir.py wildcard --executer CODE   # exécute, seulement si CODE = code affiché par la simulation

Garde-fous : rien n'est envoyé sans --executer et le bon code ; la wildcard doit être disponible ; les
transferts ne partent JAMAIS sans le chip wildcard ; budget, 10 joueurs, 5 BC / 5 FC et 2 max par équipe
vérifiés avant l'envoi ; équipe relue après l'envoi. Le cookie n'est jamais affiché.
"""
import hashlib, json, os, sys, urllib.error, urllib.request
from pathlib import Path

ICI = Path(__file__).resolve().parent
SITE = "https://nbafantasy.nba.com"
API = SITE + "/api/"


def cookie():
    c = os.environ.get("NBA_COOKIE", "").strip()
    if c.lower().startswith("cookie:"):
        c = c.split(":", 1)[1].strip()
    if not c:
        sys.exit("Pas de cookie (secret NBA_COOKIE) : impossible d'agir sur le compte.")
    return c


def entetes(methode="GET"):
    c = cookie()
    h = {"Cookie": c, "User-Agent": "Mozilla/5.0 (assistant-nba-fantasy perso)", "Accept": "application/json",
         "Referer": SITE + "/my-team", "Origin": SITE}
    csrf = next((p.split("=", 1)[1] for p in c.split("; ") if p.startswith("csrftoken=")), None)
    if csrf and methode != "GET":
        h["X-CSRFToken"] = csrf
    if methode in ("POST", "PUT"):
        h["Content-Type"] = "application/json"
    return h


def appel(methode, chemin, donnees=None):
    corps = json.dumps(donnees).encode() if donnees is not None else None
    req = urllib.request.Request(API + chemin, data=corps, headers=entetes(methode), method=methode)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            brut = r.read()
            return r.status, dict(r.headers), (json.loads(brut) if brut[:1] in (b"{", b"[") else brut[:300].decode(errors="replace"))
    except urllib.error.HTTPError as ex:
        brut = ex.read()[:500].decode(errors="replace")
        return ex.code, dict(ex.headers), brut


def config():
    return json.loads((ICI / "config.json").read_text(encoding="utf-8"))


def sonde():
    eid = config()["id_equipe"]
    code, _, mt = appel("GET", f"my-team/{eid}/")
    print(f"GET my-team : {code}")
    if code == 200:
        print("  joueurs :", [p["element"] for p in mt["picks"]], "| transferts :", mt.get("transfers"))
        print("  chips :", [(c.get("name"), c.get("status_for_entry"), c.get("is_pending")) for c in mt.get("chips", [])])
    code, _, me = appel("GET", "me/")
    print(f"GET me : {code}" + (f" (équipe {me.get('player', {}).get('entry')})" if code == 200 and isinstance(me, dict) else ""))
    for chemin in ("transfers/", f"my-team/{eid}/"):
        code, h, _ = appel("OPTIONS", chemin)
        print(f"OPTIONS {chemin} : {code} | méthodes acceptées : {h.get('Allow') or h.get('allow') or h.get('Access-Control-Allow-Methods') or '?'}")


def equipe_actuelle():
    eid = config()["id_equipe"]
    code, _, mt = appel("GET", f"my-team/{eid}/")
    if code != 200:
        sys.exit(f"Lecture de ton équipe impossible ({code}) : rien n'est envoyé.")
    return eid, mt


def payload_picks(picks):
    return {"chip": None, "picks": [{"element": p["element"], "position": p["position"],
                                     "is_captain": p.get("is_captain", False), "is_vice_captain": p.get("is_vice_captain", False)}
                                    for p in sorted(picks, key=lambda p: p["position"])]}


def test_sauvegarde():
    eid, mt = equipe_actuelle()
    avant = payload_picks(mt["picks"])
    code, _, rep = appel("POST", f"my-team/{eid}/", avant)
    print(f"POST my-team (équipe identique) : {code} | réponse : {str(rep)[:300]}")
    _, mt2 = equipe_actuelle()
    print("Équipe inchangée après l'envoi :", payload_picks(mt2["picks"]) == avant)


def titulaires(ids):
    """Met ces 5 joueurs titulaires (dans cet ordre) ; le banc garde son ordre. Capitaine/vice inchangés."""
    eid, mt = equipe_actuelle()
    boot = json.loads(urllib.request.urlopen(urllib.request.Request(API + "bootstrap-static/", headers=entetes()), timeout=60).read())
    el = {e["id"]: e for e in boot["elements"]}
    picks = sorted(mt["picks"], key=lambda p: p["position"])
    par_id = {p["element"]: p for p in picks}
    nom = lambda q: el[q]["web_name"]
    print("Avant : titulaires", ", ".join(nom(p["element"]) for p in picks[:5]), "| banc", ", ".join(nom(p["element"]) for p in picks[5:]))
    postes = [el[q]["element_type"] for q in ids]
    if len(ids) != 5 or len(set(ids)) != 5 or any(q not in par_id for q in ids) or not (2 <= postes.count(1) <= 3):
        sys.exit("❌ ARRÊT : il faut 5 joueurs différents de ton équipe, avec 2 ou 3 BC (rien n'est envoyé).")
    ids = sorted(ids, key=lambda q: el[q]["element_type"])   # le site veut les BC avant les FC parmi les titulaires
    ordre = list(ids) + [p["element"] for p in picks if p["element"] not in ids]
    # le site exige un capitaine et un vice titulaires : sinon le brassard passe aux premiers titulaires (sans activer de chip)
    cap = next((q for q in ids if par_id[q].get("is_captain")), ids[0])
    vice = next((q for q in ids if par_id[q].get("is_vice_captain") and q != cap), next(q for q in ids if q != cap))
    envoi = {"chip": None, "picks": [{"element": q, "position": k + 1, "is_captain": q == cap, "is_vice_captain": q == vice}
                                     for k, q in enumerate(ordre)]}
    code, _, rep = appel("POST", f"my-team/{eid}/", envoi)
    print(f"POST my-team : {code}" + ("" if code in (200, 201, 202) else f" | réponse : {str(rep)[:400]}"))
    _, mt2 = equipe_actuelle()
    apres = [p["element"] for p in sorted(mt2["picks"], key=lambda p: p["position"])]
    print("Après (relu sur le site) : titulaires", ", ".join(nom(q) for q in apres[:5]), "| banc", ", ".join(nom(q) for q in apres[5:]))
    print("✅ Changement confirmé sur le site" if apres == ordre else "❌ Le site n'a pas pris le changement")


def wildcard(code_execution=None):
    plan = json.loads((ICI / "rapport" / "wildcard_plan.json").read_text(encoding="utf-8"))
    boot = json.loads(urllib.request.urlopen(urllib.request.Request(API + "bootstrap-static/", headers=entetes()), timeout=60).read())
    el = {e["id"]: e for e in boot["elements"]}
    eid, mt = equipe_actuelle()
    actuels = [p["element"] for p in mt["picks"]]
    vente = {p["element"]: p.get("selling_price", el[p["element"]]["now_cost"]) for p in mt["picks"]}
    banque = (mt.get("transfers") or {}).get("bank", 0)
    cible = plan["equipe"]
    sortants = [q for q in actuels if q not in cible]
    entrants = [q for q in cible if q not in actuels]
    # --- garde-fous
    erreurs = []
    wc = next((c for c in mt.get("chips", []) if c.get("name") == "wildcard"), None)
    if not wc or wc.get("status_for_entry") not in ("available", None):
        erreurs.append(f"wildcard non disponible ({wc and wc.get('status_for_entry')})")
    if len(cible) != 10 or len(set(cible)) != 10:
        erreurs.append("l'équipe cible n'a pas 10 joueurs différents")
    postes = [el[q]["element_type"] for q in cible]
    if postes.count(1) != 5 or postes.count(2) != 5:
        erreurs.append("il faut 5 BC et 5 FC")
    equipes = [el[q]["team"] for q in cible]
    if max(equipes.count(t) for t in equipes) > 2:
        erreurs.append("plus de 2 joueurs d'une même équipe NBA")
    budget = banque + sum(vente[q] for q in sortants) - sum(el[q]["now_cost"] for q in entrants)
    if budget < 0:
        erreurs.append(f"budget dépassé de {-budget / 10:.1f} M$")
    if len(sortants) != len(entrants):
        erreurs.append("autant de ventes que d'achats attendus")
    for q in entrants:
        if el[q]["status"] in ("i", "u", "s", "n"):
            erreurs.append(f"{el[q]['web_name']} est indisponible ({el[q]['news']})")
    transferts = {"chip": "wildcard", "entry": eid, "event": plan["event"],
                  "transfers": [{"element_out": o, "selling_price": vente[o], "element_in": i, "purchase_price": el[i]["now_cost"]}
                                for o, i in zip(sorted(sortants, key=lambda q: el[q]["element_type"]),
                                                sorted(entrants, key=lambda q: el[q]["element_type"]))]}
    nom = lambda q: f"{el[q]['web_name']} ({el[q]['now_cost'] / 10:.1f} M$)"
    print(f"Wildcard pour le Gameday {plan['event']} ({plan.get('nom', '')}), calculée le {plan.get('calcul', '?')}")
    for t in transferts["transfers"]:
        print(f"  vendre {nom(t['element_out'])} (revente {t['selling_price'] / 10:.1f}) → acheter {nom(t['element_in'])}")
    print(f"  banque après : {budget / 10:.1f} M$ | titulaires du soir : {', '.join(el[q]['web_name'] for q in plan['titulaires'])}")
    code_attendu = hashlib.sha1(json.dumps(transferts, sort_keys=True).encode()).hexdigest()[:6]
    if erreurs:
        print("❌ ARRÊT, rien n'est envoyé : " + " ; ".join(erreurs))
        sys.exit(1)
    if code_execution != code_attendu:
        print(f"SIMULATION : rien n'est envoyé. Code d'exécution pour ces transferts exacts : {code_attendu}")
        return
    # En deux temps : 1 transfert avec la wildcard, vérification qu'elle est active (transferts gratuits), puis le reste.
    def wildcard_active():
        _, m = equipe_actuelle()
        c = next((c for c in m.get("chips", []) if c.get("name") == "wildcard"), {})
        t = m.get("transfers") or {}
        print(f"  état du site : wildcard {c.get('status_for_entry')} (en attente : {c.get('is_pending')}) | transferts {t}")
        return bool(c.get("is_pending") or c.get("status_for_entry") in ("active", "played") or t.get("status") == "unlimited")
    premier = dict(transferts, transfers=transferts["transfers"][:1])
    code, _, rep = appel("POST", "transfers/", premier)
    print(f"POST 1er transfert + wildcard : {code}" + ("" if code in (200, 201, 202) else f" | réponse : {str(rep)[:400]}"))
    if code not in (200, 201, 202):
        print("❌ Le site a refusé : rien n'est envoyé. Ton équipe est inchangée.")
        sys.exit(1)
    if not wildcard_active():
        print("❌ ARRÊT : la wildcard n'apparaît pas active après le 1er transfert. Rien d'autre n'est envoyé. "
              "Active la wildcard sur le site AVANT la deadline : elle rend gratuits les transferts de la journée.")
        sys.exit(1)
    print("✅ Wildcard active : transferts gratuits")
    reste = dict(transferts, transfers=transferts["transfers"][1:])
    code, _, rep = appel("POST", "transfers/", reste)
    if code not in (200, 201, 202):   # la wildcard est déjà active : renvoi sans le chip
        print(f"  (avec le chip : {code} {str(rep)[:200]}) → renvoi sans le chip")
        code, _, rep = appel("POST", "transfers/", dict(reste, chip=None))
    print(f"POST 5 autres transferts : {code}" + ("" if code in (200, 201, 202) else f" | réponse : {str(rep)[:400]}"))
    wildcard_active()
    if code not in (200, 201, 202):
        print("❌ Les transferts restants ont été refusés : la wildcard est active, ils restent gratuits ; à faire sur le site.")
        sys.exit(1)
    _, mt2 = equipe_actuelle()
    nouveaux = [p["element"] for p in mt2["picks"]]
    print("Équipe sur le site = équipe cible :", sorted(nouveaux) == sorted(cible))
    # titulaires du soir, banc dans l'ordre conseillé
    tit = sorted((q for q in plan["titulaires"] if q in nouveaux), key=lambda q: el[q]["element_type"])
    banc = [q for q in plan.get("banc", []) if q in nouveaux] + [q for q in nouveaux if q not in tit and q not in plan.get("banc", [])]
    # le site garde toujours un capitaine/vice dans l'équipe (le chip capitaine, lui, n'est pas activé : chip = null)
    picks = [{"element": q, "position": k + 1, "is_captain": k == 0, "is_vice_captain": k == 1} for k, q in enumerate(tit + banc)]
    code, _, rep = appel("POST", f"my-team/{eid}/", {"chip": None, "picks": picks})
    print(f"POST titulaires : {code} | réponse : {str(rep)[:300]}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "sonde"
    if mode == "sonde":
        sonde()
    elif mode == "test_sauvegarde":
        test_sauvegarde()
    elif mode == "titulaires":
        titulaires([int(x) for x in sys.argv[2].split(",")])
    elif mode == "wildcard":
        wildcard(sys.argv[3] if len(sys.argv) > 3 and sys.argv[2] == "--executer" else None)
    else:
        sys.exit(f"mode inconnu : {mode}")
