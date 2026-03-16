# Mobile & Tablet Responsive Design

## Goal

Make the Odigos dashboard usable on mobile phones and tablets using CSS-first responsive techniques. No new components, no design overhaul -- just Tailwind breakpoints and minimal JS to make existing UI reflow correctly.

## Context

The dashboard is a React/TypeScript SPA (Vite + Tailwind + shadcn/ui) with a fixed sidebar layout. It currently has no responsive breakpoints, hover-only interactions, and fixed widths that break on small screens. The UI is not the primary interface -- some users exclusively use Telegram or other channels -- so this work should be minimal and functional, not a mobile redesign.

## Breakpoints

| Breakpoint | Width | Sidebar | Navigation |
|---|---|---|---|
| Mobile | <640px | Hidden, slide-in overlay | Hamburger menu |
| Tablet portrait | 640-1024px | Hidden, slide-in overlay | Hamburger menu |
| Tablet landscape / Desktop | 1024px+ | Always visible | Current sidebar |

Using Tailwind's `lg:` (1024px) as the primary breakpoint for sidebar visibility. Below `lg:`, the sidebar is an overlay.

## Design Decisions

- **Chat-first mobile**: Mobile users primarily chat, upload documents, and use voice. Settings/admin pages are accessible but not optimized for.
- **Tablet adaptive**: Portrait mode behaves like mobile (overlay sidebar). Landscape shows the full desktop layout.
- **No new dependencies**: Pure Tailwind responsive classes + one boolean state variable for sidebar toggle.
- **Same visual design**: Dark theme, same components, same spacing conventions -- just responsive padding and layout shifts.

## Changes

### 1. AppLayout.tsx -- Responsive sidebar

**Current**: Sidebar is `w-64` or `w-14` (collapsed), always visible in a flex row.

**New behavior**:
- Below `lg:` breakpoint: sidebar is positioned fixed/absolute, translated off-screen (`-translate-x-full`), with `translate-x-0` when open. A semi-transparent backdrop overlay sits behind it. Tapping backdrop closes sidebar.
- At `lg:` and above: sidebar is always visible in the flex row (current behavior).
- A hamburger button appears in a top bar on mobile/tablet, hidden at `lg:`.

**State**: Add `sidebarOpen` boolean state. Hamburger toggles it. Backdrop click and navigation action both close it.

```
// Conceptual classes (not exact implementation)
<aside className={`
  fixed inset-y-0 left-0 z-40 w-64 bg-background border-r
  transition-transform duration-200
  ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}
  lg:static lg:translate-x-0 lg:flex
`}>

// Backdrop (mobile only)
{sidebarOpen && (
  <div className="fixed inset-0 z-30 bg-black/50 lg:hidden"
       onClick={() => setSidebarOpen(false)} />
)}

// Mobile top bar
<div className="flex items-center gap-2 p-3 border-b lg:hidden">
  <Button variant="ghost" size="icon" onClick={() => setSidebarOpen(true)}>
    <Menu className="h-5 w-5" />
  </Button>
  <span className="font-semibold">Odigos</span>
  <Button variant="ghost" size="icon" className="ml-auto" onClick={handleNewChat}>
    <Plus className="h-5 w-5" />
  </Button>
</div>
```

### 2. AppLayout.tsx -- Touch-friendly conversation actions

**Current**: Conversation menu (rename/delete/export) uses `group-hover:opacity-100` which doesn't work on touch devices.

**New**: The dropdown trigger button is always visible (remove the `opacity-0 group-hover:opacity-100`). On desktop, the button is subtle (ghost styling); on mobile, it's a clear tap target. No long-press needed.

### 3. AppLayout.tsx -- Auto-close sidebar on navigation

When the user taps a conversation or navigation link on mobile, close the sidebar automatically. Add `setSidebarOpen(false)` to `handleSelectConversation` and the nav button click handlers, guarded by a media query check or simply always called (no-op when sidebar is already closed on desktop).

### 4. Pages -- Responsive padding and grids

Apply responsive padding to all page containers:

- `max-w-3xl mx-auto px-4 sm:px-6 py-4 sm:py-6` (was `px-6 py-6`)
- Settings tabs: horizontal scroll on small screens if needed (tab bar gets `overflow-x-auto`)
- StatePage grid: already has `grid-cols-1 md:grid-cols-2` (no change needed)
- SkillsTab/PromptsTab: card layouts already single-column (no change needed)

### 5. Settings tab bar -- Scrollable on mobile

The settings page has 6 tabs (General, Skills, Prompts, Evolution, Agents, Plugins). On narrow screens, the tab bar should scroll horizontally rather than wrapping or overflowing.

Add `overflow-x-auto` and `flex-nowrap whitespace-nowrap` to the tab container. Each tab button gets `flex-shrink-0`.

## Files Modified

| File | Change |
|---|---|
| `dashboard/src/layouts/AppLayout.tsx` | Responsive sidebar, hamburger, backdrop, touch-friendly actions, auto-close |
| `dashboard/src/pages/ChatPage.tsx` | Responsive padding |
| `dashboard/src/pages/SettingsPage.tsx` | Scrollable tab bar |
| `dashboard/src/pages/settings/GeneralSettings.tsx` | Responsive padding |
| `dashboard/src/pages/settings/SkillsTab.tsx` | Responsive padding |
| `dashboard/src/pages/settings/PromptsTab.tsx` | Responsive padding |
| `dashboard/src/pages/settings/EvolutionTab.tsx` | Responsive padding |
| `dashboard/src/pages/settings/AgentsTab.tsx` | Responsive padding |
| `dashboard/src/pages/settings/PluginsTab.tsx` | Responsive padding |
| `dashboard/src/pages/StatePage.tsx` | Responsive padding |
| `dashboard/src/pages/FeedPage.tsx` | Responsive padding |
| `dashboard/src/pages/ConnectionsPage.tsx` | Responsive padding |
| `dashboard/src/pages/EvolutionPage.tsx` | Responsive padding |
| `dashboard/src/pages/AgentsPage.tsx` | Responsive padding |
| `dashboard/src/pages/PluginsPage.tsx` | Responsive padding |

## Out of Scope

- PWA (manifest, service worker, offline)
- Native-like gestures (swipe to dismiss)
- Bottom tab bar navigation
- Separate mobile layout component
- Mobile-specific pages or features
- Dark/light mode toggle
- Voice/mic button in chat input (separate feature, no existing dashboard-side STT integration)
- File upload button in chat input (already exists via Paperclip icon)

## Testing

- Manual testing at 375px (iPhone SE), 768px (iPad portrait), 1024px (iPad landscape), 1440px (desktop)
- Verify: sidebar toggle works, backdrop dismisses, navigation auto-closes sidebar
- Verify: conversation actions accessible on touch (no hover required)
- Verify: settings tabs scrollable on narrow screens
- TypeScript type-check passes (`npx tsc --noEmit`)
- Production build succeeds (`npm run build`)
