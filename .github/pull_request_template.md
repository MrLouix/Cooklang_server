## Objet

<!-- Ce que change cette pull request, et pourquoi. Citer l'exigence de la spécification concernée (F-5, S-3…). -->

## Vérifications

- [ ] `uv run ruff check . && uv run ruff format --check . && uv run pytest` dans `backend/`
- [ ] `npm run lint && npm run check && npm test && npm run build` dans `frontend/`
- [ ] `npm run e2e` si l'interface change
- [ ] Aucun secret, aucun outil d'écriture donné au moteur

## Points d'attention

<!-- Ce qui n'a pas pu être testé, choix discutables, suites à prévoir. -->
