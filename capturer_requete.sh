#!/bin/bash
# Attend que tu copies la requête « my-team » dans Chrome (clic droit → Copy → Copy as cURL),
# puis l'enregistre dans requete_mon_equipe.txt (lisible par toi seul). Rien n'est affiché.
DOSSIER="$(cd "$(dirname "$0")" && pwd)"
FICHIER="$DOSSIER/requete_mon_equipe.txt"
echo "⏳ J'attends : dans Chrome, clic droit sur la ligne 32607/ → Copy → Copy as cURL (5 min max)…"
for i in $(seq 1 300); do
  if pbpaste | head -c 200 | grep -q "^curl .*my-team"; then
    umask 077
    pbpaste > "$FICHIER"
    chmod 600 "$FICHIER"
    echo "✅ Requête enregistrée ($(wc -c < "$FICHIER" | tr -d ' ') octets)."
    # Envoie le cookie de session dans le coffre GitHub (version cloud), sans l'afficher
    if command -v gh >/dev/null; then
      sed -n 's/.*sessionid=\([^;'"'"'"]*\).*/sessionid=\1/p' "$FICHIER" | head -1 | tr -d '\n' \
        | gh secret set NBA_COOKIE -R hugotaubm/assistant-nba-fantasy && echo "✅ Cookie mis à jour sur GitHub."
    fi
    exit 0
  fi
  sleep 1
done
echo "❌ Rien reçu au bout de 5 min. Relance la commande et réessaie."
exit 1
