"""Publie le rapport sur GitHub Pages (dossier docs/) : page « appli » + journal + icônes.

    python3 publier.py

Utilisé par GitHub Actions après chaque passage du planificateur. Il réutilise les balises « appli »
et l'icône de serveur.py ; le bouton « Recalculer » ouvre la page GitHub du calcul (Run workflow).
"""
import html, os
from datetime import datetime
from pathlib import Path

import serveur

ICI = Path(__file__).resolve().parent
DOCS = ICI / "docs"
RECALCUL = os.environ.get("RECALCUL_URL", "")

BARRE = """
<div id="aa-barre" style="position:fixed;left:0;right:0;bottom:0;z-index:99999;
  display:flex;align-items:center;gap:12px;padding:10px 16px calc(10px + env(safe-area-inset-bottom));
  background:#1d428a;color:#fff;font:15px -apple-system,system-ui,sans-serif;box-shadow:0 -2px 8px rgba(0,0,0,.2)">
  <span style="flex:1;min-width:0">__INFO__ · <a href="journal.html" style="color:#fff">journal</a></span>
  __BOUTON__
</div>
<div style="height:80px"></div>
"""


def barre():
    t = serveur.date_dernier_rapport()
    info = f"Rapport du {t:%d/%m à %H:%M}" if t else "Aucun rapport"
    bouton = (f'<a href="{RECALCUL}" style="font:600 15px -apple-system,system-ui,sans-serif;padding:10px 16px;'
              f'border-radius:10px;background:#fff;color:#1d428a;text-decoration:none;white-space:nowrap">Recalculer</a>'
              if RECALCUL else "")
    return BARRE.replace("__INFO__", info).replace("__BOUTON__", bouton)


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
    (DOCS / ".nojekyll").write_text("")
    print(f"Page publiée dans docs/ ({datetime.now():%H:%M})")


if __name__ == "__main__":
    main()
