const CACHE_NAME = 'odigos-v2';

self.addEventListener('install', (event) => {
  // Skip waiting to activate immediately
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  // Clear all old caches
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Only handle http/https
  if (url.protocol !== 'https:' && url.protocol !== 'http:') return;

  // Never cache API calls, WebSocket, or HTML pages
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws')) return;

  // Navigation requests (HTML pages) -- always go to network
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).catch(() => caches.match('/') || new Response('Offline', { status: 503 }))
    );
    return;
  }

  // Static assets (JS/CSS with hashes) -- cache on first load
  if (url.pathname.startsWith('/assets/')) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        if (cached) return cached;
        return fetch(event.request).then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          }
          return response;
        });
      })
    );
    return;
  }

  // Everything else (icons, manifest, etc.) -- network first, cache fallback
  event.respondWith(
    fetch(event.request).then((response) => {
      if (response.ok) {
        const clone = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
      }
      return response;
    }).catch(() => caches.match(event.request))
  );
});

self.addEventListener('push', (event) => {
  let data = { title: 'Odigos', body: 'New notification' };
  try { data = event.data.json(); } catch (e) {}

  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: data.icon || '/icon-192.png',
      badge: data.badge || '/icon-192.png',
      tag: data.tag || 'odigos-notification',
      renotify: data.renotify || false,
      data: { url: data.url || '/' },
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = event.notification.data?.url || '/';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if (client.url.includes(self.location.origin) && 'focus' in client) {
          return client.focus();
        }
      }
      return clients.openWindow(url);
    })
  );
});
