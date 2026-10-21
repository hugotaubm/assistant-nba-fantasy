"""Publie le rapport sur GitHub Pages (dossier docs/) : page « appli » + journal + icônes.

    python3 publier.py

Utilisé par GitHub Actions après chaque passage du planificateur. Il réutilise les balises « appli »
et l'icône de serveur.py. Le bouton « Recalculer » lance le raccourci iPhone « Recalculer NBA »
(sur iPhone/iPad, si "raccourci_iphone": true dans config.json) ou ouvre la page GitHub du calcul. Le raccourci rouvre
la page avec ?attente=1 : elle attend alors toute seule le nouveau rapport (etat.json).
"""
import html, json, os, re
from datetime import datetime
from pathlib import Path

import serveur

ICI = Path(__file__).resolve().parent
DOCS = ICI / "docs"
RECALCUL = os.environ.get("RECALCUL_URL", "https://github.com/hugotaubm/assistant-nba-fantasy/actions/workflows/assistant.yml")
RACCOURCI = "shortcuts://run-shortcut?name=" + "Recalculer%20NBA"
# Le raccourci n'est utilisé que s'il existe ("raccourci_iphone": true dans config.json),
# sinon iOS afficherait une erreur : le bouton ouvre alors la page GitHub.
AVEC_RACCOURCI = json.loads((ICI / "config.json").read_text(encoding="utf-8")).get("raccourci_iphone", False)

BARRE = """
<div id="aa-barre" style="position:fixed;left:0;right:0;bottom:0;z-index:99999;
  display:flex;align-items:center;gap:12px;padding:10px 16px calc(10px + env(safe-area-inset-bottom));
  background:#1d428a;color:#fff;font:15px -apple-system,system-ui,sans-serif;box-shadow:0 -2px 8px rgba(0,0,0,.2)">
  <span style="flex:1;min-width:0"><span id="aa-info">__INFO__</span> · <a href="journal.html" style="color:#fff">journal</a></span>
  __BOUTON__
</div>
<div style="height:80px"></div>
<script>
(function () {
  // Sur iPhone/iPad, le bouton lance le raccourci « Recalculer NBA » ; ailleurs, la page GitHub.
  var bouton = document.getElementById("aa-recalculer");
  if (bouton && __AVEC_RACCOURCI__ && /iPhone|iPad|iPod/.test(navigator.userAgent)) bouton.href = "__RACCOURCI__";
  // Ouverte par le raccourci avec ?attente=1 : on attend le nouveau rapport puis on recharge.
  if (!/[?&]attente=/.test(location.search)) return;
  var info = document.getElementById("aa-info"), depart = Date.now(), actuel = __DERNIER__;
  info.textContent = "⏳ Calcul en cours… (2 à 4 min)";
  var minuteur = setInterval(function () {
    fetch("etat.json?t=" + Date.now(), {cache: "no-store"}).then(function (r) { return r.json(); }).then(function (e) {
      if (e.dernier && e.dernier !== actuel) { clearInterval(minuteur); location.replace(location.pathname); }
    }).catch(function () {});
    if (Date.now() - depart > 8 * 60 * 1000) {
      clearInterval(minuteur);
      info.innerHTML = 'Toujours rien après 8 min : regarde le <a href="journal.html" style="color:#fff">journal</a>';
    }
  }, 15000);
})();
</script>
"""


def date_rapport():
    """Heure de fin du dernier calcul, lue dans le rapport texte (sur GitHub, la date du fichier
    est celle du checkout : elle changerait à chaque passage)."""
    if not serveur.RAPPORT_TEXTE.exists():
        return None
    m = re.findall(r"Terminé le (\d\d/\d\d/\d{4}) à (\d\d:\d\d:\d\d)", serveur.RAPPORT_TEXTE.read_text(errors="replace"))
    return datetime.strptime(" ".join(m[-1]), "%d/%m/%Y %H:%M:%S") if m else serveur.date_dernier_rapport()


def barre():
    t = date_rapport()
    info = f"Rapport du {t:%d/%m à %H:%M}" if t else "Aucun rapport"
    bouton = (f'<a id="aa-recalculer" href="{RECALCUL}" style="font:600 15px -apple-system,system-ui,sans-serif;padding:10px 16px;'
              f'border-radius:10px;background:#fff;color:#1d428a;text-decoration:none;white-space:nowrap">Recalculer</a>'
              if RECALCUL else "")
    dernier = json.dumps(t.isoformat() if t else None)
    return (BARRE.replace("__INFO__", info).replace("__BOUTON__", bouton)
            .replace("__RACCOURCI__", RACCOURCI)
            .replace("__AVEC_RACCOURCI__", "true" if AVEC_RACCOURCI else "false").replace("__DERNIER__", dernier))


def avec_appli(contenu):
    entete = serveur.ENTETE_APPLI.replace('href="/manifest.json"', 'href="manifest.json"').replace(
        'href="/icone-180.png"', 'href="icone-180.png"')
    contenu = contenu.replace("<head>", "<head>\n" + entete, 1) if "<head>" in contenu else entete + contenu
    i = contenu.rfind("</body>")
    return contenu[:i] + barre() + contenu[i:] if i >= 0 else contenu + barre()


def main():
    DOCS.mkdir(exist_ok=True)
    rapport = ICI / "rapport.html"
    if rapport.exists():
        (DOCS / "index.html").write_text(avec_appli(rapport.read_text(errors="replace")), encoding="utf-8")
    texte = serveur.RAPPORT_TEXTE.read_text(errors="replace") if serveur.RAPPORT_TEXTE.exists() else "Pas encore de calcul."
    (DOCS / "journal.html").write_text(avec_appli(
        f'<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>Journal</title></head><body style="font-family:'
        f'-apple-system,system-ui,sans-serif;padding:16px"><p><a href="./">← Retour au rapport</a></p>'
        f'<pre style="white-space:pre-wrap;font-size:13px">{html.escape(texte)}</pre></body></html>'), encoding="utf-8")
    manifeste = serveur.MANIFESTE.replace('"/icone-', '"icone-').replace('"start_url": "/"', '"start_url": "./"')
    (DOCS / "manifest.json").write_text(manifeste, encoding="utf-8")
    for taille in (180, 192, 512):
        f = DOCS / f"icone-{taille}.png"
        if not f.exists():
            f.write_bytes(serveur.icone(taille))
    t = date_rapport()
    (DOCS / "etat.json").write_text(json.dumps({"dernier": t.isoformat() if t else None}), encoding="utf-8")
    (DOCS / ".nojekyll").write_text("")
    print(f"Page publiée dans docs/ ({datetime.now():%H:%M})")


if __name__ == "__main__":
    main()
