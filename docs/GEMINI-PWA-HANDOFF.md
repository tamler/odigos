# Gemini Handoff: Mobile Polish + PWA

Read GEMINI-HANDOFF.md fully before starting.

The workspace redesign (G-W1 through G-W5) is done and deployed. This session has two tasks: mobile polish for the workspace components, and PWA support.

## Important: Icons Are Already In Place

The Odigos brand icon (bold "O" with purple accent dot, dark background) is already at:
- `dashboard/public/favicon.svg` -- the master SVG icon
- `dashboard/public/favicon.ico` -- favicon

Look at `favicon.svg` to see the exact design. Use it as the source for generating all PWA icon sizes. Do NOT create a new icon design. Do NOT use the Vite default icon.

---

## Task G-M1: Mobile Polish for Workspace Components

**Priority:** High

The workspace redesign introduced components that weren't tested at mobile widths. Fix them.

### QuickSwitcher (dashboard/src/components/QuickSwitcher.tsx)

Current issues:
- Hardcoded `max-w-lg` and `top-[20%]` -- on mobile the dialog is too narrow and too high
- Keyboard hint badges (arrows, Enter, Esc) are irrelevant on touch devices
- No touch-friendly sizing on result rows

Fix:
- Dialog: `w-[calc(100%-2rem)] max-w-lg` on mobile, centered. On small screens use `top-[10%]` or inset for more room
- Hide keyboard hints on mobile (`hidden lg:flex`)
- Result rows: minimum 44px touch targets
- Input: 16px font size minimum on mobile (prevents iOS zoom on focus)

### AgentInputBar (dashboard/src/components/AgentInputBar.tsx)

Current issues:
- No responsive classes at all
- The "/" shortcut hint is irrelevant on mobile

Fix:
- Hide "/" shortcut text on mobile (`hidden lg:inline`)
- Ensure the input and send button have 44px minimum touch targets
- Response popover should be full-width on mobile
- Test at 375px width

### NotebookPage (dashboard/src/pages/NotebookPage.tsx)

Verify:
- Tiptap editor works at mobile widths (text wraps, toolbar doesn't overflow)
- Notebook selector dropdown is accessible on mobile
- If there's a toolbar, it should scroll horizontally on overflow

### General

- All interactive elements must be minimum 44px touch target
- No horizontal scroll at 375px
- Test the contextual sidebar behavior on mobile (should overlay, not push)

---

## Task G-PWA: Progressive Web App Support

**Priority:** High

Make Odigos installable as a PWA so users can "Add to Home Screen" on iOS, Android, and desktop.

### 1. Generate App Icons from the Existing SVG

The master icon is at `dashboard/public/favicon.svg`. It's a dark rounded-rect background with a white "O" and purple accent dot.

Generate these PNG files in `dashboard/public/` from the SVG:
- `icon-192.png` (192x192)
- `icon-512.png` (512x512)
- `icon-maskable-512.png` (512x512 with safe zone padding -- the icon content should be within the inner 80% for maskable icon support on Android)
- `apple-touch-icon.png` (180x180)

You can generate these using a canvas script, sharp, or any approach that works. The key requirement is they must match the existing `favicon.svg` design exactly -- same colors, same proportions.

### 2. Web App Manifest

Create `dashboard/public/manifest.json`:
```json
{
  "name": "Odigos",
  "short_name": "Odigos",
  "description": "Your personal AI that gets smarter every day",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#030305",
  "theme_color": "#030305",
  "orientation": "any",
  "icons": [
    {
      "src": "/favicon.svg",
      "sizes": "any",
      "type": "image/svg+xml"
    },
    {
      "src": "/icon-192.png",
      "sizes": "192x192",
      "type": "image/png"
    },
    {
      "src": "/icon-512.png",
      "sizes": "512x512",
      "type": "image/png"
    },
    {
      "src": "/icon-maskable-512.png",
      "sizes": "512x512",
      "type": "image/png",
      "purpose": "maskable"
    }
  ]
}
```

Note: `background_color` and `theme_color` are `#030305` -- this matches the icon background and the app's dark theme. Check the actual CSS variable for `--background` in the dark theme and use that if different.

### 3. Service Worker

Create `dashboard/public/sw.js`:

```js
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
  // Network-first for API calls and WebSocket -- never cache these
  if (event.request.url.includes('/api/') || event.request.url.includes('/ws')) {
    return;
  }
  event.respondWith(
    caches.match(event.request).then((cached) => {
      return cached || fetch(event.request).then((response) => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      });
    })
  );
});
```

### 4. Update index.html

In `dashboard/index.html`, replace the existing `<link rel="icon">` line and add PWA meta tags in `<head>`:

```html
<link rel="icon" type="image/svg+xml" href="/favicon.svg" />
<link rel="icon" type="image/x-icon" href="/favicon.ico" />
<link rel="apple-touch-icon" href="/apple-touch-icon.png" />
<link rel="manifest" href="/manifest.json" />
<meta name="theme-color" content="#030305" />
<meta name="apple-mobile-web-app-capable" content="yes" />
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
<meta name="apple-mobile-web-app-title" content="Odigos" />
<meta name="description" content="Your personal AI that gets smarter every day" />
```

### 5. Register Service Worker

In `dashboard/src/main.tsx` (or wherever the React app mounts), add after the render call:

```ts
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  });
}
```

### Verification

1. Build must pass: `npm run build`
2. TypeScript must compile: `npx tsc --noEmit`
3. After deploying, in Chrome DevTools > Application tab:
   - Manifest should show with all icons
   - Service worker should be registered and active
   - "Install" button should appear in the URL bar
4. On mobile: "Add to Home Screen" should work
5. The installed app should open full-screen without browser chrome
6. The app icon on the home screen should be the Odigos "O" with purple dot

Log your progress in the Communication Log at the bottom of GEMINI-HANDOFF.md.

---

## Conventions (unchanged)

1. **API responses are flat objects**, not wrapped
2. **Use `get/post/patch/del` from `@/lib/api`** for all HTTP calls
3. **Use `toast` from `sonner`** for notifications
4. **Use `lucide-react`** for all icons
5. **Responsive: `lg:` prefix** for desktop-specific styles
6. **TypeScript must compile**: `cd dashboard && npx tsc --noEmit`
7. **Build must succeed**: `cd dashboard && npm run build`
