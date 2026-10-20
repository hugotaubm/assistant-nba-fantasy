"""Petit serveur local : ouvre http://localhost:8765 dans ton navigateur.

Il affiche le dernier rapport de l'assistant avec un bouton
« Recalculer » qui relance lancer_assistant.sh. La page peut être
ajoutée à l'écran d'accueil de l'iPhone comme une appli.
"""
import html
import json
import os
import struct
import subprocess
import sys
import threading
import zlib
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8765
DOSSIER = Path(__file__).resolve().parent
RAPPORT_TEXTE = DOSSIER / "rapport" / "dernier_rapport.txt"
VERROU = DOSSIER / "rapport" / ".verrou"

# Si ton assistant.py crée lui-même un fichier HTML (ex. "rapport.html"),
# écris son nom ici pour l'afficher dans la page. Sinon laisse None.
RAPPORT_HTML = "rapport.html"

NOM_APPLI = "NBA Fantasy"
COULEUR = "#1d428a"


def calcul_en_cours():
    return VERROU.exists()


def lancer_calcul():
    env = dict(os.environ, PYTHON=sys.executable)
    subprocess.run(["/bin/bash", str(DOSSIER / "lancer_assistant.sh")], env=env)


def date_dernier_rapport():
    if not RAPPORT_TEXTE.exists():
        return None
    return datetime.fromtimestamp(RAPPORT_TEXTE.stat().st_mtime)


def icone_png(taille):
    """Dessine l'icône de l'appli (un ballon orange) en PNG, sans bibliothèque."""
    c = taille / 2
    r = taille * 0.36
    trait = max(2, taille // 45)
    fond, ballon, ligne = (0x1D, 0x42, 0x8A), (0xF5, 0x84, 0x26), (0x22, 0x22, 0x22)
    lignes = []
    for y in range(taille):
        rangee = bytearray([0])
        for x in range(taille):
            dx, dy = x - c, y - c
            d = (dx * dx + dy * dy) ** 0.5
            if d > r:
                px = fond
            elif d > r - trait or abs(dx) < trait / 2 or abs(dy) < trait / 2:
                px = ligne
            elif abs(((dx + r * 0.95) ** 2 + dy * dy) ** 0.5 - r * 0.7) < trait / 2 or \
                    abs(((dx - r * 0.95) ** 2 + dy * dy) ** 0.5 - r * 0.7) < trait / 2:
                px = ligne
            else:
                px = ballon
            rangee += bytes(px)
        lignes.append(bytes(rangee))

    def bloc(type_, donnees):
        return (struct.pack(">I", len(donnees)) + type_ + donnees
                + struct.pack(">I", zlib.crc32(type_ + donnees) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + bloc(b"IHDR", struct.pack(">IIBBBBB", taille, taille, 8, 2, 0, 0, 0))
            + bloc(b"IDAT", zlib.compress(b"".join(lignes), 9))
            + bloc(b"IEND", b""))


ICONES = {}


def icone(taille):
    if taille not in ICONES:
        ICONES[taille] = icone_png(taille)
    return ICONES[taille]


MANIFESTE = json.dumps({
    "name": NOM_APPLI,
    "short_name": NOM_APPLI,
    "start_url": "/",
    "display": "standalone",
    "background_color": "#ffffff",
    "theme_color": COULEUR,
    "icons": [
        {"src": "/icone-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "/icone-512.png", "sizes": "512x512", "type": "image/png"},
    ],
})

# Balises qui permettent d'installer la page comme une appli sur le téléphone.
ENTETE_APPLI = f"""<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="{NOM_APPLI}">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="{COULEUR}">
<link rel="manifest" href="/manifest.json">
<link rel="apple-touch-icon" href="/icone-180.png">"""

# Barre fixée en bas de l'écran, ajoutée par-dessus le rapport.
BARRE = """
<div id="aa-barre" style="position:fixed;left:0;right:0;bottom:0;z-index:99999;
  display:flex;align-items:center;gap:12px;padding:10px 16px calc(10px + env(safe-area-inset-bottom));
  background:#1d428a;color:#fff;font:15px -apple-system,system-ui,sans-serif;box-shadow:0 -2px 8px rgba(0,0,0,.2)">
  <span id="aa-info" style="flex:1;min-width:0">__INFO__</span>
  <button id="aa-bouton" style="font:600 15px -apple-system,system-ui,sans-serif;padding:10px 16px;border:0;
    border-radius:10px;background:#fff;color:#1d428a;white-space:nowrap">Recalculer</button>
</div>
<div style="height:80px"></div>
<script>
(function () {
  var bouton = document.getElementById("aa-bouton");
  var info = document.getElementById("aa-info");
  function attendre() {
    bouton.disabled = true;
    bouton.style.opacity = ".5";
    info.textContent = "⏳ Calcul en cours… (jusqu'à 2 min)";
    var minuteur = setInterval(function () {
      fetch("/etat", {cache: "no-store"}).then(function (r) { return r.json(); }).then(function (e) {
        if (!e.en_cours) { clearInterval(minuteur); location.reload(); }
      }).catch(function () {});
    }, 3000);
  }
  bouton.addEventListener("click", function () {
    fetch("/recalculer", {method: "POST"}).then(attendre);
  });
  if (__EN_COURS__) attendre();
})();
</script>
"""


def barre():
    quand = date_dernier_rapport()
    info = f"Rapport du {quand:%d/%m à %H:%M}" if quand else "Aucun rapport"
    info += ' · <a href="/journal" style="color:#fff">journal</a>'
    return BARRE.replace("__INFO__", info).replace("__EN_COURS__", "true" if calcul_en_cours() else "false")


def page_journal():
    """Sortie texte du dernier calcul (utile en cas d'erreur)."""
    if RAPPORT_TEXTE.exists():
        texte = html.escape(RAPPORT_TEXTE.read_text(errors="replace"))
    else:
        texte = "Appuie sur « Recalculer » pour lancer un premier calcul."
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
{ENTETE_APPLI}
<title>{NOM_APPLI}</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; margin: 0; padding: 16px; background: #fafafa; color: #222; }}
  pre {{ background: #fff; border: 1px solid #ddd; border-radius: 8px; padding: 12px; white-space: pre-wrap;
        font-size: 13px; overflow-wrap: anywhere; }}
  a {{ color: {COULEUR}; }}
</style></head><body>
<p><a href="/">← Retour au rapport</a></p>
<pre>{texte}</pre>
{barre()}
</body></html>"""


def page_accueil():
    """Le rapport HTML de l'assistant, avec la barre « Recalculer » en bas."""
    fichier = DOSSIER / RAPPORT_HTML if RAPPORT_HTML else None
    if not fichier or not fichier.exists():
        return page_journal()
    contenu = fichier.read_text(errors="replace")
    # Ajoute les balises « appli » dans <head> et la barre avant </body>.
    if "<head>" in contenu:
        contenu = contenu.replace("<head>", "<head>\n" + ENTETE_APPLI, 1)
    else:
        contenu = ENTETE_APPLI + contenu
    if "</body>" in contenu:
        i = contenu.rfind("</body>")
        contenu = contenu[:i] + barre() + contenu[i:]
    else:
        contenu += barre()
    return contenu


class Gestionnaire(BaseHTTPRequestHandler):
    def envoyer(self, code, contenu, type_="text/html; charset=utf-8"):
        donnees = contenu.encode() if isinstance(contenu, str) else contenu
        self.send_response(code)
        self.send_header("Content-Type", type_)
        self.send_header("Content-Length", str(len(donnees)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(donnees)

    def do_GET(self):
        chemin = self.path.split("?")[0]
        if chemin == "/":
            self.envoyer(200, page_accueil())
        elif chemin == "/journal":
            self.envoyer(200, page_journal())
        elif chemin == "/etat":
            quand = date_dernier_rapport()
            etat = {"en_cours": calcul_en_cours(), "dernier": quand.isoformat() if quand else None}
            self.envoyer(200, json.dumps(etat), "application/json")
        elif chemin == "/manifest.json":
            self.envoyer(200, MANIFESTE, "application/manifest+json")
        elif chemin in ("/icone-180.png", "/icone-192.png", "/icone-512.png", "/apple-touch-icon.png"):
            taille = 180 if chemin == "/apple-touch-icon.png" else int(chemin[7:10])
            self.envoyer(200, icone(taille), "image/png")
        else:
            self.envoyer(404, "Page introuvable")

    def do_POST(self):
        if self.path == "/recalculer":
            if not calcul_en_cours():
                threading.Thread(target=lancer_calcul, daemon=True).start()
                # Laisse au script le temps de poser son verrou
                # pour que la page affiche tout de suite « en cours ».
                for _ in range(20):
                    if calcul_en_cours():
                        break
                    threading.Event().wait(0.05)
            self.envoyer(200, json.dumps({"en_cours": calcul_en_cours()}), "application/json")
        else:
            self.envoyer(404, "Page introuvable")


if __name__ == "__main__":
    # 127.0.0.1 = accessible seulement depuis ton Mac. Le téléphone y accède
    # grâce à « tailscale serve », qui fait le lien de façon privée.
    serveur = ThreadingHTTPServer(("127.0.0.1", PORT), Gestionnaire)
    print(f"Serveur prêt : http://localhost:{PORT}")
    serveur.serve_forever()
