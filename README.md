# Aide Culinaire — serveur auto-hébergé

[![CI](https://github.com/MrLouix/Cooklang_server/actions/workflows/ci.yml/badge.svg)](https://github.com/MrLouix/Cooklang_server/actions/workflows/ci.yml)
[![Licence MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](LICENSE)

Un assistant pâtissier qui analyse tes recettes, propose des corrections chiffrées, puis écrit des fichiers [Cooklang](https://cooklang.org) (`.cook`) **après ton accord**. Les recettes sont versionnées dans Git, poussées vers GitHub et recopiées vers Google Drive pour l'appli Cook du téléphone.

Le moteur est le CLI Claude Code (`claude -p`) : pas de clé API, l'abonnement suffit. Deux autres moteurs peuvent le remplacer ou prendre le relais automatiquement quand son crédit est épuisé : l'API Anthropic, ou tout fournisseur compatible avec l'API OpenAI (OpenRouter, OpenAI, Mistral, un serveur local…). Le LLM n'a ni shell ni droit d'écriture ; toute écriture passe par l'API, sur validation.

- Spécification : [`docs/specification-serveur-aide-culinaire.md`](docs/specification-serveur-aide-culinaire.md)
- Plan de codage : [`docs/plan-de-codage.md`](docs/plan-de-codage.md)
- Mise en service et exploitation : [`docs/exploitation.md`](docs/exploitation.md)

## Ce que fait l'application

| Écran | Contenu |
| --- | --- |
| Discussions | Liste triée par activité, recherche dans les titres et les messages, archives |
| Chat | Réponses en streaming, pièces jointes, carte de proposition (aperçu, diff, Enregistrer / Demander une correction / Ignorer) |
| Recettes | Navigation par catégorie, recherche plein texte, historique Git, restauration, « Discuter de cette recette » |
| Paramètres | Unités, présentation, préférences alimentaires, textes par domaine — traduits en consignes à chaque tour |
| Base documentaire | Fiches de référence, documents (PDF, EPUB, Markdown), liens ; index plein texte |
| Système | Crédit consommé, mémoire, journal de synchronisation, état des composants |

## Architecture

```
PWA Svelte ──HTTP/SSE──▶ API FastAPI ──▶ claude -p (lecture seule : Read, Glob, Grep, Skill, WebSearch, WebFetch)
                            │
                            ├─▶ SQLite        discussions, messages, propositions, journal, index plein texte
                            ├─▶ recettes/     dépôt Git ──▶ GitHub ──▶ rclone ──▶ Google Drive ──▶ appli Cook
                            └─▶ agent/        dépôt Git : CLAUDE.md, skill, mémoire, paramètres, fiches
```

| Dossier | Rôle |
| --- | --- |
| `backend/` | API Python 3.12 (FastAPI, SQLite), moteur, synchronisation, tests |
| `frontend/` | PWA Svelte 5 (Vite), service worker, tests |
| `agent/` | Modèle du répertoire de travail du CLI : instructions du projet et skill `recette-cook`, copiés tels quels |
| `deploiement/` | Image Docker, Compose, sauvegarde |
| `docs/` | Spécification, plan, exploitation |

## Démarrer en local

Prérequis : Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 22, Git. Le mode démonstration ne demande ni CLI Claude ni rclone.

```bash
# 1. Interface
cd frontend && npm ci && npm run build

# 2. Dépendances du serveur (dont le parseur Cooklang, en Node)
cd ../backend && uv sync && (cd outils && npm ci)

# 3. Serveur en mode démonstration : réponses scénarisées, aucun crédit consommé
AC_RACINE=/tmp/aide-culinaire AC_MOTEUR=factice uv run python -m app
```

Ouvre <http://127.0.0.1:8000>. Écris « analyse ma brioche » pour voir une proposition, « modifie ma brioche » pour un diff.

Avec le vrai moteur : installe le CLI Claude Code, authentifie-le, puis lance sans `AC_MOTEUR=factice`. Le script `uv run python -m scripts.maquette_moteur --modele haiku` vérifie en quatre tours courts la reprise de session, les restrictions d'outils et le format des propositions, et affiche le coût.

Pour développer l'interface avec rechargement à chaud : `npm run dev` dans `frontend/` (l'API est relayée vers le port 8000).

## Configuration

Variables d'environnement, toutes préfixées `AC_` (modèle : [`deploiement/.env.exemple`](deploiement/.env.exemple)).

| Variable | Défaut | Rôle |
| --- | --- | --- |
| `AC_RACINE` | `/srv/aide-culinaire` | Dossier des données : `recettes/`, `agent/`, `data/` |
| `AC_MOTEUR` | `claude` | `claude` (CLI réel, abonnement), `api` (clé API Anthropic), `openai` (tout fournisseur compatible OpenAI : OpenRouter, OpenAI, Mistral, serveur local…) ou `factice` (démonstration, tests) |
| `AC_MOTEUR_SECOURS` | vide | Moteur pris automatiquement quand le principal signale un crédit épuisé ; `api` ou `openai` |
| `AC_SECOURS_REESSAI_H` | `6` | Durée pendant laquelle le secours reste en service avant de réessayer le moteur principal, en heures |
| `AC_CLE_API_FICHIER` | `/run/secrets/anthropic_api_key` | Fichier de la clé API ; à défaut, `ANTHROPIC_API_KEY` |
| `AC_OPENAI_URL` | `https://openrouter.ai/api/v1` | Moteur `openai` : URL de base du fournisseur compatible OpenAI |
| `AC_OPENAI_MODELES` | vide | Modèles proposés : `nom=identifiant` ou identifiant seul, séparés par des virgules ; le premier est le défaut |
| `AC_OPENAI_CLE_FICHIER` | `/run/secrets/openai_api_key` | Fichier de la clé ; à défaut, `OPENAI_API_KEY` |
| `AC_OPENAI_TARIFS` | vide | `identifiant=entrée/sortie` en $ par million de jetons, pour estimer le coût |
| `AC_OPENAI_CORPS_EXTRA` | vide | JSON ajouté tel quel au corps de chaque requête (options propres au fournisseur) |
| `AC_OPENAI_VISION` | `1` | `0` si le modèle ne lit pas les images |
| `AC_OPENAI_MAX_TOKENS` | `0` | Longueur maximale d'une réponse ; `0` = défaut du fournisseur |
| `AC_API_EFFORT` | vide | Niveau d'effort du moteur API (`low` à `max`) ; vide = défaut du modèle |
| `AC_MODELE_DEFAUT` | `sonnet` | Modèle des nouvelles discussions |
| `AC_DELAI_TOUR` | `300` | Délai maximal d'un tour, en secondes |
| `AC_CREDIT_MENSUEL` | `20` | Plafond affiché dans Système, en dollars |
| `AC_TITRE_AUTO` | `1` | Titre généré après le premier échange (un tour court sur `AC_MODELE_TITRE`) |
| `AC_GIT_REMOTE_RECETTES` | vide | Dépôt distant des recettes ; vide = pas de push |
| `AC_GIT_REMOTE_AGENT` | vide | Dépôt distant de `agent/` (mémoire, paramètres, fiches) |
| `AC_RCLONE_DEST` | vide | Destination rclone du miroir, par exemple `gdrive:WORKSPACE/Recettes` |
| `AC_INTERVALLE_CONTROLE` | `600` | Période du contrôle des modifications faites côté Drive, en secondes |
| `AC_MOT_DE_PASSE` | vide | Mot de passe optionnel, en plus du VPN |
| `AC_JETON_FICHIER` | `/run/secrets/claude_token` | Jeton longue durée du CLI (`claude setup-token`) |
| `AC_HOTE`, `AC_PORT` | `127.0.0.1`, `8000` | Adresse d'écoute |

## Contrôles

```bash
# Backend
cd backend
uv run ruff check . && uv run ruff format --check .
uv run pytest

# Frontend
cd frontend
npm run lint      # ESLint + Prettier
npm run check     # svelte-check
npm test          # tests unitaires (Vitest)
npm run build

# Parcours de bout en bout dans un navigateur (serveur lancé en mode démonstration sur le port 8765)
AC_URL=http://127.0.0.1:8765 npm run e2e
```

Les mêmes contrôles tournent en CI à chaque push et à chaque pull request, et peuvent être branchés en local avec [pre-commit](https://pre-commit.com) : `pre-commit install`.

Aucun test automatisé ne consomme de crédit ni ne touche à GitHub ou à Drive : le moteur est remplacé par une implémentation factice, le distant Git par un dépôt nu local, Drive par un dossier.

## État

La v1 de la spécification est codée, hors illustrations (prévues en v2). Restent à faire sur la machine cible, faute de l'avoir sous la main : construire l'image Docker, relever le crédit mensuel réel, brancher GitHub et Drive, tester l'appli Cook sur le téléphone. La marche à suivre est dans [`docs/exploitation.md`](docs/exploitation.md).

## Licence

[MIT](LICENSE). Les fichiers de `agent/` sont les instructions personnelles du projet d'origine.
