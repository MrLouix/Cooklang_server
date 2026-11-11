// Service worker : coquille de l'appli en cache, lectures de l'API consultables hors connexion (P-2).
const VERSION = 'ac-v1';
const COQUILLE = ['/', '/manifest.webmanifest', '/icone.svg', '/icone-192.png'];
const LECTURES = /^\/api\/(discussions|recettes|memoire|parametres|references)(\/|$|\?)/;

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(COQUILLE)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((cles) => Promise.all(cles.filter((c) => c !== VERSION).map((c) => caches.delete(c)))).then(() => self.clients.claim()),
  );
});

async function reseauPuisCache(requete) {
  const cache = await caches.open(VERSION);
  try {
    const reponse = await fetch(requete);
    if (reponse.ok) cache.put(requete, reponse.clone());
    return reponse;
  } catch (erreur) {
    const sauvegarde = await cache.match(requete);
    if (sauvegarde) return sauvegarde;
    throw erreur;
  }
}

async function cachePuisReseau(requete) {
  const cache = await caches.open(VERSION);
  const sauvegarde = await cache.match(requete);
  if (sauvegarde) return sauvegarde;
  const reponse = await fetch(requete);
  if (reponse.ok) cache.put(requete, reponse.clone());
  return reponse;
}

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  if (url.pathname.endsWith('/flux')) return; // flux SSE : jamais en cache
  if (url.pathname.startsWith('/api/')) {
    if (LECTURES.test(url.pathname + url.search)) e.respondWith(reseauPuisCache(e.request));
    return;
  }
  // Fichiers du build (noms hachés) : cache d'abord ; page d'accueil : réseau d'abord.
  e.respondWith(url.pathname.startsWith('/assets/') ? cachePuisReseau(e.request) : reseauPuisCache(e.request));
});
