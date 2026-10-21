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
debut = int(time.time())
while time.time() - debut < duree:
    time.sleep(20)
    if not sujet:
        continue
    try:
        with urllib.request.urlopen(f"https://ntfy.sh/{sujet}/json?poll=1&since={debut}", timeout=15) as r:
            if any(json.loads(l).get("event") == "message" for l in r.read().decode().splitlines() if l.strip()):
                print("Demande de recalcul reçue")
                sys.exit(0)
    except Exception:
        pass
sys.exit(1)
