# Contribuer

Projet personnel, mono-utilisateur. Les corrections et suggestions sont bienvenues par issue ou pull request.

## Mise en place

Voir « Démarrer en local » dans le [README](README.md). Pour brancher les contrôles avant chaque commit :

```bash
pip install pre-commit && pre-commit install
```

## Règles

- **Langue** : code, commentaires, messages de commit et interface en français, comme la spécification.
- **Référence** : toute fonctionnalité renvoie à une exigence de la [spécification](docs/specification-serveur-aide-culinaire.md) (M-1, F-5, S-3…). Une divergence se discute d'abord dans une issue.
- **Le LLM n'écrit jamais** : aucune modification ne doit donner au moteur un outil d'écriture ou un shell. Toute écriture passe par `backend/app/propositions.py`, sur validation explicite.
- **`agent/CLAUDE.md` et le skill `recette-cook`** sont des copies mot pour mot du projet d'origine : ne pas les reformuler. Les ajouts du serveur vont dans `backend/app/consignes.py`.
- **Tests** : pas de test qui appelle le vrai CLI, GitHub ou Drive. Utiliser `MoteurFactice`, un dépôt nu local et un dossier comme destination rclone (voir `backend/tests/`).
- **Secrets** : jamais dans le dépôt ni dans les réponses de l'API.

## Avant d'ouvrir une pull request

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest
cd ../frontend && npm run lint && npm run check && npm test && npm run build
```

Un changement d'interface se vérifie aussi avec `npm run e2e` (voir le README).
