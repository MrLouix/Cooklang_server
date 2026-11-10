---
name: "recette-cook"
description: "Créer une nouvelle recette ou une variante de recette Cooklang (.cook) pour le dossier Recettes : proposition dans la conversation, fichier écrit seulement après accord."
---

# Recettes Cooklang : création et variantes

À utiliser quand Louis :
- **Variante** : soumet une recette `.cook` (pièce jointe ou fichier du dossier) et demande une version modifiée (ajout/substitution d'ingrédient, réduction de sucre, changement de technique).
- **Nouvelle recette** : demande une recette qu'il n'a pas encore (« trouve-moi une recette de… »), souvent avec un problème à corriger (« les miennes sont trop molles… »).

## Règle absolue : deux phases
1. **Proposition dans la conversation.** La recette complète est présentée dans la réponse (tableaux, étapes, notes). Aucun fichier n'est écrit dans le dossier Recettes, aucun `device_commit_files`, aucune copie d'image.
2. **Enregistrement uniquement après autorisation explicite** (« ok, enregistre », « range-la », « vas-y »). Une question, une remarque ou une demande de modification n'est PAS une autorisation : on itère d'abord dans la conversation.

À la fin de la phase 1, terminer par une ligne du type : « Je l'enregistre en `.cook` dans `<Catégorie>` ? »

## Dossier
- Racine : `G:\Mon Drive\WORKSPACE\Recettes` (via `device_bash` : `$HOME/mnt/Recettes`).
- Sous-dossiers par catégorie, déterminés par le champ `course` du front matter (même table que `ranger_recettes.ps1`) :

| course | Sous-dossier |
|---|---|
| plat | Plat |
| entrée | Entrée |
| soupe | Soupe |
| accompagnement, sauce | Accompagnement et sauce |
| dessert | Dessert |
| biscuit, confiserie | Biscuit et confiserie |
| viennoiserie, boulangerie | Boulangerie et viennoiserie |
| boisson | Boisson |

- Chaque recette `Nom.cook` a une image `Nom.jpg` du même nom, dans le même sous-dossier.
- Fichiers de l'appli à ne pas toucher : `.bookmarks`, `.shopping-list`, `.shopping-checked`.

## Phase 1 : proposition

### 1. Contexte
- **Variante** : lire l'original en entier (front matter, bloc `[- … -]`, notes `>`, étapes) et repérer son sous-dossier avec `device_list_dir`.
- **Nouvelle recette** : lire 2-3 `.cook` existants de la même catégorie pour reprendre le style. Chercher dans l'historique du projet (`conversation_search`) si la recette a déjà été discutée. Faire une recherche web (WebSearch/WebFetch) sur la version de référence (traditionnelle, chef reconnu) et sur la science du résultat visé ; citer les sources.

### 2. Clarifier (2 questions max, sinon hypothèse explicite)
- Quantité d'un ingrédient déjà testé mais non donnée → hypothèse chiffrée.
- Nature exacte quand elle change les ratios (pâte de noisette pure ou praliné ; levure fraîche ou sèche ; type de farine T45/T55/gruau).
- Défaut rencontré (trop sec, trop blanc, mou le lendemain…) → 2-3 causes probables par ordre de probabilité, four compris.

### 3. Analyse technique
- Effet de chaque choix sur : matière grasse réelle (beurre ≈ 82 % de lipides, pâte de noisette/amande ≈ 60-62 %, poudre de noisette ≈ 60 %), sucre, hydratation, structure (gluten, coagulation), cuisson, conservation.
- Variante : compenser si besoin en respectant l'intention et ce que Louis a validé (« ça fonctionne bien » = ne pas tout remettre en cause).
- Toute valeur en grammes ET % du boulanger, située par rapport à la fourchette habituelle du type de pâte.

### 4. Présenter la proposition (dans la réponse)
Direct, sans préambule :
- Hypothèses faites.
- Diagnostic / effet technique (2-4 puces).
- Tableau ingrédient | g | % | modif (colonne modif seulement pour une variante). Rappel du principe (farine = 100 %) et un calcul exemple.
- Hydratation totale (lait 87 %, œuf entier 75 %, beurre 16 %) et ce qu'elle implique.
- Œufs en grammes ET nombre.
- Méthode : accessoire KitchenAid, vitesse, durée (crochet ≤ vitesse 2), températures sonde (beurre, pâte, cœur), four (mode, préchauffage 30 min, rotation de plaque, repères visuels).
- Risques sanitaires et conservation.
- Une seule variable à ajuster pour itérer, avec un critère mesurable.
- Sources si recherche web.
- Question finale d'enregistrement.

## Phase 2 : enregistrement (après accord)

### 5. Rédiger le `.cook`
Reprendre le style des fichiers existants :

```
---
title: …
locale: fr
servings: 6
course: biscuit
difficulty: facile
time.prep: 20 minutes
time.cook: 16 minutes
tags: [sablé, biscuit]
description: … (version, modifications, rendement en g)
source: https://…
---

[- Pourcentages du boulanger (farine = 100 %)
   Farine 250 g = 100 % | … 
   Calcul exemple : beurre 125 ÷ 250 × 100 = 50 %
   Hydratation totale : … → 23 % (…) -]

> Modifications : ancien → nouveau (%)
> Hypothèse : …
```

Règles Cooklang (validées dans l'historique) :
- `servings` : un nombre seul (`2`, pas `2 brioches`). Pas de `yield: 1100%g` (rejeté) : mettre le rendement dans `description`.
- Ingrédients `@nom{qté%unité}` ; optionnels `@?nom{…}` (variantes, garnitures) ; décimales avec un point (`{1.5%g}`).
- Ustensiles `#nom{}`.
- Minuteurs `~nom{valeur%unité}` : nom d'un seul mot, valeur entière unique, unité au pluriel (`minutes`, `seconds`, `hours`). Plage en texte à côté : `~cuisson{20%minutes} (20-30 min)`. Pas de décimales : `90%minutes` plutôt que `1.5%hours`.
- Notes `>` pour repères, sécurité, conservation ; sections `== Pétrissage ==` si la recette est longue.
- Éviter qu'un même ingrédient serve à plusieurs rôles sous le même nom si la liste de courses en souffre (ex. lait pâte / lait dorure) ; sinon le signaler.

### 6. Valider la syntaxe
```
npm i @cooklang/cooklang
node -e "const {CooklangParser}=require('@cooklang/cooklang');const fs=require('fs');const [r,rep]=new CooklangParser().parse(fs.readFileSync(process.argv[1],'utf8'));console.log(rep)" fichier.cook
```
Viser 0 avertissement ; corriger avant d'écrire.

### 7. Ranger
1. Écrire le fichier dans `/mnt/user-data/outputs/`.
2. Nom : variante → `Nom original (variante).cook`, jamais d'écrasement de l'original sauf si Louis le demande explicitement ; nouvelle recette → `Nom.cook`. Vérifier qu'aucun fichier du même nom n'existe déjà.
3. `device_commit_files` vers `G:\Mon Drive\WORKSPACE\Recettes\<Catégorie>\` (catégorie selon `course`). Si refus faute d'autorisation : `device_request_folder_access` sur `G:\Mon Drive\WORKSPACE\Recettes`, puis réessayer.
4. Image :
   - **Variante** : réutiliser l'image de l'original. `device_bash` + `cp` si disponible ; sinon `device_stage_files` de `<Nom original>.jpg`, copie locale sous `<Nom variante>.jpg`, puis `device_commit_files` dans le même sous-dossier.
   - **Nouvelle recette** : pas d'image existante. Indiquer à Louis la commande à lancer depuis le dossier Recettes :
     ```
     $env:OPENROUTER_API_KEY = "sk-or-..."
     powershell -ExecutionPolicy Bypass -File .\generer_images.ps1 -Only "<Nom>"
     ```
     (script parcourant les sous-dossiers, JPEG compressé, modèle par défaut google/gemini-2.5-flash-image).
5. Vérifier avec `device_list_dir` que `.cook` et `.jpg` sont côte à côte.
6. Confirmer en une ou deux lignes : nom du fichier, sous-dossier, image.

## Limites connues
- `device_bash` peut être indisponible (environnement en téléchargement, appareil déconnecté) : se rabattre sur `device_list_dir` / `device_stage_files` / `device_commit_files`, en vérifiant d'abord avec `device_list_dir` qu'une commande interrompue n'a rien modifié.
- Suppression et déplacement impossibles sans autorisation : ne pas laisser de fichier à la racine ; écrire directement dans le bon sous-dossier.