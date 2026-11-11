// État partagé : route, connexion réseau, thème, messages éphémères.

function lireRoute() {
  const brut = decodeURI(location.hash.replace(/^#\/?/, ''));
  const [ecran = 'discussions', ...reste] = brut.split('/');
  return { ecran: ecran || 'discussions', param: reste.join('/') };
}

export const app = $state({
  route: lireRoute(),
  enLigne: navigator.onLine,
  theme: localStorage.getItem('ac-theme') || 'auto',
  messages: [],
});

window.addEventListener('hashchange', () => (app.route = lireRoute()));
window.addEventListener('online', () => (app.enLigne = true));
window.addEventListener('offline', () => (app.enLigne = false));

export function aller(ecran, param = '') {
  location.hash = '#/' + ecran + (param ? '/' + encodeURI(param) : '');
}

export function appliquerTheme(theme = app.theme) {
  app.theme = theme;
  localStorage.setItem('ac-theme', theme);
  if (theme === 'auto') delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
}

let compteur = 0;
export function notifier(texte, genre = 'info') {
  const id = ++compteur;
  app.messages.push({ id, texte, genre });
  setTimeout(() => (app.messages = app.messages.filter((m) => m.id !== id)), genre === 'erreur' ? 6000 : 3000);
}

/** Exécute une action d'API et affiche l'erreur éventuelle. */
export async function tenter(action, succes) {
  try {
    const resultat = await action();
    if (succes) notifier(succes);
    return resultat;
  } catch (erreur) {
    notifier(app.enLigne ? erreur.message : 'Hors connexion.', 'erreur');
    return undefined;
  }
}
