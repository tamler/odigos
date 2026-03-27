const CACHE_NAME = 'odigos-v1';
const SHELL_URLS = ['/', '/index.html'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_URLS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Only handle http/https -- skip chrome-extension, etc.
  if (url.protocol !== 'https:' && url.protocol !== 'http:') return;

  // Never cache API calls or WebSocket
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws')) return;

  // SPA navigation routes -- serve index.html from cache
  // (any path without a file extension is a client-side route)
  const isNavigationRequest = event.request.mode === 'navigate';

  event.respondWith(
    caches.match(isNavigationRequest ? '/' : event.request).then((cached) => {
      if (cached) return cached;
      return fetch(event.request).then((response) => {
        if (response.ok && !isNavigationRequest) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      }).catch(() => {
        // Offline fallback for navigation -- serve cached shell
        if (isNavigationRequest) return caches.match('/');
        return new Response('', { status: 408 });
      });
    })
  );
});
