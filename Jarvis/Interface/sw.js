// Service worker de l'app Jarvis : il garde l'interface en cache pour que l'app s'ouvre même
// quand le Mac est injoignable (en veille, Tailscale coupé). Elle dit alors ce qui manque et se
// reconnecte d'elle-même. L'API n'est jamais mise en cache : ses réponses sont personnelles.

const CACHE = 'jarvis-interface-v1';
const SHELL = [
  './',
  './hud.css',
  './hud.js',
  './core.js',
  './voice.js',
  './mic-worklet.js',
  './manifest.webmanifest',
  './icons/icon.svg',
  './icons/icon-32.png',
  './icons/icon-192.png',
  './icons/apple-touch-icon.png',
];
const FONTS = /(^|\.)fonts\.(googleapis|gstatic)\.com$/;

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

function remember(request, response) {
  if (response.ok || response.type === 'opaque') {
    const copy = response.clone();
    caches.open(CACHE).then((cache) => cache.put(request, copy));
  }
  return response;
}

// Version en cache ; à défaut, la réponse du réseau telle quelle (ou une erreur).
function fromCache(request, networkResponse) {
  return caches.match(request, { ignoreSearch: true })
    .then((hit) => hit || (request.mode === 'navigate' ? caches.match('./') : undefined))
    .then((hit) => hit || networkResponse || Response.error());
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);

  if (url.origin === self.location.origin) {
    if (url.pathname.startsWith('/api/')) return;
    // Réseau d'abord : une mise à jour de l'interface arrive aussitôt. Le cache sert quand le Mac
    // ne répond pas (réseau coupé), ou quand Jarvis est arrêté (Tailscale répond alors 502).
    event.respondWith(
      fetch(request)
        .then((response) => (response.status >= 500 ? fromCache(request, response) : remember(request, response)))
        .catch(() => fromCache(request)),
    );
  } else if (FONTS.test(url.hostname)) {
    // Les polices changent rarement : le cache d'abord.
    event.respondWith(caches.match(request).then((hit) => hit || fetch(request).then((response) => remember(request, response))));
  }
});
