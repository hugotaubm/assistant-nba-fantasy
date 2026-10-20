"""Rendu HTML du rapport quotidien : le cinq du soir sur un demi-terrain, les transferts,
et une grille joueurs × jours pour la fin de la Gameweek."""
import datetime as dt
import html
import json

TAG_AJOUT = '<em class="tag entre">à ajouter</em>'
# statut du jeu → (sigle affiché, classe CSS)
STATUTS = {"a": ("AV", "s-ok"), "d": ("DTD", "s-doute"), "i": ("BLES", "s-out"), "s": ("SUSP", "s-out"),
           "u": ("INDISP", "s-out"), "n": ("INDISP", "s-out")}
JOURS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]


def _z(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def _e(s):
    return html.escape(str(s))


def _paris(t, tz):
    t = t.astimezone(tz)
    return f"{JOURS[t.weekday()]} {t.day:02d}/{t.month:02d} à {t.hour}h{t.minute:02d}"


def _news(txt):
    """Traduit les messages de blessure les plus courants."""
    import re
    if not txt:
        return txt
    m = re.search(r"expected back (\d{4})-(\d{2})-(\d{2})", txt)
    if m:
        debut = txt[:m.start()].strip().rstrip("-:,").strip()
        debut = "" if debut.lower() in ("back", "") else debut + ", "
        return f"{debut}retour prévu le {m.group(3)}/{m.group(2)}"
    return txt


def _m(x):
    return f"{x:.1f}".replace(".", ",")


def _court(titulaires, capitaine, joueurs, adversaire):
    """Demi-terrain SVG, panier en bas. BC sur le périmètre, FC près du cercle."""
    bc = [p for p in titulaires if joueurs[p]["poste"] == 1]
    fc = [p for p in titulaires if joueurs[p]["poste"] == 2]
    spots_bc = {1: [(250, 120)], 2: [(165, 135), (335, 135)], 3: [(250, 95), (105, 175), (395, 175)]}
    spots_fc = {1: [(250, 330)], 2: [(150, 335), (350, 335)], 3: [(250, 270), (95, 365), (405, 365)]}
    places = list(zip(bc, spots_bc.get(len(bc), []))) + list(zip(fc, spots_fc.get(len(fc), [])))
    jetons = []
    for pid, (x, y) in places:
        p = joueurs[pid]
        cap = pid == capitaine
        badge = (f'<circle cx="{x+24}" cy="{y-24}" r="13" class="cap-badge"/>'
                 f'<text x="{x+24}" y="{y-19.5}" class="cap-txt">C</text>') if cap else ""
        nom = p["nom"].split(".", 1)[-1] if "." in p["nom"] else p["nom"]
        jetons.append(f'''
      <g class="jeton{' capitaine' if cap else ''}" tabindex="0">
        <title>{_e(p['nom_complet'])} ({_e(p['equipe'])}) : {p['proj']:.1f} pts projetés{' ×2 capitaine' if cap else ''}</title>
        <circle cx="{x}" cy="{y}" r="30" class="maillot"/>
        <text x="{x}" y="{y+7}" class="pts">{p['proj']*(2 if cap else 1):.0f}</text>
        {badge}
        <text x="{x}" y="{y+54}" class="nom">{_e(nom)}</text>
        <text x="{x}" y="{y+73}" class="adv">{_e(adversaire.get(pid, ''))}</text>
      </g>''')
    return f'''
    <svg class="terrain" viewBox="0 0 500 470" role="img" aria-label="Cinq de départ placé sur un demi-terrain">
      <rect x="4" y="4" width="492" height="462" rx="6" class="parquet"/>
      <g class="lignes">
        <rect x="4" y="4" width="492" height="462" rx="6" fill="none"/>
        <path d="M34 466 V362 A216 216 0 0 1 466 362 V466"/>
        <rect x="190" y="276" width="120" height="190" fill="none"/>
        <path d="M190 276 A60 60 0 0 1 310 276"/>
        <path d="M190 276 A60 60 0 0 0 310 276" stroke-dasharray="8 7"/>
        <circle cx="250" cy="426" r="11" fill="none"/>
        <line x1="222" y1="444" x2="278" y2="444"/>
        <path d="M190 4 A60 60 0 0 0 310 4"/>
      </g>
      {''.join(jetons)}
    </svg>'''


def rendre(ctx):
    j = ctx["joueurs"]
    tz = ctx["tz"]
    plan = ctx["plan"]
    base = ctx["base"]
    jours = ctx["jours"]
    j0 = plan["plan"][0]
    dl0 = _z(j0["event"]["deadline_time"])
    matchs = ctx["matchs"]
    equipe = ctx["equipe"]
    ce_soir = bool(j0.get("entrants"))   # transferts à faire avant la deadline de ce soir

    # adversaire de chaque équipe pour chaque Gameday
    adv = {}
    for ev, t, h, a in matchs:
        adv[(h, ev)] = (ctx["sigles"].get(a, "?"), True, t)
        adv[(a, ev)] = (ctx["sigles"].get(h, "?"), False, t)

    def match_txt(pid, ev):
        m = adv.get((j[pid]["equipe_id"], ev))
        if not m:
            return ""
        o, dom, t = m
        h = f" {t.astimezone(tz).hour}h{t.astimezone(tz).minute:02d}" if t else ""
        return f"{'vs' if dom else '@'} {o}{h}"

    adversaire_soir = {pid: match_txt(pid, j0["event"]["id"]) for pid in j0["titulaires"]}
    num_jour = lambda e: e["name"].split("Day")[-1].strip() if "Day" in e["name"] else e["name"]

    # --- en-tête
    nb_tit = len(j0["titulaires"])
    if ctx.get("actuelle") is not None:
        titre = "Crée ton équipe, puis aligne ces cinq."
    elif ce_soir:
        titre = "Fais tes transferts, puis aligne ces cinq."
    else:
        titre = "Ce soir, aligne ces cinq." if nb_tit == 5 else f"Ce soir, seulement {nb_tit} de tes joueurs jouent."
    sous_titre = f"{_e(ctx['gw']['name'])}, jour {_e(num_jour(j0['event']))} sur {_e(num_jour(jours[-1]))}"

    # --- banc du soir
    effectif_soir = j0.get("effectif", equipe)
    banc = []
    for pid in sorted(effectif_soir, key=lambda q: (j[q]["poste"], -j[q]["proj"])):
        if pid in j0["titulaires"]:
            continue
        p = j[pid]
        joue_ce_soir = j0["event"]["id"] in ctx["joue"].get(p["equipe_id"], ())
        if not joue_ce_soir:
            raison = "ne joue pas ce soir"
        elif p["dispo"] == 0 or p["news"]:
            raison = _news(p["news"]) or "indisponible"
        else:
            raison = "projeté plus bas que les titulaires"
        banc.append(f'<li><span class="poste">{"BC" if p["poste"]==1 else "FC"}</span>'
                    f'<span class="qui">{_e(p["nom"])} <small>{_e(p["equipe"])}</small></span>'
                    f'<span class="pourquoi">{_e(raison)}</span></li>')

    # --- capitaine
    cap_jour = next((jp for jp in plan["plan"] if jp["capitaine"]), None)
    if not ctx["cap_dispo"]:
        cap_html = "<p>Capitaine déjà utilisé cette semaine.</p>"
    elif cap_jour is None:
        cap_html = "<p>Aucun jour ne justifie le capitaine pour l’instant.</p>"
    elif cap_jour is j0:
        cap_html = (f"<p><strong>Active-le ce soir sur {_e(j[cap_jour['capitaine']]['nom'])}.</strong> "
                    f"C’est le meilleur coup de la semaine (environ {j[cap_jour['capitaine']]['proj']:.0f} pts doublés).</p>")
    else:
        e = cap_jour["event"]
        cap_html = (f"<p><strong>Garde-le pour le jour {_e(num_jour(e))}</strong> ({_e(_paris(_z(e['deadline_time']), tz))}) "
                    f"sur {_e(j[cap_jour['capitaine']]['nom'])}, {_e(match_txt(cap_jour['capitaine'], e['id']))}.</p>")

    # --- transferts : chacun avec le jour où le faire
    if not plan["transferts"]:
        tr_html = (f'<p class="calme">Aucun transfert ne rapporte assez cette semaine. '
                   f'Tu gardes tes {ctx["gratuits"]} transferts pour une blessure éventuelle.</p>')
        tr_classe = "calme"
    else:
        blocs = []
        for ev, sortants, entrants in plan["transferts"]:
            quand = ("Avant la deadline de ce soir" if ev["id"] == j0["event"]["id"] else
                     f"Avant le jour {num_jour(ev)}, {_paris(_z(ev['deadline_time']), tz)}")
            lignes = []
            for s, e in zip(sorted(sortants, key=lambda q: j[q]["poste"]), sorted(entrants, key=lambda q: j[q]["poste"])):
                lignes.append(f'''
          <li>
            <div class="vend"><span>Vendre</span><b>{_e(j[s]['nom'])}</b><small>{_e(j[s]['equipe'])}, {_m(j[s]['prix']/10)} M$</small></div>
            <svg class="fleche" viewBox="0 0 40 16" aria-hidden="true"><path d="M2 8h32M28 2l7 6-7 6"/></svg>
            <div class="achete"><span>Acheter</span><b>{_e(j[e]['nom'])}</b><small>{_e(j[e]['equipe'])}, {_m(j[e]['prix']/10)} M$, {j[e]['proj']:.0f} pts/match</small></div>
          </li>''')
            blocs.append(f'<p class="quand"><strong>{_e(quand)}</strong></p><ul class="echanges">{"".join(lignes)}</ul>')
        hit = f'<p class="note alerte-txt">Inclut {plan["hits"]} transfert payant (−100 pts), rentable d’après le calcul.</p>' if plan["hits"] else ""
        suiv = ""
        if plan.get("transferts_suiv"):
            suiv = ('<p class="note">Prévu la semaine suivante (indicatif) : ' + _e(" ; ".join(
                f"jour {num_jour(ev)} : " + ", ".join(f"{j[a]['nom']} → {j[b]['nom']}" for a, b in
                zip(sorted(so, key=lambda q: j[q]["poste"]), sorted(en, key=lambda q: j[q]["poste"])))
                for ev, so, en in plan["transferts_suiv"])) + '.</p>')
        tr_html = (f'<p class="quand">Gain attendu <strong>+{plan["score"]-base["score"]:.0f} pts</strong> '
                   f'(cette semaine + la suivante pondérée) par rapport à ne rien faire.</p>'
                   + "".join(blocs) + hit + suiv +
                   '<p class="note">Relance l’assistant avant chaque deadline : le conseil est recalculé avec les dernières blessures.</p>')
        tr_classe = "urgent" if ce_soir else "prevu"

    # --- alertes
    alertes = [pid for pid in equipe if j[pid]["dispo"] < 1 or j[pid]["news"]]
    alertes_html = ""
    if alertes:
        items = "".join(f'<li><b>{_e(j[p]["nom"])}</b> ({_e(j[p]["equipe"])}) : {_e(_news(j[p]["news"]) or "statut " + j[p]["statut"])}, '
                        f'{int(j[p]["dispo"]*100)} % de chances de jouer</li>' for p in alertes)
        alertes_html = f'<section class="alertes" aria-label="Blessures et incertitudes"><h2>À surveiller</h2><ul>{items}</ul></section>'

    # --- effectif × jours (Front Court / Back Court, adversaire de chaque jour)
    elements, equipes_nba = ctx["elements"], ctx["equipes_nba"]
    logo = lambda eid: f"https://cdn.nba.com/logos/nba/{equipes_nba.get(eid, '')}/global/L/logo.svg"
    tous = list(dict.fromkeys(list(equipe) + [q for jp in plan["plan"] + (plan.get("plan2") or []) for q in jp["effectif"]]))
    plan2 = plan.get("plan2") or []
    jour_sem = lambda e: JOURS[(_z(e["deadline_time"]) - dt.timedelta(hours=4)).weekday()]
    entetes = "".join(
        f'<th scope="col" class="jour{" auj" if i == 0 else ""}">J{_e(num_jour(e))}<small>{_e(jour_sem(e))}</small></th>'
        for i, e in enumerate(jours))
    entetes += "".join(
        f'<th scope="col" class="jour suiv{" sep" if i == 0 else ""}" title="Semaine suivante (avant ses transferts)">'
        f'J{_e(num_jour(jp["event"]))}<small>{_e(jour_sem(jp["event"]))} · {_e(jp["event"]["name"].split(" - ")[0].replace("Gameweek ", "GW"))}</small></th>'
        for i, jp in enumerate(plan2))

    def cellule(pid, jp, dans_effectif, classe=""):
        ev = jp["event"]["id"]
        m = adv.get((j[pid]["equipe_id"], ev))
        if not dans_effectif:
            return f'<td class="hors {classe}" title="Pas dans ton équipe ce jour-là"></td>'
        if not m:
            return f'<td class="repos {classe}" title="Pas de match"><span class="tiret"></span></td>'
        adv_id = next((t for t, s in ctx["sigles"].items() if s == m[0]), None)
        if pid == jp["capitaine"]:
            role, quoi = "cap", "Titulaire et capitaine"
        elif pid in jp["titulaires"]:
            role, quoi = "tit", "Titulaire"
        else:
            role, quoi = "banc", "Sur le banc"
        b2b = (j[pid]["equipe_id"], ev) in ctx.get("b2b", ())
        quoi += " (2e soir d’affilée, B2B)" if b2b else ""
        return (f'<td class="m {role} {classe}" title="{quoi} : {_e(match_txt(pid, ev))}">'
                f'<span class="adv-logo"><img src="{logo(adv_id)}" alt="{_e(m[0])}" '
                f'onerror="this.replaceWith(document.createTextNode(this.alt))"></span>'
                f'<small>{"vs" if m[1] else "@"}{" · B2B" if b2b else ""}</small><i class="role">{"C" if role == "cap" else ""}</i></td>')

    def ligne(pid):
        p, el = j[pid], elements[pid]
        etat = "sort" if pid in plan["sortants"] else "entre" if pid not in equipe else ""
        cellules = [cellule(pid, jp, pid in jp["effectif"]) for jp in plan["plan"]]
        cellules += [cellule(pid, jp, pid in jp["effectif"], "suiv" + (" sep" if i == 0 else ""))
                     for i, jp in enumerate(plan2)]
        marque = {"sort": '<em class="tag sort">vendu</em>', "entre": '<em class="tag entre">acheté</em>'}.get(etat, "")
        st = STATUTS.get(p["statut"], (p["statut"].upper(), "s-autre"))
        val = p["proj"] / (p["prix"] / 10) if p["prix"] else 0
        return (f'<tr class="{etat}"><th scope="row"><div class="joueur">'
                f'<img class="tete" src="https://cdn.nba.com/headshots/nba/latest/260x190/{el["code"]}.png" alt="" onerror="this.style.visibility=\'hidden\'">'
                f'<div><span class="prenom">{_e(el["first_name"])}</span><span class="nomf">{_e(el["second_name"])}</span>'
                f'<span class="eq">{_e(p["equipe"])} <em class="statut {st[1]}">{st[0]}</em>{marque}</span></div></div></th>'
                f'<td class="num">{_m(p["prix"]/10)}</td><td class="num fort">{p["proj"]:.1f}</td>'
                f'<td class="num">{val:.1f}</td><td class="num">{el["total_points"]/10:.0f}</td>{"".join(cellules)}</tr>')

    def tableau(poste, titre, pied=""):
        ids = sorted((q for q in tous if j[q]["poste"] == poste), key=lambda q: (q not in equipe, -j[q]["proj"]))
        return f'''
    <div class="defile">
      <table class="effectif-t {"fc" if poste == 2 else "bc"}">
        <thead><tr><th scope="col" class="titre-t">{titre}</th>
          <th scope="col" title="Prix (M$)">$</th><th scope="col" title="Points fantasy projetés par match">PROJ</th>
          <th scope="col" title="Points projetés par M$">VAL</th><th scope="col" title="Total de points la saison passée">TP</th>{entetes}</tr></thead>
        <tbody>{"".join(ligne(q) for q in ids)}</tbody>{pied}
      </table>
    </div>'''
    pts_jours = "".join(f'<td class="pts-j">{jp["points"]:.0f}</td>' for jp in plan["plan"])
    pts_jours += "".join(f'<td class="pts-j suiv{" sep" if i == 0 else ""}">{jp["points"]:.0f}</td>' for i, jp in enumerate(plan2))
    titre_suiv = (f'<p class="note suiv">Les colonnes grisées à droite sont la semaine suivante, avec ton équipe après les transferts '
                  f'de cette semaine : ~{sum(jp["points"] for jp in plan2):.0f} pts projetés, avant ses propres transferts.</p>'
                  if plan2 else "")
    pied = f'<tfoot><tr><th scope="row">Points projetés de l’équipe</th><td colspan="4"></td>{pts_jours}</tr></tfoot>'
    tableaux = tableau(2, "Front Court") + tableau(1, "Back Court", pied)

    # --- construction de l'équipe (avant la 1re deadline)
    constr_html = ""
    act = ctx.get("actuelle")
    if act is not None:
        cartes = []
        for pid in sorted(equipe, key=lambda q: (j[q]["poste"], -j[q]["prix"])):
            p = j[pid]
            neuf = pid not in act
            cartes.append(f'<li class="{"neuf" if neuf else ""}"><span class="poste">{"BC" if p["poste"]==1 else "FC"}</span>'
                          f'<b>{_e(p["nom"])}</b><small>{_e(p["equipe"])}, {_m(p["prix"]/10)} M$, {p["proj"]:.0f} pts/match</small>'
                          f'{TAG_AJOUT if neuf else ""}</li>')
        retires = [q for q in act if q not in equipe]
        ret = (f'<p class="note">À retirer de ton équipe actuelle : {_e(", ".join(j[q]["nom"] for q in retires))}.</p>'
               if retires else '<p class="note">Ton équipe actuelle est déjà la bonne.</p>')
        constr_html = f'''
  <section class="construction">
    <h2>Ton équipe de départ</h2>
    <p>Avant la première deadline, les changements sont gratuits et illimités. Voici la meilleure équipe pour démarrer
    ({_m(sum(j[q]["prix"] for q in equipe)/10)} M$ sur 100).</p>
    <ul class="effectif">{"".join(cartes)}</ul>
    {ret}
  </section>'''

    # --- encadré « À faire avant la prochaine deadline » (tout en haut)
    suivi = ctx.get("suivi") or {}
    forces = suivi.get("forces", {})
    pastille = lambda f: f' <span class="force">{_e(f[1])} +{f[0]:.0f}</span>' if f else ""
    paires = lambda so, en: list(zip(sorted(so, key=lambda q: j[q]["poste"]), sorted(en, key=lambda q: j[q]["poste"])))
    tit_items = []
    for q in sorted(j0["titulaires"], key=lambda q: (j[q]["poste"], -j[q]["proj"])):
        b2b = (j[q]["equipe_id"], j0["event"]["id"]) in ctx.get("b2b", ())
        tit_items.append(f'<li><b>{_e(j[q]["nom"])}</b> <small>{_e(match_txt(q, j0["event"]["id"]))}'
                         f'{" · B2B" if b2b else ""}</small></li>')
    if len(j0["titulaires"]) < 5:
        tit_items.append(f'<li class="vide">{5 - len(j0["titulaires"])} place(s) vide(s) : pas d’autre joueur qui joue</li>')
    tr_soir = [f'{_e(j[a]["nom"])} → <b>{_e(j[b]["nom"])}</b>{pastille(forces.get((j0["event"]["id"], a, b)))}'
               for a, b in paires(j0.get("sortants", []), j0.get("entrants", []))]
    cap_jour = next((jp for jp in plan["plan"] if jp["capitaine"]), None)
    if not ctx["cap_dispo"]:
        cap_txt = "déjà utilisé cette semaine"
    elif cap_jour is j0:
        cap_txt = f'<b>Activer sur {_e(j[j0["capitaine"]]["nom"])}</b>{pastille(forces.get("capitaine"))}'
    elif cap_jour:
        cap_txt = (f'Non, garder pour le jour {_e(num_jour(cap_jour["event"]))} '
                   f'({_e(j[cap_jour["capitaine"]]["nom"])}){pastille(forces.get("capitaine"))}')
    else:
        cap_txt = "Non"
    plus_tard = [(ev, a, b) for ev, so, en in plan["transferts"] if ev["id"] != j0["event"]["id"] for a, b in paires(so, en)]
    prochain = ""
    if plus_tard:
        par_jour = {}
        for ev, a, b in plus_tard:
            par_jour.setdefault(ev["id"], (ev, []))[1].append(f'{_e(j[a]["nom"])} → {_e(j[b]["nom"])}{pastille(forces.get((ev["id"], a, b)))}')
        prochain = "".join(f'<p class="discret">Transfert(s) prévu(s) avant le jour {_e(num_jour(ev))} '
                           f'({_e(_paris(_z(ev["deadline_time"]), tz))}) : {" ; ".join(l)}</p>' for ev, l in par_jour.values())
    al_html = "".join(f'<li>⚠️ {_e(a)}</li>' for a in suivi.get("alertes", []))
    al_html = f'<ul class="alerte-site">{al_html}</ul>' if al_html else ""
    av = "".join(f'<li>🔶 {_e(a)}</li>' for a in suivi.get("a_verifier", []))
    al_html += f'<ul class="alerte-site verifier">{av}</ul>' if av else ""
    note = f'<p class="discret">{_e(suivi["note_alertes"])}</p>' if suivi.get("note_alertes") else ""
    chg = "".join(f'<p class="discret">{_e(suivi[k])}</p>' for k in ("changements", "stabilite") if suivi.get(k))
    afaire_html = f'''
  <section class="afaire" aria-label="À faire avant la prochaine deadline">
    <div class="ech" id="deadline" data-iso="{dl0.isoformat()}">
      <span>Avant <b>{_e(j0["event"]["name"])}</b>, {_e(_paris(dl0, tz))}</span>
      <span class="chiffre" id="compte">…</span>
    </div>
    {al_html}
    <ul class="actions">
      <li><span class="ic">✅</span><div><b>Titulaires</b><ul class="tits">{"".join(tit_items)}</ul></div></li>
      <li><span class="ic">🔁</span><div><b>Transferts</b> {(" ; ".join(tr_soir)) if tr_soir else "Aucun avant cette deadline"}</div></li>
      <li><span class="ic">⭐</span><div><b>Capitaine</b> {cap_txt}</div></li>
    </ul>
    {prochain}{note}{chg}
  </section>'''
    sources = "".join(f"<li>{_e(n)} : {_e(s)}</li>" for n, s in ctx["sources"].items())
    genere = _paris(dt.datetime.now(dt.timezone.utc), tz)

    return f'''<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(titre)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;700;800&family=Barlow:wght@400;500;600&display=swap">
<style>
:root {{
  --fond: #eef1f5; --surface: #ffffff; --encre: #16213d; --doux: #5b6680; --trait: #d6dbe5;
  --parquet: #e3b678; --parquet-2: #d7a764; --ligne: rgba(255,255,255,.85);
  --maillot: #1b2a52; --maillot-txt: #ffffff; --cap: #f2a516; --cap-txt: #16213d;
  --action: #2453e6; --action-doux: #e5ecff; --vert: #198a5a; --vert-doux: #e2f4eb;
  --alerte: #b5650b; --alerte-doux: #fff3df; --repos: #f4f6f9;
  --fc: #b82a35; --bc: #24407f; --entete-txt: #ffffff; --rouge: #b42318; --rouge-doux: #fdecea;
  color-scheme: light;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --fond: #0f1526; --surface: #18213a; --encre: #e8ecf5; --doux: #9aa5bf; --trait: #2a3552;
    --parquet: #8a6a3f; --parquet-2: #7d5f37; --ligne: rgba(255,255,255,.6);
    --maillot: #e8ecf5; --maillot-txt: #16213d; --cap: #f2a516; --cap-txt: #16213d;
    --action: #7d9bff; --action-doux: #1f2c55; --vert: #4cc792; --vert-doux: #163a2c;
    --alerte: #f2b45a; --alerte-doux: #3a2a12; --repos: #141b30;
    --fc: #9e2630; --bc: #2b4a91; --entete-txt: #ffffff; --rouge: #ff8a80; --rouge-doux: #3d1715;
    color-scheme: dark;
  }}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--fond); color: var(--encre);
  font: 16px/1.5 Barlow, "Helvetica Neue", Arial, sans-serif; }}
main {{ max-width: 980px; margin: 0 auto; padding: 32px 20px 48px; }}
h1, h2, .chiffre {{ font-family: "Barlow Condensed", "Arial Narrow", sans-serif; }}
h1 {{ font-size: clamp(2rem, 5vw, 3.1rem); line-height: 1.02; font-weight: 800; margin: 4px 0 10px; letter-spacing: -.01em; }}
h2 {{ font-size: 1.45rem; font-weight: 700; margin: 0 0 10px; }}
.sous {{ color: var(--doux); margin: 0; font-weight: 500; }}
.deadline {{ display: inline-flex; gap: 10px; align-items: baseline; margin-top: 14px; padding: 8px 14px;
  background: var(--surface); border: 1px solid var(--trait); border-radius: 10px; }}
.deadline {{ flex-wrap: wrap; }} .deadline .chiffre {{ font-size: 1.6rem; font-weight: 700; white-space: nowrap; }}
.deadline.proche {{ border-color: var(--alerte); background: var(--alerte-doux); }}
.deadline.passee {{ border-color: var(--doux); opacity: .8; }}

.soir {{ display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr); gap: 28px; margin-top: 28px; align-items: start; }}
@media (max-width: 760px) {{ .soir {{ grid-template-columns: 1fr; }} }}
.terrain {{ width: 100%; height: auto; display: block; }}
.cadre {{ margin: 0; }} .cadre figcaption {{ color: var(--doux); font-size: .85rem; margin-top: 8px; }}
.parquet {{ fill: var(--parquet); }}
.lignes * {{ stroke: var(--ligne); stroke-width: 3; fill: none; }}
.maillot {{ fill: var(--maillot); stroke: var(--surface); stroke-width: 3; }}
.pts {{ fill: var(--maillot-txt); font: 700 24px "Barlow Condensed", sans-serif; text-anchor: middle; }}
.nom {{ fill: #16213d; font: 700 20px "Barlow Condensed", sans-serif; text-anchor: middle; paint-order: stroke; stroke: var(--parquet); stroke-width: 4px; }}
.adv {{ fill: #3a2c17; font: 500 15px Barlow, sans-serif; text-anchor: middle; }}
@media (prefers-color-scheme: dark) {{ .nom {{ fill: #fff; }} .adv {{ fill: #f3e2c6; }} }}
.cap-badge {{ fill: var(--cap); stroke: var(--surface); stroke-width: 3; }}
.cap-txt {{ fill: var(--cap-txt); font: 800 15px "Barlow Condensed", sans-serif; text-anchor: middle; }}
.capitaine .maillot {{ stroke: var(--cap); stroke-width: 5; }}
.jeton:focus {{ outline: none; }} .jeton:focus .maillot {{ stroke: var(--action); stroke-width: 5; }}

.colonne > section + section {{ margin-top: 22px; }}
.banc ul, .alertes ul {{ list-style: none; padding: 0; margin: 0; }}
.banc li {{ display: grid; grid-template-columns: 34px 1fr; column-gap: 8px; padding: 7px 0; border-top: 1px solid var(--trait); }}
.banc li:first-child {{ border-top: 0; }}
.banc .pourquoi {{ grid-column: 2; color: var(--doux); font-size: .9rem; }}
.qui small, .vend small, .achete small {{ color: var(--doux); font-weight: 500; }}
.poste {{ display: inline-block; font: 700 .75rem Barlow, sans-serif; color: var(--doux); border: 1px solid var(--trait);
  border-radius: 4px; padding: 0 4px; margin-right: 6px; line-height: 1.5; }}
.banc .poste {{ margin: 3px 0 0; justify-self: start; }}

.transferts {{ margin-top: 34px; padding: 20px 22px; background: var(--surface); border-radius: 14px; border: 1px solid var(--trait); }}
.transferts.urgent {{ border: 2px solid var(--action); }}
.transferts.calme {{ background: transparent; }}
.quand {{ margin: 0 0 14px; }}
.echanges {{ list-style: none; padding: 0; margin: 0; display: grid; gap: 10px; }}
.echanges li {{ display: grid; grid-template-columns: 1fr 44px 1fr; align-items: center; gap: 8px; }}
.echanges li > div {{ padding: 10px 14px; border-radius: 10px; display: flex; flex-direction: column; }}
.echanges span {{ font-size: .8rem; color: var(--doux); }}
.echanges b {{ font: 700 1.25rem "Barlow Condensed", sans-serif; }}
.vend {{ background: var(--repos); }} .vend b {{ text-decoration: line-through; text-decoration-thickness: 2px; text-decoration-color: var(--doux); }}
.achete {{ background: var(--vert-doux); }} .achete b {{ color: var(--vert); }}
.fleche path {{ stroke: var(--doux); stroke-width: 2.5; fill: none; stroke-linecap: round; stroke-linejoin: round; }}
@media (max-width: 560px) {{ .echanges li {{ grid-template-columns: 1fr; }} .fleche {{ transform: rotate(90deg); width: 28px; justify-self: center; }} }}
.note {{ color: var(--doux); font-size: .92rem; margin: 12px 0 0; }}
.alerte-txt {{ color: var(--alerte); }}

.alertes {{ margin-top: 22px; padding: 14px 18px; border-radius: 12px; background: var(--alerte-doux); }}
.alertes h2 {{ color: var(--alerte); font-size: 1.2rem; margin-bottom: 4px; }}
.alertes li {{ padding: 3px 0; }}

.semaine {{ margin-top: 34px; }}
.defile {{ overflow-x: auto; border: 1px solid var(--trait); border-radius: 12px; background: var(--surface); }}
table {{ border-collapse: collapse; width: 100%; min-width: 560px; }}
th, td {{ padding: 0; text-align: center; }}
thead th {{ font: 700 1rem "Barlow Condensed", sans-serif; padding: 10px 6px 8px; border-bottom: 1px solid var(--trait); }}
thead th small {{ display: block; font: 500 .78rem Barlow, sans-serif; color: var(--doux); }}
thead th.auj {{ color: var(--action); }}
tbody th, thead th:first-child, tfoot th {{ position: sticky; left: 0; background: var(--surface); z-index: 1; }}
tbody th {{ text-align: left; font-weight: 600; padding: 8px 12px; white-space: nowrap; }}
@media (max-width: 560px) {{ tbody th {{ padding: 8px 8px; font-size: .92rem; }} .tag {{ display: none; }} }}
tbody tr + tr > * {{ border-top: 1px solid var(--trait); }}
tbody tr.sort th {{ color: var(--doux); }}
td {{ height: 40px; min-width: 48px; }}
td span {{ display: inline-block; width: 22px; height: 22px; border-radius: 50%; vertical-align: middle; }}
td.tit span {{ background: var(--maillot); }}
td.banc span {{ border: 2px solid var(--maillot); opacity: .55; }}
td.cap span {{ background: var(--cap); color: var(--cap-txt); font: 800 .85rem/22px "Barlow Condensed", sans-serif; }}
td.repos {{ background: transparent; }}
td.hors {{ background: repeating-linear-gradient(-45deg, transparent 0 5px, var(--repos) 5px 10px); }}
tfoot th, tfoot td {{ padding: 8px 6px; border-top: 1px solid var(--trait); font: 700 1.05rem "Barlow Condensed", sans-serif; }}
tfoot th {{ text-align: left; padding-left: 12px; font-weight: 600; font-family: Barlow, sans-serif; font-size: .9rem; color: var(--doux); }}
.tag {{ font-style: normal; font-size: .72rem; font-weight: 600; padding: 1px 6px; border-radius: 4px; margin-left: 4px; }}
.tag.sort {{ background: var(--repos); color: var(--doux); }}
.tag.entre {{ background: var(--vert-doux); color: var(--vert); }}
.legende {{ display: flex; flex-wrap: wrap; gap: 16px; margin: 10px 2px 0; color: var(--doux); font-size: .88rem; }}
.legende i {{ display: inline-block; width: 14px; height: 14px; border-radius: 50%; vertical-align: -2px; margin-right: 6px; }}
.l-tit {{ background: var(--maillot); }} .l-banc {{ border: 2px solid var(--maillot); opacity: .55; }} .l-cap {{ background: var(--cap); }}
.l-hors {{ border-radius: 3px !important; background: repeating-linear-gradient(-45deg, transparent 0 3px, var(--doux) 3px 5px); opacity: .5; }}
.semaine .defile + .defile {{ margin-top: 14px; }}
.effectif-t {{ min-width: 720px; }}
.effectif-t thead th {{ background: var(--fc); color: var(--entete-txt); border-bottom: 0; padding: 12px 8px; font-size: 1.05rem; letter-spacing: .02em; }}
.effectif-t.bc thead th {{ background: var(--bc); }}
.effectif-t thead th small {{ color: rgba(255,255,255,.75); }}
.effectif-t thead th.auj {{ color: var(--entete-txt); box-shadow: inset 0 -4px 0 var(--cap); }}
.effectif-t thead th.titre-t {{ text-align: left; padding-left: 16px; font-size: 1.5rem; min-width: 210px; }}
.effectif-t tbody th {{ padding: 8px 12px; }}
.joueur {{ display: flex; align-items: center; gap: 10px; }}
.tete {{ width: 64px; height: 47px; object-fit: cover; object-position: top; border-radius: 6px; background: var(--repos); flex: none; }}
.joueur > div {{ display: flex; flex-direction: column; line-height: 1.15; }}
.prenom {{ font-weight: 500; font-size: .92rem; }}
.nomf {{ font: 700 1.1rem "Barlow Condensed", sans-serif; }}
.eq {{ font: 700 .95rem "Barlow Condensed", sans-serif; color: var(--doux); margin-top: 2px; }}
.statut {{ font-style: italic; font-weight: 600; margin-left: 4px; }}
.s-ok {{ color: var(--alerte); }} .s-doute {{ color: var(--alerte); font-style: normal; }} .s-out {{ color: var(--fc); font-style: normal; }}
.effectif-t td.num {{ font: 500 1.05rem "Barlow Condensed", sans-serif; min-width: 52px; padding: 0 6px; }}
.effectif-t td.fort {{ font-weight: 700; }}
.effectif-t td {{ height: 66px; }}
.effectif-t td.m {{ position: relative; }}
.effectif-t td span.adv-logo {{ display: block; width: 34px; height: 34px; margin: 0 auto; border-radius: 0; background: none; border: 0; font: 700 .8rem/34px Barlow, sans-serif; }}
.adv-logo img {{ width: 34px; height: 34px; object-fit: contain; }}
.effectif-t td.m small {{ display: block; color: var(--doux); font-size: .72rem; line-height: 1; }}
.effectif-t td span.tiret {{ width: 26px; height: 4px; border-radius: 2px; background: var(--doux); opacity: .55; }}
.role {{ position: absolute; top: 5px; right: 5px; width: 10px; height: 10px; border-radius: 50%; font-style: normal; }}
td.tit .role {{ background: var(--maillot); }}
td.banc .role {{ border: 2px solid var(--maillot); opacity: .55; }}
td.cap .role {{ width: 17px; height: 17px; top: 3px; right: 3px; background: var(--cap); color: var(--cap-txt); font: 800 .75rem/17px "Barlow Condensed", sans-serif; }}
td.banc .adv-logo {{ opacity: .5; }}
.effectif-t tfoot td {{ padding: 8px 6px; }}
.effectif-t thead th.suiv {{ filter: saturate(.35) brightness(.85); }}
.effectif-t td.suiv {{ background-color: var(--repos); }}
.effectif-t .sep {{ border-left: 3px solid var(--trait); }}
.resume {{ display: flex; flex-wrap: wrap; gap: 28px; margin-top: 18px; }}
.resume div {{ display: flex; flex-direction: column; }}
.resume .chiffre {{ font-size: 1.9rem; font-weight: 700; line-height: 1.1; }}
.resume span {{ color: var(--doux); font-size: .9rem; }}

.afaire {{ background: var(--surface); border: 2px solid var(--action); border-radius: 16px; padding: 16px 18px;
  margin: 0 0 22px; font-size: 1.05rem; }}
.afaire .ech {{ display: flex; flex-wrap: wrap; justify-content: space-between; gap: 4px 12px; align-items: baseline;
  padding-bottom: 10px; border-bottom: 1px solid var(--trait); }}
.afaire .ech .chiffre {{ font-size: 1.5rem; font-weight: 700; white-space: nowrap; }}
.afaire .ech.proche .chiffre {{ color: var(--alerte); }}
.afaire .ech.passee .chiffre {{ color: var(--doux); font-size: 1.1rem; }}
.alerte-site {{ list-style: none; margin: 12px 0 0; padding: 10px 12px; border-radius: 10px;
  background: var(--rouge-doux); color: var(--rouge); font-weight: 600; }}
.alerte-site li + li {{ margin-top: 6px; }}
.alerte-site.verifier {{ background: var(--alerte-doux); color: var(--alerte); }}
.actions {{ list-style: none; margin: 12px 0 0; padding: 0; display: grid; gap: 12px; }}
.actions > li {{ display: grid; grid-template-columns: 28px 1fr; gap: 8px; align-items: start; }}
.actions .ic {{ font-size: 1.25rem; line-height: 1.3; }}
.tits {{ list-style: none; padding: 0; margin: 4px 0 0; display: grid; gap: 3px; }}
.tits small {{ color: var(--doux); }}
.tits .vide {{ color: var(--alerte); }}
.force {{ display: inline-block; font-size: .85rem; font-weight: 600; padding: 0 6px; border-radius: 6px;
  background: var(--repos); white-space: nowrap; }}
.discret {{ color: var(--doux); font-size: .9rem; margin: 10px 0 0; }}
details.semaine > summary, #gw2 > summary {{ cursor: pointer; }}
details.semaine > summary h2 {{ display: inline; }}
#gw2 {{ margin: 0 0 10px; color: var(--action); font-weight: 600; }}
body:not(:has(#gw2[open])) .suiv {{ display: none; }}
.construction {{ margin-top: 26px; padding: 20px 22px; border-radius: 14px; border: 2px solid var(--action); background: var(--surface); }}
.construction > p {{ margin: 0 0 12px; max-width: 70ch; }}
.effectif {{ list-style: none; padding: 0; margin: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 8px; }}
.effectif li {{ padding: 8px 12px; border-radius: 10px; background: var(--repos); display: flex; flex-direction: column; }}
.effectif li.neuf {{ background: var(--vert-doux); }}
.effectif b {{ font: 700 1.15rem "Barlow Condensed", sans-serif; }}
.effectif small {{ color: var(--doux); }}
.effectif .poste {{ align-self: flex-start; margin-bottom: 2px; }}
.effectif .tag {{ align-self: flex-start; margin: 4px 0 0; }}
footer {{ margin-top: 40px; color: var(--doux); font-size: .85rem; }}
footer ul {{ list-style: none; padding: 0; margin: 6px 0 0; display: flex; flex-wrap: wrap; gap: 4px 18px; }}
@media (prefers-reduced-motion: no-preference) {{
  .jeton {{ animation: entree .5s ease-out both; }}
  .jeton:nth-of-type(2) {{ animation-delay: .06s; }} .jeton:nth-of-type(3) {{ animation-delay: .12s; }}
  .jeton:nth-of-type(4) {{ animation-delay: .18s; }} .jeton:nth-of-type(5) {{ animation-delay: .24s; }}
  @keyframes entree {{ from {{ opacity: 0; transform: translateY(8px); }} }}
}}
</style>
</head>
<body>
<main>
  {afaire_html}
  <header>
    <p class="sous">{sous_titre}</p>
    <h1>{_e(titre)}</h1>
  </header>

  {alertes_html}
  {constr_html}

  <div class="soir">
    <figure class="cadre">
      {_court(j0["titulaires"], j0["capitaine"], j, adversaire_soir)}
      <figcaption>Le chiffre sur chaque maillot : points projetés ce soir (doublés pour le capitaine). Heures de Paris.</figcaption>
    </figure>
    <div class="colonne">
      <section>
        <h2>Capitaine</h2>
        {cap_html}
      </section>
      <section class="banc">
        <h2>Sur le banc ce soir</h2>
        <ul>{''.join(banc) or '<li>Personne</li>'}</ul>
      </section>
    </div>
  </div>

  <section class="transferts {tr_classe}">
    <h2>Transferts</h2>
    {tr_html}
  </section>

  <details class="semaine" open>
    <summary><h2>Ton effectif, jour par jour</h2></summary>
    <details id="gw2"><summary>Afficher aussi la semaine suivante</summary></details>
    {tableaux}
    {titre_suiv}
    <div class="legende">
      <span><i class="l-tit"></i>titulaire</span><span><i class="l-cap"></i>capitaine</span>
      <span><i class="l-banc"></i>joue, mais sur le banc</span><span><i class="l-hors"></i>pas dans ton équipe ce jour-là</span>
      <span>— : pas de match</span><span>B2B : 2e soir d’affilée (effet mesuré pour chaque joueur la saison passée)</span><span>VAL : points projetés par M$</span><span>TP : total de points la saison passée</span>
    </div>
    <div class="resume">
      <div><span class="chiffre">{plan['pts_semaine']:.0f}</span><span>pts projetés d’ici la fin de semaine</span></div>
      <div><span class="chiffre">{base['pts_semaine']:.0f}</span><span>sans aucun transfert</span></div>
      <div><span class="chiffre">{_m(ctx['banque']/10)} M$</span><span>en banque</span></div>
      <div><span class="chiffre">{ctx['gratuits']}</span><span>transferts gratuits restants</span></div>
    </div>
  </details>

  <footer>
    Généré le {_e(genere)}. Équipe lue depuis : {_e(ctx['src_equipe'])}. Projections indicatives : vérifie les blessures de dernière minute avant de valider.
    <ul>{sources}</ul>
  </footer>
</main>
<script>
(function () {{
  var box = document.getElementById("deadline"), out = document.getElementById("compte");
  var fin = new Date(box.dataset.iso).getTime();
  function maj() {{
    var ms = fin - Date.now();
    if (ms <= 0) {{ out.textContent = "deadline passée : recalcule"; box.classList.add("passee"); return; }}
    var h = Math.floor(ms / 3600000), m = Math.floor(ms % 3600000 / 60000);
    out.textContent = "dans " + (h >= 24 ? Math.floor(h / 24) + " j " + (h % 24) + " h" : h + " h " + String(m).padStart(2, "0"));
    box.classList.toggle("proche", ms < 3 * 3600000);
  }}
  maj(); setInterval(maj, 60000);
}})();
</script>
</body>
</html>'''
