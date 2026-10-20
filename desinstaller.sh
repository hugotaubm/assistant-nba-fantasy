#!/bin/bash
# Arrête et supprime les deux tâches launchd (tes fichiers restent en place).
for nom in calcul planif serveur; do
  fichier="$HOME/Library/LaunchAgents/fr.assistant.$nom.plist"
  launchctl bootout "gui/$(id -u)" "$fichier" 2>/dev/null
  rm -f "$fichier"
done
echo "✅ Tâches automatiques supprimées."
