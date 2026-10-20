#!/bin/bash
# Installe les deux tâches launchd :
#  - le planificateur (toutes les 10 min : calcule avant chaque deadline et notifie l'iPhone)
#  - le serveur local, toujours allumé sur http://localhost:8765
set -e

DOSSIER="$(cd "$(dirname "$0")" && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
PYTHON="$(command -v python3)"
UID_ACTUEL="$(id -u)"

if [ ! -f "$DOSSIER/assistant.py" ]; then
  echo "❌ assistant.py est introuvable dans $DOSSIER"
  echo "   Mets ces fichiers dans le même dossier que assistant.py."
  exit 1
fi
if [ -z "$PYTHON" ]; then
  echo "❌ python3 est introuvable."; exit 1
fi
case "$(readlink /etc/localtime)" in
  *Europe/Paris*) ;;
  *) echo "⚠️  Ton Mac n'est pas réglé sur l'heure de Paris : launchd utilise l'heure du Mac." ;;
esac

mkdir -p "$AGENTS" "$DOSSIER/rapport"
chmod +x "$DOSSIER/lancer_assistant.sh"

# Ancienne tâche à heures fixes (17h00 / 19h45), remplacée par le planificateur
if [ -f "$AGENTS/fr.assistant.calcul.plist" ]; then
  launchctl bootout "gui/$UID_ACTUEL" "$AGENTS/fr.assistant.calcul.plist" 2>/dev/null || true
  rm -f "$AGENTS/fr.assistant.calcul.plist"
fi

cat > "$AGENTS/fr.assistant.planif.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>fr.assistant.planif</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON</string>
    <string>$DOSSIER/planificateur.py</string>
  </array>
  <key>WorkingDirectory</key><string>$DOSSIER</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHON</key><string>$PYTHON</string>
    <key>PATH</key><string>$(dirname "$PYTHON"):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>StartInterval</key><integer>600</integer>
  <key>StandardOutPath</key><string>$DOSSIER/rapport/launchd.log</string>
  <key>StandardErrorPath</key><string>$DOSSIER/rapport/launchd.log</string>
</dict>
</plist>
PLIST

cat > "$AGENTS/fr.assistant.serveur.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>fr.assistant.serveur</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON</string>
    <string>$DOSSIER/serveur.py</string>
  </array>
  <key>WorkingDirectory</key><string>$DOSSIER</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$(dirname "$PYTHON"):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$DOSSIER/rapport/serveur.log</string>
  <key>StandardErrorPath</key><string>$DOSSIER/rapport/serveur.log</string>
</dict>
</plist>
PLIST

for nom in planif serveur; do
  fichier="$AGENTS/fr.assistant.$nom.plist"
  plutil -lint "$fichier" >/dev/null
  launchctl bootout "gui/$UID_ACTUEL" "$fichier" 2>/dev/null || true
  launchctl bootstrap "gui/$UID_ACTUEL" "$fichier"
done

echo "✅ Installation terminée."
echo "   Python utilisé : $PYTHON"
echo "   Calcul automatique : ~1 h 30 et ~20 min avant chaque deadline (vérifié toutes les 10 min)"
echo "   Ouvre http://localhost:8765 dans ton navigateur"
