"""Lecture de pages web par le serveur, pour les moteurs dont le fournisseur n'héberge pas d'outil web.

Le contenu rapporté est une donnée non fiable (X-3) : le modèle n'a ni écriture ni shell, et rien
n'est enregistré sans validation. Seuls les hôtes publics sont joignables.
"""

from __future__ import annotations

import httpx

from ..references import ErreurReference, html_en_markdown, url_publique

TAILLE_MAX = 60_000

DEFINITION = {
    "name": "WebFetch",
    "description": (
        "Télécharge une page web publique et en renvoie le texte. À utiliser pour lire une recette ou une source "
        "dont l'URL est connue (donnée par Louis, ou figurant dans la base documentaire)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"url": {"type": "string", "description": "Adresse http(s) complète."}},
        "required": ["url"],
        "additionalProperties": False,
    },
}


class LectureWeb:
    def __init__(self, client: httpx.AsyncClient | None = None, verifier_hote: bool = True):
        self.client = client or httpx.AsyncClient(
            follow_redirects=True,
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0 (compatible; lecteur-de-recettes)"},
        )
        self.verifier_hote = verifier_hote

    async def executer(self, entree: object) -> tuple[str, bool]:
        """Renvoie (texte, est_une_erreur) ; ne lève jamais."""
        url = entree.get("url") if isinstance(entree, dict) else None
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            return "Paramètre invalide : `url` doit être une adresse http(s).", True
        try:
            if self.verifier_hote:
                url_publique(url)
            reponse = await self.client.get(url)
        except ErreurReference as erreur:
            return str(erreur), True
        except httpx.HTTPError as erreur:
            return f"Page injoignable : {erreur}", True
        if reponse.status_code >= 400:
            return f"La page a répondu HTTP {reponse.status_code}.", True
        genre = reponse.headers.get("content-type", "")
        if "html" in genre:
            titre, texte = html_en_markdown(reponse.text)
            texte = f"# {titre}\n\n{texte}" if titre else texte
        elif genre.startswith("text/") or "json" in genre:
            texte = reponse.text
        else:
            return f"Type de contenu non lisible : {genre or 'inconnu'}.", True
        if len(texte) > TAILLE_MAX:
            # Jamais de coupe silencieuse : le modèle sait que la page continue.
            texte = (
                texte[:TAILLE_MAX]
                + f"\n\n[Page tronquée : {len(texte) - TAILLE_MAX} caractères non affichés.]"
            )
        return f"Source : {url}\n\n{texte}", False
