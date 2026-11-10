# Spécification — Serveur Aide Culinaire auto-hébergé

Version du 10 novembre 2026 · Louis

## 1. Objectif et périmètre

Le serveur reproduit chez toi le projet claude.ai « Aide Culinaire » : un assistant pâtissier qui analyse, propose, puis écrit des fichiers Cooklang (.cook) après ton accord, avec des discussions que tu peux rouvrir et des recettes disponibles dans l'appli Cook du smartphone.

**Périmètre v1**

- Chat avec l'assistant, avec les mêmes instructions de projet et le même skill `recette-cook`.
- Création et modification de fichiers .cook, uniquement après validation explicite.
- Liste des discussions, réouverture et poursuite.
- Mémoire persistante (matériel, préférences, habitudes).
- Recherche web pour importer ou comparer des recettes.
- Synchronisation Git + Google Drive vers le smartphone.
- Page Paramètres : unités, présentation et préférences alimentaires (section 11).
- Base documentaire de référence : documents locaux et liens web (section 12).

**Hors périmètre v1**

- Illustrations générées (prévu en v2, section 10).
- Multi-utilisateur.
- Reprise ou édition des recettes Bergamot, pilotage d'un navigateur.
- Reprise automatique de l'historique des discussions claude.ai existantes.

## 2. Décisions retenues

| Sujet | Décision | Conséquence |
| --- | --- | --- |
| Hébergement | Mini-PC dédié, allumé en permanence | Linux (Debian ou Ubuntu), Docker Compose |
| Interface | Web app dédiée, installable (PWA), mobile d'abord | Front et API à développer |
| Moteur LLM | Claude Code CLI, abonnement Pro | Pas de clé API ; quota spécifique au mode non interactif (section 4), montant à vérifier plus tard |
| Synchronisation | Git + Google Drive ; Syncthing en option | Git = source de vérité, Drive = miroir |
| Remote Git | Dépôt GitHub privé | Clé de déploiement dédiée, push après chaque commit |
| Smartphone | Android | Appli Cook sur dossier local ; dernier maillon à tester (section 7) |
| Transition | Bascule nette | À la mise en service, le projet claude.ai n'écrit plus dans le dossier Drive |
| Bergamot | Pas de reprise des recettes | Le serveur ne gère que les .cook du dépôt |
| Accès distant | VPN Tailscale ou WireGuard | Aucun port exposé sur internet |
| Utilisateurs | Toi seul | Une mémoire, pas de gestion de comptes |
| Stack | Libre | Python 3.12 + FastAPI + SQLite, front Svelte statique |

## 3. Architecture

Un seul service applicatif pilote le CLI Claude, écrit les fichiers lui-même et déclenche la synchronisation ; le LLM ne touche jamais directement au disque.

| Composant | Rôle | Technologie |
| --- | --- | --- |
| PWA | Chat, liste des discussions, aperçu et diff des recettes, édition de la mémoire | Svelte, build statique servi par l'API |
| API | Sessions, flux de réponse, validation et écriture des .cook, déclenchement de la synchro | FastAPI, SSE pour le streaming |
| Moteur | Exécute un tour de conversation | `claude -p` en sous-processus, sortie `stream-json` |
| Base | Index des discussions, messages, propositions, journal de synchro | SQLite (fichier unique) |
| Dépôt recettes | Source de vérité des .cook, classés par catégorie | Git, dépôt local + dépôt GitHub privé |
| Synchro | Miroir vers Google Drive, option Syncthing | rclone, tâche déclenchée après chaque commit |
| Réseau | Accès depuis le smartphone | Tailscale, HTTPS via `tailscale serve` |

**Arborescence sur le serveur**

- `/srv/aide-culinaire/recettes/` : dépôt Git des .cook (sous-dossiers de catégorie, identique au dossier Drive actuel).
- `/srv/aide-culinaire/agent/` : répertoire de travail du CLI, avec `CLAUDE.md` (instructions du projet, copiées telles quelles), `.claude/skills/recette-cook/SKILL.md` et `memoire/*.md`.
- `/srv/aide-culinaire/data/app.db` : base SQLite.

**Déroulé d'un tour**

1. La PWA envoie le message à l'API.
2. L'API lance le CLI dans `agent/`, en reprenant la session Claude de la discussion.
3. La réponse est diffusée en streaming vers la PWA et enregistrée en base.
4. Si la réponse contient une proposition de recette, la PWA affiche l'aperçu, le diff et un bouton « Enregistrer ».
5. Sur validation, l'API vérifie la syntaxe Cooklang, écrit le fichier, commite, pousse, puis lance la synchro Drive.

## 4. Moteur LLM : Claude Code CLI

Le choix « CLI + abonnement Pro » fonctionne, mais le mode non interactif ne consomme plus le quota de l'abonnement : c'est le principal risque du projet.

**Point de vigilance sur le quota**

- Depuis le 15 juin 2026, l'usage de `claude -p` et de l'Agent SDK sur un abonnement est décompté d'un crédit mensuel séparé, distinct des limites interactives ([documentation Claude Code](https://code.claude.com/docs/zh-CN/headless)).
- Des sources secondaires chiffrent ce crédit à 20 $ par mois pour Pro, avec un dépassement facturé au tarif API, optionnel et désactivé par défaut ([dev.to](https://dev.to/jovan_chan_9500711396d4e6/claude-code-agentic-api-rate-limits-in-june-2026-what-the-new-credit-separation-means-for-solo-1kal), [dev.to](https://dev.to/vainamoinen/what-anthropics-200-agent-sdk-credit-means-if-you-run-claude-p-in-production-ce2)). Montant à vérifier dans ton compte avant de démarrer.
- Les limites d'abonnement supposent un usage individuel ordinaire ; ton cas (un seul utilisateur, sur ta machine) y correspond.

**Exigences**

- M-1 : le moteur est isolé derrière une interface `Engine.run(session, message) -> flux d'événements`. Une seconde implémentation (clé API Anthropic ou OpenRouter) doit pouvoir le remplacer sans toucher au reste.
- M-2 : invocation par tour : `claude -p "<message>" --resume <id_session> --output-format stream-json --verbose --model <modèle>`, exécuté dans `agent/`.
- M-3 : outils autorisés en discussion : `Read`, `Glob`, `Grep` (sur `recettes/` et `memoire/`), `Skill`, `WebSearch`, `WebFetch`. Outils interdits : `Write`, `Edit`, `Bash`. L'écriture passe par l'API (section 5).
- M-4 : authentification du CLI par jeton longue durée (`claude setup-token`), stocké dans un volume, droits 600. À valider en maquette.
- M-5 : modèle par défaut Sonnet, sélectionnable par discussion ; un seul tour exécuté à la fois (file d'attente).
- M-6 : la PWA affiche le crédit consommé (coût estimé renvoyé par le CLI, cumulé par mois) et un message clair quand le quota est atteint.
- M-7 : délai maximal par tour : 5 minutes, puis arrêt du sous-processus et message d'erreur.

## 5. Exigences fonctionnelles

**Chat et instructions**

- F-1 : les instructions du projet claude.ai (rôle, équipement, pourcentages du boulanger, œufs, méthode d'analyse, format) sont reprises mot pour mot dans `CLAUDE.md`.
- F-2 : le skill `recette-cook` est copié tel quel dans `.claude/skills/` ; tout skill ajouté dans ce dossier est disponible sans redéploiement.
- F-3 : réponses en streaming, rendu Markdown avec tableaux lisibles sur écran de téléphone.
- F-4 : envoi de pièces jointes (photo d'une recette, capture d'écran, texte collé).

**Fichiers .cook**

- F-5 : l'assistant ne peut pas écrire. Il émet une proposition structurée : chemin cible (`<Catégorie>/<Nom>.cook`), type (création, modification, variante) et contenu complet.
- F-6 : la PWA affiche la proposition en aperçu Cooklang, avec diff ligne à ligne pour une modification, et trois actions : Enregistrer, Demander une correction, Ignorer.
- F-7 : à l'enregistrement, l'API valide la syntaxe avec un parseur Cooklang (CookCLI ou cooklang-rs). Un fichier invalide est refusé et l'erreur renvoyée à l'assistant.
- F-8 : chaque enregistrement produit un commit Git dont le message cite la discussion d'origine ; l'historique et la restauration d'une version sont accessibles depuis la PWA.
- F-9 : l'assistant lit les recettes existantes avant de proposer une modification ou une variante, et ne propose jamais d'écraser un fichier sans le signaler.
- F-10 : navigation dans les recettes par catégorie et recherche plein texte ; bouton « Discuter de cette recette » qui ouvre une discussion avec le fichier en contexte.

**Mémoire**

- F-11 : la mémoire est un ensemble de fichiers Markdown (`memoire/materiel.md`, `memoire/preferences.md`, `memoire/essais.md`) importés dans `CLAUDE.md`, donc présents à chaque tour.
- F-12 : l'assistant propose les ajouts de mémoire selon le même mécanisme que les recettes (proposition puis validation). Les fichiers sont éditables directement dans la PWA.
- F-13 : contenu initial : KitchenAid Classic 5K45SS, four peu précis, thermomètre à sonde, yaourtière express, préférence pour l'huile neutre plutôt que le beurre fondu, règle « proposition avant écriture ».

**Recherche web**

- F-14 : l'assistant peut chercher et lire des pages pour importer ou comparer une recette ; les sources sont citées avec lien dans la réponse.
- F-15 : une recette importée est convertie en Cooklang, en grammes, puis proposée comme toute autre (F-5), avec l'URL source dans les métadonnées du fichier.

## 6. Discussions

Chaque discussion de la PWA correspond à une session du CLI, reprise par son identifiant ; l'index et les messages sont conservés en base, indépendamment des fichiers internes du CLI.

- D-1 : liste des discussions triée par dernière activité, avec titre, date, modèle et recettes liées ; recherche par titre et par contenu.
- D-2 : le titre est généré après le premier échange et reste modifiable.
- D-3 : rouvrir une discussion réaffiche tout l'historique depuis la base, puis le tour suivant reprend la session CLI avec `--resume`.
- D-4 : si la session CLI est introuvable ou corrompue, l'API en recrée une et réinjecte l'historique stocké en base, de façon transparente.
- D-5 : actions par discussion : renommer, archiver, supprimer, dupliquer à partir d'un message.
- D-6 : depuis une recette, lister les discussions qui l'ont créée ou modifiée.
- D-7 : les fichiers de session du CLI (`~/.claude/projects/`) sont dans un volume persistant et inclus dans la sauvegarde.

Les discussions claude.ai existantes ne sont pas accessibles au CLI. Une reprise n'est possible que par l'export de données de ton compte, à importer en lecture seule ; ce n'est pas prévu en v1.

## 7. Synchronisation

Le dépôt Git du serveur est la source de vérité ; Google Drive en est un miroir, et le smartphone lit un dossier local tenu à jour.

**Ce que l'appli Cook accepte**

L'appli lit soit un dossier choisi sur le téléphone et synchronisé par un service tiers (Dropbox, Nextcloud, Syncthing…), soit Cook Cloud, le service hébergé de l'éditeur, payant pour les nouveaux comptes ([cooklang.org](https://cooklang.org/docs/getting-started)). Sur Android, l'appli sert à consulter : l'édition se fait ailleurs ([aide Android](https://platform.cooklang.org/help/android/troubleshooting)), ce qui convient ici puisque le serveur est le seul à écrire.

**Exigences**

- S-1 : après chaque commit, `git push` vers un dépôt GitHub privé.
- S-2 : après chaque push, `rclone sync` du dépôt (hors `.git`) vers `Mon Drive/WORKSPACE/Recettes`. Les .cook restent des fichiers texte brut, sans conversion en Google Doc.
- S-3 : avant chaque écriture, contrôle de divergence (`rclone check`). Un fichier modifié côté Drive (depuis le PC) est importé et commité comme « modification externe » avant toute écriture ; aucun écrasement silencieux.
- S-4 : en cas de conflit sur un même fichier, les deux versions sont conservées (`<Nom>.conflit-<date>.cook`) et signalées dans la PWA.
- S-5 : journal de synchro consultable (date, fichiers, résultat) et bouton « Resynchroniser ».
- S-6 : une recette enregistrée est visible sur le téléphone en moins de 2 minutes, réseau disponible.

**Bascule** : la transition est nette. À la mise en service, le dossier Drive actuel est importé une fois dans le dépôt Git (commit initial), puis le projet claude.ai cesse d'y écrire ; le serveur devient le seul à créer et modifier les .cook.

**Dernier maillon : du miroir au téléphone**

| Option | Principe | Limite |
| --- | --- | --- |
| A. Dossier Drive direct | Pointer l'appli Cook sur le dossier Drive via le sélecteur de fichiers Android | Fonctionnement hors ligne incertain, à tester en premier |
| B. Drive + appli de synchro de dossier | Une appli tierce télécharge le dossier Drive en local | Une appli de plus, délai de synchro |
| C. Syncthing serveur → téléphone | Dossier local synchronisé directement par le réseau Tailscale | Syncthing à installer des deux côtés ; aucun cloud |

Smartphone Android confirmé. Recommandation : tester A ; si la lecture hors ligne échoue, passer à C, qui supprime la dépendance à Drive pour le téléphone tout en gardant Drive comme sauvegarde.

## 8. PWA, API et données

Six écrans en v1 : Discussions, Chat, Recettes, Paramètres (section 11), Base documentaire (section 12), Système (mémoire, synchro, quota).

**PWA**

- P-1 : installable sur l'écran d'accueil, utilisable à une main, thème clair et sombre.
- P-2 : hors connexion, l'historique déjà chargé et les recettes restent consultables ; l'envoi de message est désactivé avec un indicateur d'état.
- P-3 : un message en cours de génération survit à la mise en veille du téléphone : au retour, la PWA récupère la réponse complète depuis la base.

**API**

| Méthode et chemin | Fonction |
| --- | --- |
| `GET /api/discussions` | Liste, recherche, filtre archivées |
| `POST /api/discussions` | Créer (option : recette en contexte) |
| `GET /api/discussions/{id}` | Historique complet |
| `POST /api/discussions/{id}/messages` | Envoyer un message, réponse en SSE |
| `PATCH` / `DELETE /api/discussions/{id}` | Renommer, archiver, supprimer |
| `GET /api/recettes` | Arborescence et recherche |
| `GET /api/recettes/{chemin}` | Contenu, historique Git |
| `POST /api/propositions/{id}/valider` | Valider, écrire, commiter, synchroniser |
| `POST /api/propositions/{id}/rejeter` | Ignorer |
| `GET` / `PUT /api/memoire/{fichier}` | Lire, modifier la mémoire |
| `GET /api/synchro`, `POST /api/synchro` | Journal, relance manuelle |
| `GET /api/quota` | Consommation du mois |

**Tables SQLite**

| Table | Champs principaux |
| --- | --- |
| `discussions` | id, titre, id_session_claude, modèle, créée_le, modifiée_le, archivée |
| `messages` | id, discussion_id, rôle, contenu, pièces_jointes, coût_estimé, créé_le |
| `propositions` | id, message_id, type, chemin, contenu, état (en attente, validée, rejetée), commit |
| `synchro` | id, date, cible, fichiers, résultat, erreur |

## 9. Sécurité et exploitation

Le service n'écoute que sur l'interface VPN et le LLM n'a ni shell ni droit d'écriture.

- X-1 : écoute sur l'interface Tailscale uniquement ; HTTPS fourni par `tailscale serve` (nécessaire à l'installation de la PWA). Aucune redirection de port sur la box.
- X-2 : mot de passe unique optionnel en plus du VPN, session par cookie.
- X-3 : le contenu des pages web lues par l'assistant est traité comme non fiable. L'absence d'outil d'écriture et de shell (M-3) et la validation manuelle (F-6) bornent l'effet d'une injection d'instructions.
- X-4 : secrets (jeton Claude, jeton rclone, clé de déploiement Git) hors dépôt, droits 600, jamais renvoyés par l'API.
- X-5 : sauvegarde quotidienne de `data/`, `agent/memoire/` et des sessions CLI vers le NAS ; les recettes sont déjà couvertes par Git et Drive.
- X-6 : déploiement par `docker compose up -d` ; redémarrage automatique ; journaux consultables ; mise à jour du CLI par reconstruction de l'image, version figée.

## 10. Illustrations (v2)

L'appli Cook affiche automatiquement une image qui porte le même nom que la recette dans le même dossier, par exemple `carbonara.cook` et `carbonara.jpg` ([cooklang.org](https://cooklang.org/blog/34-cooklang-mobile-app/)) ; l'illustration se réduit donc à déposer un fichier.

- I-1 : bouton « Illustrer » sur une recette ; le prompt est rédigé par l'assistant à partir du .cook, modifiable avant envoi.
- I-2 : génération par un modèle d'image via OpenRouter, fournisseur et modèle configurables ; clé API distincte, plafond de dépense mensuel.
- I-3 : 2 à 4 variantes proposées ; l'image retenue est enregistrée en `<Nom>.jpg` (1024 px, moins de 300 Ko), commitée et synchronisée comme une recette.
- I-4 : possibilité de remplacer l'image générée par une photo prise au téléphone.

## 11. Page Paramètres

Les réglages sont des données structurées, saisies par cases à cocher et listes déroulantes, que le serveur traduit en consignes injectées à chaque tour ; l'assistant ne les interprète pas depuis du texte flou.

**Unités et présentation**

| Réglage | Contrôle | Valeurs | Défaut |
| --- | --- | --- | --- |
| Œufs | Liste | Grammes + nombre ; grammes seuls ; nombre seul | Grammes + nombre |
| Poids de référence d'un œuf | Nombre | 40 à 70 g sans coquille | 50 g |
| Pourcentages du boulanger | Liste | Tableau systématique ; sur demande ; jamais | Systématique |
| Rappel du principe et calcul détaillé | Case | Oui / non | Oui |
| Hydratation totale | Case | Affichée / masquée | Affichée |
| Liquides | Liste | Grammes ; millilitres | Grammes |
| Petites quantités (sel, levure, épices) | Liste | Grammes ; cuillères + grammes | Grammes |
| Températures | Liste | °C ; °F | °C |
| Levure de boulanger | Liste | Fraîche ; sèche active ; instantanée | Fraîche |
| Mode de four par défaut | Liste | Statique ; chaleur tournante | Statique |
| Niveau de détail des réponses | Liste | Analyse complète ; synthèse | Complète |

**Préférences alimentaires**

| Réglage | Contrôle | Valeurs |
| --- | --- | --- |
| Régime | Liste | Aucun ; végétarien ; végétalien ; pescétarien |
| Exclusions | Cases | Porc ; alcool ; gélatine animale ; fruits à coque ; gluten ; lactose ; œuf cru |
| Ingrédients à éviter | Liste d'étiquettes libre | Un ingrédient par étiquette |
| Niveau d'exclusion | Liste, par exclusion | Stricte (jamais proposé) ; souple (à éviter, alternative proposée) |
| Substitutions préférées | Cases | Huile neutre plutôt que beurre fondu ; sucre réduit ; farine complète partielle |

**Texte libre par domaine**

Un champ de texte par domaine pour les préférences qui n'entrent pas dans une case : Pâtisserie, Viennoiserie, Boulangerie, Cuisine salée, Yaourts et fermentations, Matériel, Forme des réponses. Tu peux ajouter ou supprimer un domaine.

**Exigences**

- PA-1 : les réglages sont stockés en JSON (`parametres.json`, versionné dans Git) ; le serveur en génère `memoire/parametres.md`, importé dans `CLAUDE.md`.
- PA-2 : une modification s'applique dès le tour suivant, dans toutes les discussions, sans redémarrage.
- PA-3 : en cas de conflit, l'ordre de priorité est : demande explicite dans le message, puis paramètres, puis instructions générales du projet.
- PA-4 : un texte libre de domaine n'est injecté que si la discussion porte sur ce domaine ; les réglages structurés le sont toujours.
- PA-5 : à la validation d'un .cook, le serveur compare les ingrédients aux exclusions strictes et affiche un avertissement bloquant, levé seulement par confirmation.
- PA-6 : les .cook sont toujours écrits en grammes ; les réglages d'unités ne changent que la présentation dans le chat.
- PA-7 : valeurs initiales reprises du projet actuel (colonne Défaut) ; bouton de retour aux valeurs par défaut.
- PA-8 : API `GET` / `PUT /api/parametres` ; le schéma des réglages est déclaratif, de sorte qu'ajouter un réglage ne demande pas de modifier la PWA.

La mémoire (F-11 à F-13) garde les faits appris au fil des discussions ; les Paramètres portent les choix que tu fixes toi-même.

## 12. Base documentaire

L'assistant appuie ses chiffres (hydratation, ratios, températures de cuisson et à cœur) sur une base que tu constitues, et signale explicitement tout chiffre qui n'en provient pas.

**Trois types de contenu**

| Type | Contenu | Origine | Usage |
| --- | --- | --- | --- |
| Fiches de référence | Valeurs chiffrées par type de pâte ou de préparation | Rédigées ou validées par toi, une source par valeur | Consultées en premier, font foi |
| Documents | PDF, EPUB ou Markdown librement téléchargeables, notes personnelles | Importés depuis la PWA | Recherche plein texte |
| Liens | Site ou page de référence sur internet | URL saisie dans la PWA | Copie locale indexée, ou consultation à la demande |

**Format d'une fiche de référence**

Une fiche est un fichier Markdown par famille (brioche, pâte feuilletée levée, pâte à choux, pain courant, crèmes cuites, sirops, chocolat…), avec des champs fixes : fourchettes en % du boulanger (hydratation, sucre, matière grasse, sel, levure), température de pâte en fin de pétrissage, température et mode de four, température à cœur en fin de cuisson, repères visuels, source de chaque valeur.

**Exigences**

- B-1 : écran Base documentaire : ajouter un document, ajouter un lien, créer ou modifier une fiche, activer ou désactiver une source, voir l'état d'indexation.
- B-2 : à l'import, un document est converti en Markdown (extraction de texte, OCR pour les pages scannées) et rangé dans `agent/references/documents/` ; l'original est conservé.
- B-3 : pour un lien, deux modes au choix : « copie locale » (page téléchargée, convertie, rafraîchie sur demande) ou « à la demande » (le domaine est ajouté aux sources que l'assistant interroge en priorité lors d'une recherche web).
- B-4 : recherche en v1 par index plein texte (SQLite FTS5) et lecture directe des fichiers par le CLI ; l'outil `Read` de M-3 est étendu à `references/`. Pas de base vectorielle tant que le volume reste inférieur à quelques centaines de documents.
- B-5 : ordre de priorité des sources : fiches de référence, puis documents, puis liens enregistrés, puis recherche web générale, puis connaissances du modèle.
- B-6 : chaque valeur chiffrée d'un diagnostic ou d'une correction porte sa source (fiche, document et page, ou URL). Une valeur issue des connaissances du modèle est marquée « non sourcé ».
- B-7 : quand deux sources se contredisent, l'assistant donne les deux valeurs et leurs sources, sans trancher en silence.
- B-8 : l'assistant peut proposer une nouvelle fiche ou un ajout à une fiche à partir d'un document ou d'un essai réussi ; rien n'entre dans les fiches sans ta validation (même mécanisme que F-5).
- B-9 : fiches et liens sont versionnés dans Git ; les documents importés sont sauvegardés avec `data/` (X-5) et ne sont pas poussés vers GitHub ni vers Drive.
- B-10 : API `GET` / `POST` / `DELETE /api/references`, `GET /api/references/recherche?q=`, `GET` / `PUT /api/references/fiches/{nom}` ; table `sources` (id, type, titre, chemin ou URL, mode, état, ajoutée_le).
- B-11 : l'ajout d'une source exige une URL publique consultable sans paiement ni compte ; le serveur vérifie que l'URL répond avant de l'enregistrer et signale les liens devenus inaccessibles.

Les extraits de documents utilisés dans une réponse sont envoyés à Claude comme contexte ; le reste de la base ne quitte pas le serveur.

**Critères d'acceptation**

- [ ] Changer le réglage « Œufs » modifie la présentation dès la réponse suivante.
- [ ] Une recette contenant un ingrédient en exclusion stricte déclenche l'avertissement à la validation.
- [ ] Une analyse de brioche cite la fiche « brioche » pour l'hydratation et la température à cœur, et marque « non sourcé » toute valeur absente de la base.

**Sources de départ**

La base n'accepte que des références consultables gratuitement en ligne (B-11) ; aucun ouvrage payant.

| Source | Langue | Apport | Accès |
| --- | --- | --- | --- |
| [King Arthur Baking, référence professionnelle](https://www.kingarthurbaking.com/pro/reference/bakers-percentage) | EN | Pourcentage du boulanger, températures de pâte, préferments, sel, eau | Pages web |
| [BAKERpedia, procédés](https://bakerpedia.com/processes/) | EN | Encyclopédie technique : pâte à choux, feuilletage, pétrissage, absorption d'eau, paramètres de four | Pages web et guides PDF |
| [Understanding Ingredients for the Canadian Baker](https://opentextbc.ca/ingredients/) (BCcampus) | EN | Manuel ouvert sur le rôle des ingrédients : farines, sucres, matières grasses, œufs, chocolat | Licence CC BY 4.0, web, PDF, EPUB |
| [INBP, encart « Techniques de pâtisserie »](https://www.inbp.com/wp-content/uploads/2021/07/inbp-encart-technique-patisserie-1027-juillet-2021-web.pdf) et Suppléments techniques | FR | Fiches de l'Institut national de la boulangerie pâtisserie | PDF |
| [CNBPF, L'essentiel des bonnes pratiques d'hygiène](https://boulangerie.org/wp-content/uploads/CNBPF_Guide-de-lEssentiel-des-bonnes-pratiques-dhygiene-en-boulangerie-patisserie_30.03.2026.pdf) | FR | Chaîne du froid et du chaud, crèmes, œufs, conservation | PDF |
| [Valrhona, guide de cristallisation](https://dam.valrhona.com/m/74481653c9217d6a) | FR | Courbes de tempérage du chocolat noir, lait et blanc | PDF |

Seul le manuel BCcampus est sous licence ouverte : il peut être copié en local sans restriction. Les autres sources sont gratuites à la lecture mais protégées ; elles sont utilisées en mode « à la demande » ou en copie locale strictement privée (B-9).

**Point ouvert**

- [ ] Premières fiches de référence à rédiger à partir des sources de départ (brioche, pâte levée feuilletée, pâte à choux, crèmes cuites, chocolat).

## 13. Risques, jalons et points ouverts

**Risques**

| Risque | Effet | Parade |
| --- | --- | --- |
| Crédit mensuel `claude -p` insuffisant | Assistant indisponible en fin de mois | Suivi du quota (M-6), Sonnet par défaut, moteur de secours par clé API (M-1) |
| Changement des règles ou du format du CLI | Moteur cassé après mise à jour | Version du CLI figée, interface `Engine`, historique en base (D-4) |
| Expiration du jeton d'authentification | Erreur à chaque tour | Détection de l'erreur, procédure de renouvellement documentée |
| Écritures concurrentes côté Drive | Perte d'une modification | Contrôle de divergence et fichiers de conflit (S-3, S-4) |
| Lecture du dossier Drive par l'appli Cook | Recettes absentes hors ligne | Option C, Syncthing (section 7) |

**Jalons**

1. Maquette du moteur : un tour, une reprise de session, mesure du coût par tour. Décide de la viabilité du choix CLI.
2. Chat en streaming et liste des discussions (sections 4 et 6).
3. Propositions, validation, écriture .cook et Git (F-5 à F-10).
4. Synchro GitHub et Drive, test sur le téléphone Android, puis bascule nette depuis le projet claude.ai (section 7).
5. Mémoire, page Paramètres, recherche web, mode hors ligne de la PWA.
6. Base documentaire : import, fiches de référence, citation des sources.
7. v2 : illustrations.

**Critères d'acceptation v1**

- [ ] Soumettre une recette de brioche produit le diagnostic, le tableau en grammes et en % du boulanger et les œufs en grammes et en nombre, comme dans le projet actuel.
- [ ] Aucun fichier n'est écrit sans appui sur « Enregistrer ».
- [ ] La recette enregistrée apparaît dans Git, dans Drive et dans l'appli Cook en moins de 2 minutes.
- [ ] Une discussion de la veille se rouvre et se poursuit avec son contexte, y compris après redémarrage du serveur.
- [ ] Une préférence ajoutée à la mémoire est appliquée dans une nouvelle discussion.
- [ ] Le service est injoignable hors du VPN.

**Points ouverts**

- [ ] Crédit mensuel `claude -p` du compte Pro : montant réel à relever et coût d'une analyse complète de recette à mesurer. Reporté ; à traiter au jalon 1.

**Points clos**

- Système du smartphone : Android.
- Remote Git : dépôt GitHub privé.
- Transition : bascule nette ; le projet claude.ai cesse d'écrire dans le dossier Drive à la mise en service.
- Recettes Bergamot : pas de reprise.
