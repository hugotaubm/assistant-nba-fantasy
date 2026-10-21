"""Attend une demande « Recalculer » envoyée par le bouton de la page (canal ntfy « ntfy_recalcul »).

    python3 attendre_demande.py 600     # attend jusqu'à 600 s ; code 0 = demande reçue, 1 = rien

Utilisé par le veilleur GitHub à la place d'une simple pause de 10 min : un appui sur le bouton
déclenche le calcul en moins d'une demi-minute.
"""
import json, sys, time, urllib.request
from pathlib import Path

ICI = Path(__file__).resolve().parent
sujet = json.loads((ICI / "config.json").read_text(encoding="utf-8")).get("ntfy_recalcul")
duree = int(sys.argv[1]) if len(sys.argv) > 1 else 600
# Dernier signal déjà traité : un appui pendant un calcul n'est pas perdu, il sera vu au prochain passage
memoire = Path("/tmp/derniere_demande")
debut = int(time.time())
depuis = int(memoire.read_text()) if memoire.exists() else debut
while time.time() - debut < duree:
    if sujet:
        try:
            with urllib.request.urlopen(f"https://ntfy.sh/{sujet}/json?poll=1&since={depuis}", timeout=15) as r:
                msgs = [json.loads(l) for l in r.read().decode().splitlines() if l.strip()]
            msgs = [m for m in msgs if m.get("event") == "message"]
            if msgs:
                memoire.write_text(str(max(m["time"] for m in msgs) + 1))
                print("Demande de recalcul reçue")
                sys.exit(0)
        except Exception:
            pass
    time.sleep(20)
sys.exit(1)
