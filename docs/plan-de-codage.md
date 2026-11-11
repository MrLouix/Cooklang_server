# Plan de codage — Serveur Aide Culinaire

Version du 10 novembre 2026 · d'après `specification-serveur-aide-culinaire.md` (même dossier)

Ce plan découpe la spécification en phases livrables, dans l'ordre des jalons de la section 13. Chaque phase indique ce qu'on code, les exigences couvertes et le critère qui permet de passer à la suivante. Les identifiants (M-1, F-5, S-3…) renvoient à la spécification.

## 1. Principes de réalisation

- **Le risque d'abord.** La phase 1 est une maquette jetable du moteur CLI : si le coût par tour ou l'authentification ne tiennent pas, on le sait avant d'avoir écrit l'application.
- **Tout ce qui est fragile derrière une interface.** Le CLI Claude, Git, rclone et le parseur Cooklang sont chacun enveloppés dans un module avec une implémentation factice pour les tests. Aucun test automatisé ne consomme de crédit ni ne touche à Drive.
- **Le tour de conversation est une tâche de fond**, détachée de la requête HTTP : c'est ce qui rend possibles la file d'attente (M-5), le délai maximal (M-7) et la reprise après mise en veille (P-3).
- **Une seule voie d'écriture.** Recettes, mémoire et fiches passent par le même pipeline `proposition → validation → écriture → commit → synchro`.
- **Tranches verticales.** Chaque phase livre du back, du front et des tests ; l'application est utilisable dès la fin de la phase 2.

## 2. Décisions de conception à valider avant de coder

La spécification laisse ces points ouverts ou ambigus. Le plan retient une proposition pour chacun ; les cinq premiers conditionnent le schéma et méritent ton accord avant la phase 2.

| # | Sujet | Constat | Proposition retenue par le plan |
| --- | --- | --- | --- |
| C-1 | Format de la « proposition structurée » (F-5) | Non défini | Bloc clôturé ` ```proposition ` dans la réponse : un en-tête `cible` / `type` / `chemin`, une ligne `---`, puis le contenu complet. L'API l'extrait à la fin du tour ; la PWA le remplace par une carte. |
| C-2 | Où donner cette consigne sans toucher à `CLAUDE.md` (F-1, F-2 : copies « mot pour mot ») | Le skill `recette-cook` actuel suppose que l'assistant écrit lui-même le fichier | Consigne ajoutée par `--append-system-prompt` : « tu n'as pas d'outil d'écriture ; écrire = émettre un bloc `proposition` ». `CLAUDE.md` et le skill restent identiques à l'original. |
| C-3 | Dépôt Git de `parametres.json`, des fiches et des liens (PA-1, B-9) | « Versionnés dans Git », mais le dépôt `recettes/` est miroité vers le dossier que lit l'appli Cook (S-2) | Second dépôt Git local sur `agent/` (mémoire, paramètres, fiches, liste des liens), poussé vers un second dépôt GitHub privé, jamais vers Drive. `references/documents/` y est ignoré (B-9). |
| C-4 | Propositions de mémoire et de fiches (F-12, B-8) | La table `propositions` ne distingue pas la cible | Colonne `cible` (`recette`, `memoire`, `fiche`) ; le pipeline choisit le dépôt et le validateur selon la cible. |
| C-5 | Points d'API manquants | Pièces jointes (F-4), historique et restauration (F-8), dupliquer (D-5), reprise de flux (P-3), confirmation d'exclusion (PA-5), santé | Ajoutés en section 5 de ce plan. |
| C-6 | Titre automatique (D-2) | Un tour CLI dédié consomme du crédit | Titre provisoire = début du premier message ; titre généré par un tour Haiku sans outils, désactivable dans Système. |
| C-7 | Détection du domaine d'une discussion (PA-4) | Non définie | Champ `domaine` sur la discussion, déduit par mots-clés au premier message et de la catégorie de la recette en contexte, modifiable dans l'en-tête du chat. Pas d'appel LLM. |
| C-8 | Correspondance ingrédients ↔ exclusions (PA-5) | « Porc » ne figure pas tel quel dans un .cook | Table de synonymes versionnée (`porc` → lard, jambon, lardons, saucisse…), éditable ; comparaison sur les noms d'ingrédients normalisés issus du parseur. Filet de sécurité, pas garantie. |
| C-9 | Coût de `rclone check` avant chaque écriture (S-3) face aux 2 minutes de S-6 | Deux exigences en tension | Contrôle limité aux fichiers modifiés (`rclone check --combined`), plus un contrôle périodique toutes les 10 minutes pour que l'écriture trouve en général un état propre. À mesurer en phase 4. |
| C-10 | Dépôt du code | Ce dépôt ne contient que la spécification | Le code de l'application vit ici ; les recettes et `agent/` sont des dépôts de données distincts, jamais mêlés au code. |

**À vérifier en maquette, pas sur documentation** : nom exact des options du CLI à la version figée (`--allowedTools`, `--disallowedTools`, `--append-system-prompt`, `--resume`), restriction de `Read` à certains dossiers par les règles de permission, variable d'environnement du jeton `setup-token`, format des événements `stream-json`, message d'erreur d'une session introuvable et d'un quota épuisé, commande de validation de CookCLI.

## 3. Organisation du dépôt de code

```
backend/
  app/
    main.py              # FastAPI, montage des routes et du front statique
    config.py            # chemins, modèle par défaut, délais (variables d'environnement)
    db.py, migrations/   # SQLite (WAL), migrations SQL numérotées
    moteur/
      base.py            # interface Engine + types d'événements (M-1)
      claude_cli.py      # sous-processus claude -p, lecture stream-json
      factice.py         # rejoue des enregistrements stream-json (tests, démo)
    tours.py             # file d'attente, tâche de fond, délai, diffusion SSE
    propositions.py      # extraction des blocs, états, pipeline de validation
    cooklang.py          # validation et extraction des ingrédients
    depots.py            # opérations Git (recettes, agent)
    synchro.py           # push, rclone, divergence, conflits, journal
    parametres/          # schéma déclaratif, génération de parametres.md
    references/          # import, conversion, FTS5, fiches, liens
    routes/              # un fichier par ressource de l'API
  tests/
frontend/                # Svelte + Vite, build statique, service worker
deploiement/
  Dockerfile, compose.yaml, sauvegarde.sh, README-exploitation.md
agent-modele/            # squelette de agent/ : CLAUDE.md, skill, mémoire initiale (F-13)
docs/
```

Outils : `uv` pour Python, `ruff`, `pytest` ; `pnpm`, `vitest` et Playwright côté front ; une CI GitHub Actions qui lance lint, tests et build à chaque push.

## 4. Phases

### Phase 0 — Socle

- Squelette `backend/` et `frontend/`, CI, `Dockerfile` (Python 3.12, Node pour le CLI Claude à version figée, git, rclone, CookCLI), `compose.yaml` avec les volumes `recettes/`, `agent/`, `data/`, `~/.claude`, secrets.
- `GET /api/sante` : versions du CLI, de rclone, de CookCLI, état de la base.
- Migrations SQLite et script d'initialisation de `agent/` à partir de `agent-modele/`.

**Sortie** : `docker compose up -d` démarre, la page d'accueil vide s'affiche, la CI est verte.

### Phase 1 — Maquette du moteur (jalon 1)

Script autonome, sans API ni base.

- Authentification par `claude setup-token` dans le conteneur, jeton en volume, droits 600 (M-4).
- Un tour, puis un second avec `--resume` ; capture brute des événements `stream-json` dans `backend/tests/enregistrements/` (ils alimenteront le moteur factice).
- Vérification des outils : `Read`, `Glob`, `Grep`, `Skill`, `WebSearch`, `WebFetch` autorisés ; `Write`, `Edit`, `Bash` refusés ; `Read` hors de `recettes/`, `memoire/` et `references/` refusé (M-3, B-4).
- Test du bloc `proposition` (C-1, C-2) sur une vraie recette de brioche avec le `CLAUDE.md` et le skill d'origine.
- Mesures : coût et durée d'une analyse complète, d'un tour court, d'un tour avec recherche web ; relevé du crédit mensuel réel du compte.
- Provocation des erreurs : session inconnue, jeton invalide, dépassement de délai.

**Sortie** : note de décision dans `docs/maquette-moteur.md` avec le nombre d'analyses complètes possibles par mois. Si le chiffre est insuffisant, on code l'implémentation par clé API (M-1) dès la phase 2 au lieu de la laisser en secours.

### Phase 2 — Chat et discussions (jalon 2)

Back :

- `Engine.run(session, message)` produisant des événements typés : `texte`, `outil`, `fin` (coût, identifiant de session), `erreur` (quota, authentification, session introuvable, délai). Implémentations `claude_cli` et `factice`.
- `tours.py` : file à un seul exécutant (M-5), délai de 5 minutes avec arrêt du sous-processus (M-7), écriture progressive du message en base, diffusion à des abonnés SSE. Le tour continue si le client se déconnecte (P-3).
- D-4 : sur l'erreur « session introuvable », nouvelle session et réinjection de l'historique stocké en préambule du message, sans intervention.
- Routes discussions et messages ; recherche par titre et contenu (FTS5 sur `messages`) ; renommer, archiver, supprimer, dupliquer à partir d'un message (D-1, D-5).
- Titre automatique (C-6), modèle par discussion.
- Cumul mensuel des coûts et `GET /api/quota` (M-6).

Front :

- Écrans Discussions et Chat, mobile d'abord, thèmes clair et sombre (P-1).
- Rendu Markdown en streaming ; tableaux à défilement horizontal avec première colonne figée (F-3).
- Indicateur des appels d'outils, liens des sources (F-14), bandeau de quota et messages d'erreur du moteur.
- Reprise : au retour au premier plan, rechargement du message depuis la base puis réabonnement au flux.

**Sortie** : le critère « une discussion de la veille se rouvre et se poursuit, y compris après redémarrage du serveur » passe, d'abord avec le moteur factice en test automatisé, puis à la main avec le CLI.

### Phase 3 — Propositions, .cook et Git (jalon 3)

- Extraction des blocs `proposition` en fin de tour, enregistrement en base à l'état « en attente » ; contrôle du chemin (catégorie existante ou nouvelle, pas de `..`, extension `.cook`).
- `cooklang.py` : validation par CookCLI, extraction des ingrédients en JSON (F-7). Sur échec, la proposition reste en attente et l'erreur part à l'assistant comme message suivant.
- Pipeline de validation, sous verrou : relecture de l'état du fichier cible, refus si le fichier a changé depuis la proposition, écriture, commit dont le message cite l'identifiant et le titre de la discussion (F-8). La synchro se branchera ici en phase 4.
- `depots.py` : historique d'un fichier, contenu d'une version, restauration (nouveau commit, jamais de réécriture d'historique).
- Routes recettes : arborescence, contenu, recherche plein texte, historique ; discussions liées à une recette par jointure sur `propositions` (D-6).
- Front : carte de proposition avec aperçu Cooklang et diff ligne à ligne, actions Enregistrer / Demander une correction (pré-remplit la saisie) / Ignorer (F-6) ; écran Recettes avec historique, restauration et « Discuter de cette recette » (F-10).
- Pièces jointes : envoi d'images et de texte, stockage dans `data/pieces/`, transmises au CLI par chemin en lecture seule (F-4).

**Sortie** : « aucun fichier n'est écrit sans appui sur Enregistrer » est couvert par un test qui vérifie que le dépôt ne change pas tant que la route de validation n'est pas appelée ; une modification affiche un diff correct ; un .cook invalide est refusé.

### Phase 4 — Synchronisation et bascule (jalon 4)

- Après commit : `git push` avec la clé de déploiement (S-1), puis `rclone sync` hors `.git` vers `Mon Drive/WORKSPACE/Recettes`, sans conversion en Google Doc (S-2). Reprises automatiques avec attente croissante ; un échec n'annule jamais le commit local.
- Avant écriture : contrôle de divergence (S-3). Fichier modifié côté Drive et différent de la cible → import et commit « modification externe ». Fichier modifié côté Drive et identique à la cible → les deux versions sont gardées, `<Nom>.conflit-<date>.cook`, signalement dans la PWA (S-4).
- Table `synchro`, écran Système avec journal et bouton « Resynchroniser » (S-5).
- Script de bascule : import unique du dossier Drive dans le dépôt, commit initial, vérification que chaque .cook passe le parseur, rapport des fichiers en anomalie.
- Essais sur le téléphone : option A, puis C (Syncthing) si la lecture hors ligne échoue ; résultat consigné dans la documentation d'exploitation.
- Réseau : écoute sur l'interface Tailscale seule, `tailscale serve` pour le HTTPS (X-1), mot de passe optionnel avec cookie de session (X-2).

**Sortie** : une recette enregistrée est dans GitHub, dans Drive et dans l'appli Cook en moins de 2 minutes (S-6) ; une modification faite à la main dans Drive est reprise sans perte ; le service ne répond pas hors VPN.

### Phase 5 — Mémoire, Paramètres, hors ligne (jalon 5)

- Mémoire : `GET` / `PUT /api/memoire/{fichier}`, éditeur dans la PWA, propositions de cible `memoire` (F-11, F-12), contenu initial (F-13), commit dans le dépôt `agent/` (C-3).
- Paramètres : schéma déclaratif unique (type de contrôle, valeurs, défaut, texte de consigne par valeur) servi par `GET /api/parametres` ; la PWA construit le formulaire à partir du schéma (PA-8).
- Génération de `memoire/parametres.md` à chaque `PUT`, effet dès le tour suivant (PA-1, PA-2) ; règle de priorité PA-3 et rappel « .cook toujours en grammes » (PA-6) écrits en tête du fichier généré.
- Textes libres par domaine, ajout et suppression de domaine ; injection selon le domaine de la discussion (PA-4, C-7).
- Contrôle des exclusions strictes à la validation : la route répond « confirmation requise » avec la liste des ingrédients en cause, et n'écrit qu'avec le paramètre de confirmation (PA-5, C-8).
- Retour aux valeurs par défaut (PA-7).
- Hors ligne : manifeste et service worker, cache des recettes et des discussions déjà ouvertes, saisie désactivée avec indicateur d'état (P-1, P-2).

**Sortie** : les deux premiers critères de la section 12 passent (réglage « Œufs », avertissement d'exclusion), ainsi que « une préférence ajoutée à la mémoire est appliquée dans une nouvelle discussion ».

### Phase 6 — Base documentaire (jalon 6)

- Table `sources` et routes de B-10 ; écran Base documentaire avec état d'indexation (B-1).
- Import : PDF, EPUB, Markdown → Markdown avec repères de page, OCR des pages scannées, original conservé (B-2). Traitement en tâche de fond, état visible.
- Liens : vérification que l'URL répond avant enregistrement, mode « copie locale » ou « à la demande », contrôle périodique des liens morts (B-3, B-11).
- Index FTS5 par passage (titre, page, texte) et route de recherche (B-4).
- Fiches de référence : gabarit à champs fixes, éditeur, validation du gabarit, propositions de cible `fiche` (B-8).
- Consignes générées dans `memoire/references.md` : liste des fiches et des sources actives, domaines prioritaires, ordre B-5, règle de citation et mention « non sourcé » (B-6), règle de contradiction (B-7).
- Rédaction des cinq premières fiches avec toi (point ouvert de la section 12).

**Sortie** : une analyse de brioche cite la fiche « brioche » pour l'hydratation et la température à cœur, et marque « non sourcé » ce qui manque.

### Phase 7 — Exploitation et recette finale

- Sauvegarde quotidienne de `data/`, `agent/` et des sessions CLI vers le NAS, avec un essai de restauration complet (X-5, D-7).
- Vérification que les routes ne renvoient aucun secret (X-4) ; redémarrage automatique, journaux, procédure de mise à jour du CLI et de renouvellement du jeton (X-6).
- Déroulé des six critères d'acceptation v1, à la main, sur le mini-PC et le téléphone.

### Phase 8 — Illustrations (v2)

Hors v1. Le pipeline de la phase 3 accepte déjà des fichiers non .cook dans le dépôt recettes ; I-1 à I-4 s'y brancheront avec une cible `image`.

## 5. Données et API : compléments à la spécification

**Tables** (en plus des champs de la section 8)

| Table | Ajouts |
| --- | --- |
| `discussions` | `domaine`, `recette_contexte`, `titre_auto` |
| `messages` | `état` (en cours, terminé, erreur), `outils` (JSON), `durée_ms` |
| `propositions` | `cible`, `sha_base` (version du fichier au moment de la proposition), `erreur_validation` |
| `tours` | id, discussion_id, état, démarré_le, terminé_le — file d'attente et reprise |
| `sources` | conforme à B-10 |
| `passages` (FTS5) | source_id, page, texte |
| `messages_fts` (FTS5) | recherche dans les discussions |

**Routes ajoutées**

| Méthode et chemin | Fonction |
| --- | --- |
| `GET /api/sante` | État des composants |
| `GET /api/discussions/{id}/flux` | Se réabonner au tour en cours (P-3) |
| `POST /api/discussions/{id}/dupliquer` | Dupliquer à partir d'un message (D-5) |
| `POST /api/pieces` | Déposer une pièce jointe (F-4) |
| `GET /api/recettes/{chemin}/historique`, `POST …/restaurer` | Versions Git (F-8) |
| `GET /api/recettes/{chemin}/discussions` | Discussions liées (D-6) |
| `POST /api/propositions/{id}/valider?confirmer_exclusions=1` | Lever l'avertissement PA-5 |
| `GET /api/parametres/schema` | Schéma déclaratif (PA-8) |

## 6. Tests

| Niveau | Contenu | Dépendances réelles |
| --- | --- | --- |
| Unitaires | Extraction des propositions, génération de `parametres.md`, correspondance des exclusions, lecture du `stream-json`, contrôle des chemins | Aucune |
| Intégration | API complète avec moteur factice, dépôts Git temporaires, « distant » rclone local sur disque | Git, rclone, CookCLI |
| Bout en bout | Playwright sur la PWA avec moteur factice : envoyer, valider, voir le diff, rouvrir, hors ligne | Aucune externe |
| Fumée manuelle | Un tour réel par phase avec le CLI, check-list des critères d'acceptation | CLI, Drive, téléphone |

Cas à ne pas oublier : déconnexion du client en plein tour, deux messages envoyés coup sur coup, redémarrage du serveur pendant un tour, délai dépassé, fichier cible modifié entre proposition et validation, push refusé, Drive injoignable, nom de recette avec accents et espaces.

## 7. Traçabilité

| Exigences | Phase |
| --- | --- |
| M-1 à M-4 | 1, puis 2 |
| M-5 à M-7, F-3, F-14, D-1 à D-5, P-1 (base), P-3 | 2 |
| F-4 à F-10, F-15, D-6 | 3 |
| S-1 à S-6, X-1, X-2, bascule | 4 |
| F-11 à F-13, PA-1 à PA-8, P-2 | 5 |
| B-1 à B-11 | 6 |
| X-3 à X-6, D-7, critères v1 | 7 |
| F-1, F-2 | 0 (copie), 1 (vérification) |
| I-1 à I-4 | 8 (v2) |

## 8. Ce dont j'ai besoin de toi

1. Ton accord, ou tes corrections, sur C-1 à C-5 avant la phase 2.
2. Le texte exact des instructions du projet claude.ai et le skill `recette-cook`, à déposer dans `agent-modele/`.
3. Le relevé du crédit mensuel `claude -p` de ton compte, au début de la phase 1.
4. Le mini-PC avec Docker et Tailscale, la clé de déploiement GitHub et la configuration rclone de ton compte Drive, pour la phase 4.

## 9. Écarts constatés à la réalisation

Le plan ci-dessus a été suivi ; ces points diffèrent de ce qu'il annonçait.

| Sujet | Plan | Réalisé | Raison |
| --- | --- | --- | --- |
| Modèle de `agent/` | `agent-modele/` | `agent/`, à la racine du dépôt | C'est là que les instructions et le skill ont été déposés |
| Validation Cooklang | CookCLI | Paquet npm officiel `@cooklang/cooklang` (cooklang-rs en WASM) | C'est le parseur que cite le skill ; Node est déjà dans l'image pour le CLI. Tout avertissement du parseur est bloquant, comme le demande le skill |
| Pièces jointes | `data/pieces/` | `agent/pieces/` (ignoré par Git) | L'outil `Read` du CLI est borné à son répertoire de travail |
| Table `tours` | Table dédiée | État porté par `messages.etat`, file en mémoire | Un tour interrompu ne reprend pas : il est marqué en erreur au redémarrage |
| Bloc `proposition` dans les messages | Conservé tel quel | Remplacé en base par un marqueur `[[proposition:ID]]` | La PWA affiche une carte sans réanalyser le texte ; le bloc est reconstitué quand l'historique est réinjecté |
| Textes de domaine (PA-4) | Injectés selon le domaine | Idem, sauf « Matériel » et « Forme des réponses », toujours injectés | Ils s'appliquent à toute discussion |
| Conflit Drive (S-4) | — | La version du Drive est rangée dans `<Nom>.conflit-<date>.cook`, celle du serveur garde le nom d'origine | Une seule règle, sans question posée en plein enregistrement |
| Second moteur par clé API (M-1) | Codé si la maquette l'exige | Interface prête, implémentation non écrite | Le crédit réel n'est pas encore relevé |
| Migrations SQL numérotées | Prévues | Schéma unique créé au démarrage | Pas encore de version antérieure à migrer |
| Phase 8, illustrations | v2 | Non commencée | Hors périmètre v1 |
