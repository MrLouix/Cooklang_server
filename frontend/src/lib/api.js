// Client de l'API : JSON, envoi de fichiers et lecture des flux SSE.

export class ErreurApi extends Error {
  constructor(statut, corps) {
    super(corps?.detail || corps?.message || `Erreur ${statut}`);
    this.statut = statut;
    this.corps = corps || {};
  }
}

async function requete(methode, chemin, { corps, formulaire, params } = {}) {
  let url = chemin;
  if (params) url += '?' + new URLSearchParams(params);
  const options = { method: methode, credentials: 'same-origin' };
  if (formulaire) options.body = formulaire;
  else if (corps !== undefined) {
    options.body = JSON.stringify(corps);
    options.headers = { 'Content-Type': 'application/json' };
  }
  const reponse = await fetch(url, options);
  if (reponse.status === 204) return null;
  let donnees = null;
  try {
    donnees = await reponse.json();
  } catch {
    /* corps vide */
  }
  if (reponse.status === 401 && chemin !== '/api/connexion') window.dispatchEvent(new Event('ac:deconnecte'));
  if (!reponse.ok) throw new ErreurApi(reponse.status, donnees);
  return donnees;
}

export const api = {
  get: (chemin, params) => requete('GET', chemin, { params }),
  post: (chemin, corps, params) => requete('POST', chemin, { corps, params }),
  put: (chemin, corps) => requete('PUT', chemin, { corps }),
  patch: (chemin, corps) => requete('PATCH', chemin, { corps }),
  suppr: (chemin) => requete('DELETE', chemin),
  envoyerFichier: (chemin, champs) => {
    const formulaire = new FormData();
    for (const [cle, valeur] of Object.entries(champs)) if (valeur != null) formulaire.append(cle, valeur);
    return requete('POST', chemin, { formulaire });
  },
};

export const cheminRecette = (chemin) => chemin.split('/').map(encodeURIComponent).join('/');

/** Lit un flux SSE (POST ou GET) et appelle `surEvenement(genre, donnees)`. Résout à la fin du flux. */
export async function flux(methode, chemin, corps, surEvenement, signal) {
  const options = { method: methode, credentials: 'same-origin', signal };
  if (corps !== undefined) {
    options.body = JSON.stringify(corps);
    options.headers = { 'Content-Type': 'application/json' };
  }
  const reponse = await fetch(chemin, options);
  if (reponse.status === 204) return false;
  if (!reponse.ok) {
    let donnees = null;
    try {
      donnees = await reponse.json();
    } catch {
      /* pas de corps */
    }
    throw new ErreurApi(reponse.status, donnees);
  }
  const lecteur = reponse.body.getReader();
  const decodeur = new TextDecoder();
  let tampon = '';
  for (;;) {
    const { done, value } = await lecteur.read();
    if (done) break;
    tampon += decodeur.decode(value, { stream: true });
    let fin;
    while ((fin = tampon.indexOf('\n\n')) >= 0) {
      const bloc = tampon.slice(0, fin);
      tampon = tampon.slice(fin + 2);
      let genre = 'message';
      let donnees = '';
      for (const ligne of bloc.split('\n')) {
        if (ligne.startsWith('event: ')) genre = ligne.slice(7);
        else if (ligne.startsWith('data: ')) donnees += ligne.slice(6);
      }
      if (donnees) surEvenement(genre, JSON.parse(donnees));
    }
  }
  return true;
}
