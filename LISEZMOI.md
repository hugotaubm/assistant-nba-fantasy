# Assistant NBA Fantasy — mode d'emploi

Chaque jour, le programme récupère les données de NBA Fantasy, projette les points de chaque joueur sur les Gamedays restants de la Gameweek, puis te propose :
- le cinq de départ du prochain Gameday,
- le meilleur jour pour ton capitaine,
- les transferts à faire, et quand les faire (« maintenant » ou « attends tel jour »),
- les alertes blessures.

Il affiche tout dans le terminal et ouvre un rapport `rapport.html` dans ton navigateur.

## 0. Version cloud (iPhone, Mac éteint)

L'assistant tourne sur GitHub Actions (`.github/workflows/assistant.yml`) et publie la page sur
https://hugotaubm.github.io/assistant-nba-fantasy/. À chaque passage, `planificateur.py` décide s'il
faut calculer (avant chaque deadline), envoie les notifications ntfy, et `publier.py` met la page à jour.

Les passages programmés de GitHub (`schedule`) sont souvent retardés ou sautés : ils n'arrivaient que
toutes les 2 à 5 h. Le workflow tourne donc en **veilleur** : une tâche reste active environ 5 h 40, lance
le planificateur toutes les 10 min, puis se relance elle-même. Le cron (`7 */3 * * *`) ne sert plus qu'à
redémarrer la chaîne si elle s'arrête. Aucun réglage extérieur n'est nécessaire.

Pour vérifier : onglet **Actions** du dépôt → une tâche « assistant » doit toujours être en cours
(icône jaune). Dans `rapport/planificateur.log`, chaque calcul est noté avec son heure.

**Bouton « Recalculer » sur iPhone : raccourci « Recalculer NBA »** (facultatif, appli Raccourcis)

Il faut une **clé d'accès GitHub** : un fine-grained token limité à ce dépôt, avec la permission
**Actions : Read and write**. Ne la mets jamais dans le dépôt ni dans un chat.

1. Action « Obtenir le contenu de l'URL » :
   - URL : `https://api.github.com/repos/hugotaubm/assistant-nba-fantasy/actions/workflows/assistant.yml/dispatches` ;
   - méthode POST ;
   - en-têtes : `Authorization: Bearer <clé>` et `Accept: application/vnd.github+json` ;
   - corps JSON : `ref` = `main` (forcer vaut true par défaut : calcul immédiat).
2. Action « Ouvrir les URL » : `https://hugotaubm.github.io/assistant-nba-fantasy/?attente=1`.

3. Dans `config.json`, mets `"raccourci_iphone": true`.

Sur iPhone, le bouton de la page lance alors ce raccourci. La page attend ensuite le nouveau rapport et se
recharge toute seule. Sans raccourci, ou sur ordinateur, le bouton ouvre la page GitHub du calcul :
connecte-toi à GitHub, puis « Run workflow » (case « Recalculer maintenant » cochée).

Le planificateur rattrape un passage en retard : tant qu'il reste au moins 8 min avant la deadline,
le calcul complet est fait.

## 1. Installation (une seule fois)

1. Installe Python 3.10 ou plus récent depuis python.org. Sous Windows, coche « Add Python to PATH » pendant l'installation.
2. Ouvre un terminal dans ce dossier, puis tape :
   ```
   pip install -r requirements.txt
   ```

## 2. Dire au programme quelle est ton équipe

Tu as deux options.

**Option A : automatique (recommandé).** Le programme lit ton équipe, ta banque, tes transferts restants et tes chips directement sur ton compte.

1. Connecte-toi sur nbafantasy.nba.com, puis ouvre la page « Mon équipe ».
2. Appuie sur **F12**, va dans l'onglet **Réseau** (Network) et recharge la page.
3. Dans la liste, clique sur la requête qui contient `my-team/` :
   - le **nombre** à la fin de son adresse est ton `id_equipe` ;
   - dans **En-têtes de requête** (Request Headers), copie toute la valeur de **Cookie**.
4. Colle ces deux valeurs dans `config.json` :
   ```json
   "id_equipe": 1234567,
   "cookie": "colle ici toute la valeur…",
   ```

⚠ Le cookie donne accès à ton compte. Ne partage jamais ce fichier. Il expire au bout d'un moment : si le programme indique « mon équipe = cache » ou une erreur 401/403, recopie-le.

**Option B : manuelle.** Laisse `id_equipe` et `cookie` à `null` et remplis :
- `equipe_manuelle` : tes 10 joueurs, avec le nom affiché dans le jeu (ex. `"T.Maxey"`) ;
- `banque` : ton argent restant en M$ ;
- `transferts_restants_cette_semaine` et `capitaine_deja_utilise_cette_semaine`.

Pense à mettre ce fichier à jour après chaque transfert.

## 3. Utilisation quotidienne

```
python assistant.py
```

Lance-le idéalement chaque jour, avant la deadline (30 min avant le premier match, souvent en fin d'après-midi ou en soirée, heure de Paris).

Options utiles :
- `--hors-ligne` : réutilise les dernières données téléchargées (dossier `donnees/`) ;
- `--pas-de-navigateur` : n'ouvre pas le rapport HTML.

### Lancement automatique (facultatif)

- **Windows** : ouvre le Planificateur de tâches, puis « Créer une tâche de base ». Choisis « Tous les jours » à 17h00, action « Démarrer un programme » :
  - Programme : `python`
  - Arguments : `assistant.py`
  - Commencer dans : le chemin de ce dossier
- **Mac / Linux** : tape `crontab -e`, puis ajoute la ligne :
  ```
  0 17 * * * cd /chemin/vers/le/dossier && python3 assistant.py
  ```

## 4. Réglages (config.json)

| Clé | Rôle |
|---|---|
| `joueurs_exclus` | Joueurs que l'assistant ne doit jamais te proposer d'acheter. |
| `joueurs_bloques` | Joueurs de ton équipe à ne jamais vendre. |
| `ajustements` | Ton avis sur un joueur. Ex. `{"T.Maxey": 1.1}` = +10 % sur sa projection, `0.8` = -20 %. |
| `poids_futur` | Importance donnée aux semaines suivantes face à la semaine en cours (1,5 par défaut). Augmente-le pour moins de transferts « opportunistes ». |
| `projection_min` | Les joueurs projetés en dessous de ce seuil (points/match) sont ignorés. |

## 5. Comment fonctionnent les projections

- **Avant-saison** : le fichier `priors.json` contient la production 2025-26 par match, mélangée avec le prix du joueur. Le prix pèse d'autant plus que le joueur a peu joué l'an dernier. Des ajustements de rôle y sont intégrés (ex. Maxey partage le ballon à Philadelphie, Tatum devient la première option à Boston).
- **En cours de saison** : la moyenne 2026-27 prend progressivement le relais. Après 8 matchs, elle pèse autant que la projection d'avant-saison. La forme récente compte pour 25 %.
- **Disponibilité** : la projection est multipliée par la probabilité de jouer donnée par le jeu. Un joueur annoncé « de retour le 23/10 » compte pour 0 avant cette date.
- **Optimiseur** : le programme teste toutes les options (aucun transfert, ou transferts avant chacun des Gamedays restants). Pour chacune, il calcule le meilleur cinq de chaque jour (2-3 BC, 2-3 FC), le capitaine et la valeur de l'équipe pour la semaine suivante. Un transfert payant (-100 pts) n'est proposé que s'il est rentable. À gain quasi égal, il préfère attendre, pour garder de la marge en cas de blessure.

## 6. Si quelque chose ne marche pas

L'API de NBA Fantasy n'est pas officielle : elle peut changer sans prévenir. Le calendrier vient de `/api/fixtures/` du jeu, ou à défaut du calendrier public de la NBA. Si un téléchargement échoue, le programme réutilise la dernière version enregistrée et te le signale en bas du rapport.

En cas d'erreur, copie le message affiché et envoie-le-moi.
