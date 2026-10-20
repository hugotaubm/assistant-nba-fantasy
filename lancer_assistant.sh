#!/bin/bash
# Lance assistant.py une seule fois et range ce qu'il affiche
# dans rapport/dernier_rapport.txt (lu ensuite par le serveur).

DOSSIER="$(cd "$(dirname "$0")" && pwd)"
cd "$DOSSIER" || exit 1
PYTHON="${PYTHON:-python3}"
mkdir -p rapport

# Verrou : empêche deux calculs en même temps (bouton + launchd).
# Un verrou de plus d'une heure est considéré comme oublié et supprimé.
find rapport/.verrou -maxdepth 0 -mmin +60 -exec rmdir {} \; 2>/dev/null
if ! mkdir rapport/.verrou 2>/dev/null; then
  echo "Un calcul est déjà en cours, rien à faire."
  exit 0
fi
trap 'rmdir rapport/.verrou' EXIT

{
  echo "Calcul lancé le $(date '+%d/%m/%Y à %H:%M:%S')"
  echo "----------------------------------------"
  "$PYTHON" assistant.py --pas-de-navigateur
  code=$?
  echo "----------------------------------------"
  echo "Terminé le $(date '+%d/%m/%Y à %H:%M:%S') (code de sortie : $code)"
} > rapport/en_cours.txt 2>&1

mv rapport/en_cours.txt rapport/dernier_rapport.txt
echo "$(date '+%Y-%m-%d %H:%M:%S') code=$code" >> rapport/historique.log
