"""Page Paramètres (section 11) : schéma déclaratif, stockage JSON, consignes générées."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from .depots import Depot


def _liste(cle: str, libelle: str, valeurs: list[tuple[str, str, str]], defaut: str) -> dict:
    return {
        "cle": cle, "libelle": libelle, "controle": "liste", "defaut": defaut,
        "valeurs": [{"valeur": v, "libelle": lib, "consigne": c} for v, lib, c in valeurs],
    }  # fmt: skip


EXCLUSIONS = ["porc", "alcool", "gélatine animale", "fruits à coque", "gluten", "lactose", "œuf cru"]

DOMAINES_DEFAUT = [
    "Pâtisserie", "Viennoiserie", "Boulangerie", "Cuisine salée",
    "Yaourts et fermentations", "Matériel", "Forme des réponses",
]  # fmt: skip

# Ajouter un réglage ici suffit : la PWA construit le formulaire à partir de ce schéma (PA-8).
SCHEMA: dict[str, Any] = {
    "sections": [
        {
            "cle": "unites",
            "titre": "Unités et présentation",
            "reglages": [
                _liste("oeufs", "Œufs", [
                    ("grammes_nombre", "Grammes + nombre", "Exprime les œufs en grammes ET en nombre d'œufs équivalent."),
                    ("grammes", "Grammes seuls", "Exprime les œufs en grammes uniquement, sans nombre équivalent."),
                    ("nombre", "Nombre seul", "Exprime les œufs en nombre uniquement dans la conversation."),
                ], "grammes_nombre"),
                {"cle": "poids_oeuf", "libelle": "Poids de référence d'un œuf", "controle": "nombre", "min": 40, "max": 70,
                 "defaut": 50, "unite": "g sans coquille",
                 "consigne": "Poids de référence d'un œuf moyen sans coquille : {valeur} g."},
                _liste("pourcentages", "Pourcentages du boulanger", [
                    ("systematique", "Tableau systématique", "Présente systématiquement le tableau ingrédient | grammes | % du boulanger."),
                    ("sur_demande", "Sur demande", "Ne présente le tableau des % du boulanger que si je le demande."),
                    ("jamais", "Jamais", "Ne présente pas de tableau des % du boulanger."),
                ], "systematique"),
                {"cle": "rappel_calcul", "libelle": "Rappel du principe et calcul détaillé", "controle": "case", "defaut": True,
                 "consigne": {"true": "Rappelle le principe des % du boulanger et montre un calcul détaillé.",
                              "false": "Ne rappelle pas le principe des % du boulanger et ne détaille pas le calcul."}},
                {"cle": "hydratation", "libelle": "Hydratation totale", "controle": "case", "defaut": True,
                 "libelle_case": "Affichée",
                 "consigne": {"true": "Indique l'hydratation totale.", "false": "N'indique pas l'hydratation totale."}},
                _liste("liquides", "Liquides", [
                    ("grammes", "Grammes", "Exprime les liquides en grammes."),
                    ("millilitres", "Millilitres", "Exprime les liquides en millilitres dans la conversation."),
                ], "grammes"),
                _liste("petites_quantites", "Petites quantités (sel, levure, épices)", [
                    ("grammes", "Grammes", "Exprime les petites quantités en grammes."),
                    ("cuilleres_grammes", "Cuillères + grammes", "Exprime les petites quantités en cuillères ET en grammes."),
                ], "grammes"),
                _liste("temperatures", "Températures", [
                    ("celsius", "°C", "Températures en °C."),
                    ("fahrenheit", "°F", "Températures en °F."),
                ], "celsius"),
                _liste("levure", "Levure de boulanger", [
                    ("fraiche", "Fraîche", "Levure de boulanger par défaut : fraîche."),
                    ("seche_active", "Sèche active", "Levure de boulanger par défaut : sèche active (convertis depuis la fraîche si besoin)."),
                    ("instantanee", "Instantanée", "Levure de boulanger par défaut : instantanée (convertis depuis la fraîche si besoin)."),
                ], "fraiche"),
                _liste("four", "Mode de four par défaut", [
                    ("statique", "Statique", "Mode de four par défaut : chaleur statique."),
                    ("tournante", "Chaleur tournante", "Mode de four par défaut : chaleur tournante."),
                ], "statique"),
                _liste("detail", "Niveau de détail des réponses", [
                    ("complete", "Analyse complète", "Niveau de détail : analyse complète."),
                    ("synthese", "Synthèse", "Niveau de détail : synthèse courte, sans développer chaque point."),
                ], "complete"),
            ],
        },
        {
            "cle": "alimentation",
            "titre": "Préférences alimentaires",
            "reglages": [
                _liste("regime", "Régime", [
                    ("aucun", "Aucun", ""),
                    ("vegetarien", "Végétarien", "Régime végétarien : ni viande, ni poisson, ni gélatine animale."),
                    ("vegetalien", "Végétalien", "Régime végétalien : aucun produit d'origine animale."),
                    ("pescetarien", "Pescétarien", "Régime pescétarien : pas de viande, poisson autorisé."),
                ], "aucun"),
                {"cle": "exclusions", "libelle": "Exclusions", "controle": "cases_niveau", "defaut": {},
                 "options": EXCLUSIONS,
                 "niveaux": [{"valeur": "stricte", "libelle": "Stricte (jamais proposé)"},
                             {"valeur": "souple", "libelle": "Souple (alternative proposée)"}]},
                {"cle": "ingredients_a_eviter", "libelle": "Ingrédients à éviter", "controle": "etiquettes_niveau", "defaut": [],
                 "niveaux": [{"valeur": "stricte", "libelle": "Stricte"}, {"valeur": "souple", "libelle": "Souple"}]},
                {"cle": "substitutions", "libelle": "Substitutions préférées", "controle": "cases", "defaut": ["huile_neutre"],
                 "valeurs": [
                     {"valeur": "huile_neutre", "libelle": "Huile neutre plutôt que beurre fondu",
                      "consigne": "Préfère l'huile neutre au beurre fondu quand la recette le permet."},
                     {"valeur": "sucre_reduit", "libelle": "Sucre réduit",
                      "consigne": "Propose une version à sucre réduit quand la structure le permet."},
                     {"valeur": "farine_complete", "libelle": "Farine complète partielle",
                      "consigne": "Propose de remplacer une partie de la farine par de la farine complète."},
                 ]},
            ],
        },
        {
            "cle": "domaines",
            "titre": "Texte libre par domaine",
            "reglages": [
                {"cle": "textes_domaines", "libelle": "Préférences par domaine", "controle": "textes_domaines",
                 "defaut": {d: "" for d in DOMAINES_DEFAUT}},
            ],
        },
    ]
}  # fmt: skip


def _reglages() -> list[dict]:
    return [r for section in SCHEMA["sections"] for r in section["reglages"]]


def defauts() -> dict[str, Any]:
    return {r["cle"]: json.loads(json.dumps(r["defaut"])) for r in _reglages()}


class ParametresInvalides(ValueError):
    pass


def valider(valeurs: dict[str, Any]) -> dict[str, Any]:
    """Complète avec les défauts et refuse toute valeur hors schéma."""
    propres = defauts()
    for reglage in _reglages():
        cle = reglage["cle"]
        if cle not in valeurs:
            continue
        v, controle = valeurs[cle], reglage["controle"]
        permis = {x["valeur"] for x in reglage.get("valeurs", [])}
        niveaux = {x["valeur"] for x in reglage.get("niveaux", [])}
        if controle == "liste" and v in permis:
            propres[cle] = v
        elif (
            controle == "nombre"
            and isinstance(v, int | float)
            and not isinstance(v, bool)
            and reglage["min"] <= v <= reglage["max"]
        ):
            propres[cle] = v
        elif controle == "case" and isinstance(v, bool):
            propres[cle] = v
        elif controle == "cases" and isinstance(v, list) and set(v) <= permis:
            propres[cle] = v
        elif (
            controle == "cases_niveau"
            and isinstance(v, dict)
            and set(v) <= set(reglage["options"])
            and set(v.values()) <= niveaux
        ):
            propres[cle] = v
        elif (
            controle == "etiquettes_niveau"
            and isinstance(v, list)
            and all(
                isinstance(e, dict) and str(e.get("nom", "")).strip() and e.get("niveau") in niveaux
                for e in v
            )
        ):
            propres[cle] = [{"nom": str(e["nom"]).strip()[:60], "niveau": e["niveau"]} for e in v]
        elif (
            controle == "textes_domaines"
            and isinstance(v, dict)
            and all(isinstance(k, str) and k.strip() and isinstance(t, str) for k, t in v.items())
        ):
            propres[cle] = {k.strip()[:60]: t for k, t in v.items()}
        else:
            raise ParametresInvalides(f"Valeur refusée pour « {reglage['libelle']} ».")
    return propres


def generer_markdown(valeurs: dict[str, Any]) -> str:
    """Traduit les réglages en consignes (PA-1), avec les règles PA-3 et PA-6 en tête."""
    lignes = [
        "# Paramètres",
        "",
        "Réglages fixés par Louis dans la page Paramètres. Ordre de priorité en cas de conflit : "
        "1) demande explicite dans le message, 2) ces paramètres, 3) instructions générales du projet.",
        "",
        "Les fichiers .cook sont toujours écrits en grammes, quels que soient les réglages d'unités : "
        "ceux-ci ne changent que la présentation dans la conversation.",
        "",
    ]
    for section in SCHEMA["sections"]:
        puces: list[str] = []
        for reglage in section["reglages"]:
            v, controle = valeurs[reglage["cle"]], reglage["controle"]
            if controle == "liste":
                puces += [x["consigne"] for x in reglage["valeurs"] if x["valeur"] == v and x["consigne"]]
            elif controle == "nombre":
                puces.append(reglage["consigne"].format(valeur=f"{v:g}"))
            elif controle == "case":
                puces.append(reglage["consigne"]["true" if v else "false"])
            elif controle == "cases":
                puces += [x["consigne"] for x in reglage["valeurs"] if x["valeur"] in v]
            elif controle in ("cases_niveau", "etiquettes_niveau"):
                elements = v.items() if isinstance(v, dict) else [(e["nom"], e["niveau"]) for e in v]
                for nom, niveau in elements:
                    if niveau == "stricte":
                        puces.append(f"Exclusion stricte : {nom}. Ne jamais en proposer.")
                    else:
                        puces.append(f"À éviter : {nom}. Si la recette en contient, propose une alternative.")
        if puces:
            lignes += [f"## {section['titre']}", "", *[f"- {p}" for p in puces], ""]
    return "\n".join(lignes)


# --- Domaines (PA-4) --------------------------------------------------------

MOTS_DOMAINES = {
    "Viennoiserie": ["brioche", "croissant", "pain au chocolat", "feuilletée levée", "viennoiserie", "kouglof", "babka", "chinois"],
    "Boulangerie": ["pain", "baguette", "levain", "boulangerie", "focaccia", "pizza", "poolish", "autolyse"],
    "Pâtisserie": ["gâteau", "tarte", "crème", "choux", "macaron", "biscuit", "sablé", "génoise", "mousse", "cake",
                   "pâtisserie", "chocolat", "meringue", "cookie", "dessert", "flan", "ganache"],
    "Yaourts et fermentations": ["yaourt", "yaourtière", "ferment", "kéfir", "kombucha", "skyr", "fromage blanc"],
    "Cuisine salée": ["plat", "viande", "poisson", "légume", "soupe", "sauce", "quiche", "salé", "entrée", "gratin"],
    "Matériel": ["robot", "kitchenaid", "four", "thermomètre", "moule", "matériel"],
}  # fmt: skip


def normaliser(texte: str) -> str:
    texte = texte.lower().replace("œ", "oe").replace("æ", "ae")
    return "".join(c for c in unicodedata.normalize("NFD", texte) if unicodedata.category(c) != "Mn")


def detecter_domaine(texte: str, domaines: list[str]) -> str | None:
    """Premier domaine dont un mot-clé apparaît ; un domaine ajouté est reconnu par son propre nom."""
    cible = normaliser(texte)
    meilleur, score = None, 0
    for domaine in domaines:
        mots = MOTS_DOMAINES.get(domaine, []) + [domaine]
        trouves = sum(1 for m in mots if re.search(rf"\b{re.escape(normaliser(m))}", cible))
        if trouves > score:
            meilleur, score = domaine, trouves
    return meilleur


# --- Exclusions (PA-5) ------------------------------------------------------

SYNONYMES_DEFAUT = {
    "porc": ["porc", "lard", "lardon", "jambon", "saucisse", "saucisson", "bacon", "chorizo", "pancetta", "guanciale",
             "saindoux", "andouille", "boudin", "coppa", "rillettes", "travers", "échine"],
    "alcool": ["alcool", "rhum", "kirsch", "vin", "bière", "cognac", "grand marnier", "amaretto", "whisky", "vodka",
               "cointreau", "calvados", "porto", "marsala", "liqueur", "champagne", "cidre", "armagnac"],
    "gélatine animale": ["gélatine"],
    "fruits à coque": ["amande", "noisette", "noix", "pistache", "pécan", "cajou", "praliné", "pralin", "macadamia",
                       "pignon", "châtaigne", "marron", "gianduja", "frangipane"],
    "gluten": ["farine", "blé", "seigle", "orge", "épeautre", "semoule", "chapelure", "pain", "pâtes", "boulgour", "couscous"],
    "lactose": ["lait", "beurre", "crème", "fromage", "yaourt", "mascarpone", "ricotta", "babeurre", "lactosérum"],
    "œuf cru": [],
    "viande": ["viande", "bœuf", "veau", "agneau", "poulet", "dinde", "canard", "lapin", "volaille", "steak", "foie gras"],
    "poisson": ["poisson", "saumon", "thon", "cabillaud", "anchois", "crevette", "moule", "crabe", "sardine", "truite"],
    "produits animaux": ["œuf", "jaune", "blanc d'œuf", "miel"],
}  # fmt: skip

# "noix de coco" et "noix de muscade" ne sont pas des fruits à coque ; "lait d'amande" n'est pas du lactose…
FAUX_AMIS = ["noix de coco", "noix de muscade", "lait de coco", "lait d'amande", "lait de soja", "lait d'avoine",
             "beurre de cacao", "beurre de cacahuète", "crème de coco", "crème de tartre", "vinaigre de vin",
             "farine de riz", "farine de maïs", "farine de sarrasin", "blé noir"]  # fmt: skip

REGIMES = {
    "vegetarien": ["viande", "porc", "poisson", "gélatine animale"],
    "vegetalien": ["viande", "porc", "poisson", "gélatine animale", "lactose", "produits animaux"],
    "pescetarien": ["viande", "porc"],
}


def verifier_exclusions(
    valeurs: dict[str, Any], ingredients: list[dict], synonymes: dict[str, list[str]]
) -> list[dict]:
    """Ingrédients qui heurtent une exclusion stricte. Filet de sécurité, pas garantie."""
    regles: dict[str, list[str]] = {}
    for nom, niveau in valeurs.get("exclusions", {}).items():
        if niveau == "stricte":
            regles[nom] = synonymes.get(nom, [nom])
    for famille in REGIMES.get(valeurs.get("regime", "aucun"), []):
        regles.setdefault(f"régime ({famille})", synonymes.get(famille, []))
    for element in valeurs.get("ingredients_a_eviter", []):
        if element["niveau"] == "stricte":
            regles[element["nom"]] = [element["nom"]]
    faux = [normaliser(f) for f in FAUX_AMIS]
    alertes = []
    for ingredient in ingredients:
        nom = normaliser(ingredient["nom"])
        for faux_ami in faux:
            nom = nom.replace(faux_ami, " ")
        for exclusion, mots in regles.items():
            if any(re.search(rf"\b{re.escape(normaliser(m))}s?\b", nom) for m in mots):
                alertes.append({"ingredient": ingredient["nom"], "exclusion": exclusion})
    return alertes


class Parametres:
    """Lecture et écriture de parametres.json dans le dépôt agent/."""

    def __init__(self, depot: Depot):
        self.depot = depot

    def lire(self) -> dict[str, Any]:
        brut = self.depot.lire("parametres.json")
        try:
            return valider(json.loads(brut)) if brut else defauts()
        except (json.JSONDecodeError, ParametresInvalides):
            return defauts()

    def enregistrer(self, valeurs: dict[str, Any]) -> dict[str, Any]:
        propres = valider(valeurs)
        self.depot.ecrire(
            "parametres.json", json.dumps(propres, ensure_ascii=False, indent=2) + "\n", "Paramètres modifiés"
        )
        self.depot.ecrire(
            "memoire/parametres.md", generer_markdown(propres), "Consignes de paramètres régénérées"
        )
        return propres

    def initialiser(self) -> None:
        if (
            self.depot.lire("parametres.json") is None
            or not (self.depot.lire("memoire/parametres.md") or "").strip()
        ):
            self.enregistrer(self.lire())
        if self.depot.lire("exclusions.json") is None:
            self.depot.ecrire(
                "exclusions.json", json.dumps(SYNONYMES_DEFAUT, ensure_ascii=False, indent=2) + "\n",
                "Table des synonymes d'exclusion",
            )  # fmt: skip

    def synonymes(self) -> dict[str, list[str]]:
        try:
            return {**SYNONYMES_DEFAUT, **json.loads(self.depot.lire("exclusions.json") or "{}")}
        except json.JSONDecodeError:
            return SYNONYMES_DEFAUT

    def texte_domaine(self, domaine: str | None) -> str:
        if not domaine:
            return ""
        return (self.lire()["textes_domaines"].get(domaine) or "").strip()

    def domaines(self) -> list[str]:
        return list(self.lire()["textes_domaines"])
