// Keeps a copy of the app so it opens even while the computer is out of reach.
//
// Network first: every load still comes from the computer when it can, so
// updates show up at once. Browsers only run service workers over HTTPS (or
// on localhost), so over plain local-network HTTP this never registers.

const CACHE = 'open-dots-shell-v1';
const SHELL = ['/m/', '/m/app.js', '/m/markdown.js', '/m/styles.css', '/m/icons/icon-180.png', '/m/icons/icon.svg'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter((name) => name !== CACHE).map((name) => caches.delete(name)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);
  // Conversations and live events always come from the computer, never a cache.
  if (request.method !== 'GET' || url.origin !== self.location.origin || !url.pathname.startsWith('/m/')) return;

  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    try {
      const response = await fetch(request);
      if (response.ok) cache.put(request, response.clone());
      return response;
    } catch (error) {
      // Any start URL (with or without a linking code) opens the cached app.
      const cached = request.mode === 'navigate'
        ? await cache.match('/m/', { ignoreSearch: true })
        : await cache.match(request, { ignoreSearch: url.pathname.endsWith('.webmanifest') });
      if (cached) return cached;
      throw error;
    }
  })());
});
