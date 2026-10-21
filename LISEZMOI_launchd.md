# Version cloud (GitHub) — celle utilisée depuis le 21/10/2026

L'assistant tourne sur GitHub Actions (dépôt hugotaubm/assistant-nba-fantasy), même Mac éteint :
- **Page** : https://hugotaubm.github.io/assistant-nba-fantasy/ (ajoute-la à l'écran d'accueil de l'iPhone via Safari → Partager).
- **Planificateur** : `.github/workflows/assistant.yml` lance le planificateur toutes les 10 min ; calcul complet 2 h 30 à 1 h avant chaque deadline, contrôle 50 à 15 min avant. Chaque calcul est enregistré dans le dépôt (dossiers `rapport/` et `docs/`).
- **Recalculer** : bouton en bas de la page → « Run workflow » (ou appli GitHub → Actions → assistant → Run workflow, « Recalculer maintenant » coché).
- **Veilleur** : la tâche `assistant` tourne ~5 h 50 puis se relance elle-même (le cron toutes les 3 h ne sert qu’à la redémarrer si besoin).
- **Secrets** (Settings → Secrets and variables → Actions) : `NTFY_SUJET` (sujet ntfy) et, si tu le veux, `NBA_COOKIE`. Pour le cookie : copie sa valeur (voir étape « cookie » ci-dessous), puis dans le Terminal :
  `pbpaste | gh secret set NBA_COOKIE -R hugotaubm/assistant-nba-fantasy`
- Sur le Mac, `config_local.json` garde le sujet ntfy (jamais envoyé sur GitHub). Les tâches launchd du Mac sont désinstallées ; `bash installer.sh` les remet si besoin (attention aux notifications en double).

---

# Lancer l'assistant automatiquement (Mac)

## Les fichiers
- `lancer_assistant.sh` : lance `python3 assistant.py --pas-de-navigateur` une fois et enregistre le résultat dans `rapport/dernier_rapport.txt` (un verrou empêche deux calculs en même temps).
- `planificateur.py` : lancé toutes les 10 min, il décide quand calculer (voir plus bas) et envoie les notifications iPhone.
- `serveur.py` : la page http://localhost:8765 (et https://hugos-macbook-pro.tail81f2b6.ts.net sur l'iPhone, via Tailscale) avec le bouton « Recalculer ».
- `installer.sh` : crée les deux tâches launchd (planificateur + serveur) et les démarre.
- `desinstaller.sh` : supprime les tâches automatiques.
- `maj_priors.py` / `maj_b2b.py` : recalculent les projections et l'effet des back-to-backs.

## Installation
1. Ouvre le Terminal (Cmd + Espace, tape « Terminal », Entrée).
2. Tape `cd ~/assistant-nba-fantasy` puis Entrée.
3. Tape `bash installer.sh` puis Entrée.

## Quand les calculs ont lieu
Pour chaque deadline :
- **entre 1 h 40 et 1 h 10 avant** : calcul complet → notification « à faire » (titulaires, transfert, capitaine) ;
- **entre 30 et 15 min avant** : calcul de contrôle → notification seulement si le conseil a changé, ou en priorité haute si ton équipe sur le site n'est pas en ordre ;
- si le Mac se réveille trop tard (moins de 15 min avant), le calcul est sauté (noté dans `rapport/planificateur.log`) ;
- un calcul de secours vers midi s'il n'y en a pas eu depuis 12 h.

Tester sans rien lancer : `python3 planificateur.py --simuler` (ajoute `--maintenant 2026-10-21T21:00:00Z` pour une autre heure).

**Indispensable** : Réglages Système → Batterie → Options → « Empêcher la suspension automatique sur secteur lorsque l'écran est éteint », et laisse le Mac branché.

## Notifications iPhone (ntfy)
1. Installe l'appli **ntfy** depuis l'App Store sur l'iPhone et autorise les notifications.
2. Dans l'appli : **+** → « Topic name » = la valeur de `ntfy_sujet` dans `config.json` → **Subscribe** (serveur par défaut ntfy.sh).
3. Test : `python3 planificateur.py --test-notif`.

Le nom du sujet est long et aléatoire : garde-le pour toi (quiconque le connaît peut lire les notifications).

## Cookie (étape « cookie ») : voir tes titulaires avant la deadline
Sans cookie, l'assistant ne voit ton équipe qu'après chaque deadline (pages publiques). Avec le cookie, il voit tes titulaires, ton capitaine et tes transferts en direct, et peut t'alerter si quelque chose ne va pas.
Le cookie est un secret : ne le colle **jamais** dans un chat ou un message.

1. Dans **Safari** sur le Mac : Réglages → Avancées → coche « Afficher les fonctionnalités pour les développeurs web ».
2. Ouvre https://nbafantasy.nba.com, connecte-toi, puis va sur la page de ton équipe (« Pick Team »).
3. Menu **Développement → Afficher l'inspecteur web** → onglet **Réseau**, puis recharge la page (Cmd + R).
4. Dans la liste, clique sur la requête **32607** (adresse …/api/my-team/32607/). Dans « En-têtes » → « Requête », trouve la ligne **Cookie** et copie toute sa valeur (clic droit → Copier la valeur, ou sélectionne et Cmd + C).
5. Dans le Terminal, colle cette ligne puis Entrée (elle prend le presse-papiers sans l'afficher) :
   `pbpaste > ~/assistant-nba-fantasy/secret_cookie.txt && chmod 600 ~/assistant-nba-fantasy/secret_cookie.txt`
6. Clique sur « Recalculer » : la ligne « Équipe lue depuis » doit indiquer « my-team (connecté, à jour en direct) ».

Si le rapport affiche « Cookie expiré », refais les étapes 2 à 5. Pour arrêter d'utiliser le cookie : supprime `secret_cookie.txt`.

## Vérifier
- `launchctl list | grep fr.assistant` : `fr.assistant.planif` et `fr.assistant.serveur` doivent apparaître.
- En cas de problème : `rapport/planificateur.log`, `rapport/dernier_rapport.txt` et `rapport/launchd.log`.

## Bon à savoir
- launchd suit l'heure du Mac : il doit être réglé sur Paris (Réglages Système → Général → Date et heure).
- Évite de mettre le dossier dans Documents, Bureau ou Téléchargements : macOS y bloque souvent les tâches automatiques (« Operation not permitted »).
