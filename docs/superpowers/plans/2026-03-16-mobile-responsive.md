# Mobile & Tablet Responsive Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Odigos dashboard usable on mobile and tablet by adding Tailwind responsive breakpoints and a slide-in sidebar overlay.

**Architecture:** CSS-first approach using Tailwind's `lg:` breakpoint (1024px). Below `lg:`, the sidebar becomes a fixed overlay toggled by a hamburger menu. One new boolean state (`sidebarOpen`) in AppLayout. All pages get responsive padding. No new components or dependencies.

**Tech Stack:** React, TypeScript, Tailwind CSS, lucide-react icons

**Spec:** `docs/superpowers/specs/2026-03-16-mobile-responsive-design.md`

---

## Chunk 1: AppLayout Responsive Sidebar

### Task 1: Add sidebarOpen state and hamburger toggle

**Files:**
- Modify: `dashboard/src/layouts/AppLayout.tsx`

- [ ] **Step 1: Add Menu import and sidebarOpen state**

In the imports, add `Menu` to the lucide-react import:

```typescript
import { Settings, PanelLeftClose, PanelLeft, Plus, Pencil, Trash2, Check, X, Download, MoreHorizontal, Activity, Rss, Link2, Menu } from 'lucide-react'
```

Add state after the existing `collapsed` state:

```typescript
const [sidebarOpen, setSidebarOpen] = useState(false)
```

- [ ] **Step 2: Add mobile top bar before the sidebar**

Inside the `<div className="flex h-screen ...">`, BEFORE the `<aside>`, add:

```tsx
{/* Mobile top bar */}
<div className="flex items-center gap-2 p-3 border-b border-border/40 lg:hidden fixed top-0 left-0 right-0 z-20 bg-background">
  <Button variant="ghost" size="icon" onClick={() => setSidebarOpen(true)}>
    <Menu className="h-5 w-5" />
  </Button>
  <span className="text-sm font-semibold">Odigos</span>
  <Button variant="ghost" size="icon" className="ml-auto" onClick={handleNewChat}>
    <Plus className="h-5 w-5" />
  </Button>
</div>
```

- [ ] **Step 3: Make sidebar responsive**

Change the `<aside>` className from:

```
${collapsed ? 'w-14' : 'w-64'} flex flex-col border-r border-border/40 transition-all duration-200
```

To:

```
fixed inset-y-0 left-0 z-40 w-64 flex flex-col border-r border-border/40 bg-background transition-transform duration-200 ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'} lg:static lg:translate-x-0 ${collapsed ? 'lg:w-14' : 'lg:w-64'}
```

This keeps the existing collapse behavior on desktop (`lg:`) while making the sidebar a slide-in overlay on mobile.

- [ ] **Step 4: Add backdrop overlay**

Right after the `<aside>` closing tag, add:

```tsx
{/* Backdrop for mobile sidebar */}
{sidebarOpen && (
  <div
    className="fixed inset-0 z-30 bg-black/50 lg:hidden"
    onClick={() => setSidebarOpen(false)}
  />
)}
```

- [ ] **Step 5: Add top padding to main content on mobile**

Change the `<main>` className from:

```
flex-1 flex flex-col overflow-hidden
```

To:

```
flex-1 flex flex-col overflow-hidden pt-[52px] lg:pt-0
```

The `pt-[52px]` accounts for the fixed mobile top bar height. On desktop (`lg:`), padding is removed since the top bar is hidden.

- [ ] **Step 6: Type-check**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 7: Commit**

```bash
git add dashboard/src/layouts/AppLayout.tsx
git commit -m "feat(dashboard): add responsive sidebar with hamburger toggle

Sidebar becomes a slide-in overlay below lg: breakpoint (1024px).
Fixed mobile top bar with hamburger and new-chat button."
```

### Task 2: Auto-close sidebar on navigation

**Files:**
- Modify: `dashboard/src/layouts/AppLayout.tsx`

- [ ] **Step 1: Close sidebar in handleSelectConversation**

Change:

```typescript
function handleSelectConversation(id: string) {
  setActiveId(id)
  navigate(`/?c=${id}`)
}
```

To:

```typescript
function handleSelectConversation(id: string) {
  setActiveId(id)
  setSidebarOpen(false)
  navigate(`/?c=${id}`)
}
```

- [ ] **Step 2: Close sidebar in handleNewChat**

Change:

```typescript
function handleNewChat() {
  setActiveId(null)
  navigate('/')
}
```

To:

```typescript
function handleNewChat() {
  setActiveId(null)
  setSidebarOpen(false)
  navigate('/')
}
```

- [ ] **Step 3: Close sidebar on bottom nav clicks**

For each of the four bottom nav buttons (Connections, Feed, Inspector, Settings), add `setSidebarOpen(false)` to their onClick handlers. Change each from:

```typescript
onClick={() => navigate('/connections')}
```

To:

```typescript
onClick={() => { setSidebarOpen(false); navigate('/connections') }}
```

Repeat for `/feed`, `/status`, `/settings`.

- [ ] **Step 4: Type-check**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/layouts/AppLayout.tsx
git commit -m "feat(dashboard): auto-close sidebar on mobile navigation"
```

### Task 3: Touch-friendly conversation actions

**Files:**
- Modify: `dashboard/src/layouts/AppLayout.tsx`

- [ ] **Step 1: Remove hover-only opacity**

Find this line (around line 214):

```
<div className="absolute right-1 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 transition-opacity">
```

Change to:

```
<div className="absolute right-1 top-1/2 -translate-y-1/2">
```

This makes the three-dot menu always visible and tappable on touch devices. On desktop, the button is still subtle (ghost variant).

- [ ] **Step 2: Type-check and build**

Run: `cd dashboard && npx tsc --noEmit && npm run build`
Expected: No errors, build succeeds

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/layouts/AppLayout.tsx
git commit -m "fix(dashboard): make conversation actions touch-friendly

Remove hover-only visibility so dropdown menu is tappable on mobile."
```

---

## Chunk 2: Responsive Pages and Settings

### Task 4: Settings tab bar scrollable on mobile

**Files:**
- Modify: `dashboard/src/pages/SettingsPage.tsx`

- [ ] **Step 1: Make tab bar horizontally scrollable**

Change the outer tab bar container from:

```tsx
<div className="border-b border-border/40 px-6">
  <div className="max-w-3xl mx-auto flex gap-1">
```

To:

```tsx
<div className="border-b border-border/40 px-4 sm:px-6">
  <div className="max-w-3xl mx-auto flex gap-1 overflow-x-auto">
```

And add `flex-shrink-0` to each tab button. Change:

```tsx
className={`px-4 py-3 text-sm font-medium transition-colors relative ${
```

To:

```tsx
className={`px-4 py-3 text-sm font-medium transition-colors relative shrink-0 ${
```

- [ ] **Step 2: Type-check**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/SettingsPage.tsx
git commit -m "feat(dashboard): make settings tab bar scrollable on mobile"
```

### Task 5: Responsive padding for settings tabs

**Files:**
- Modify: `dashboard/src/pages/settings/GeneralSettings.tsx`
- Modify: `dashboard/src/pages/settings/SkillsTab.tsx`
- Modify: `dashboard/src/pages/settings/PromptsTab.tsx`
- Modify: `dashboard/src/pages/settings/EvolutionTab.tsx`
- Modify: `dashboard/src/pages/settings/AgentsTab.tsx`
- Modify: `dashboard/src/pages/settings/PluginsTab.tsx`

- [ ] **Step 1: Update all settings tabs**

In each of the 6 settings tab files, find the outer container div:

```
"max-w-3xl mx-auto px-6 py-6 space-y-5"
```

Replace with:

```
"max-w-3xl mx-auto px-4 sm:px-6 py-4 sm:py-6 space-y-5"
```

This applies to: GeneralSettings.tsx, SkillsTab.tsx, PromptsTab.tsx, EvolutionTab.tsx, AgentsTab.tsx, PluginsTab.tsx.

- [ ] **Step 2: Type-check**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/settings/
git commit -m "feat(dashboard): responsive padding for settings tabs"
```

### Task 6: Responsive padding for main pages

**Files:**
- Modify: `dashboard/src/pages/StatePage.tsx`
- Modify: `dashboard/src/pages/FeedPage.tsx`
- Modify: `dashboard/src/pages/ConnectionsPage.tsx`
- Modify: `dashboard/src/pages/EvolutionPage.tsx`
- Modify: `dashboard/src/pages/AgentsPage.tsx`
- Modify: `dashboard/src/pages/PluginsPage.tsx`

- [ ] **Step 1: Update all main pages**

In each of the 6 main page files, find the outer container div:

```
"max-w-4xl mx-auto px-6 py-8 space-y-6"
```

or

```
"max-w-4xl mx-auto px-6 py-8 space-y-8"
```

Replace `px-6 py-8` with `px-4 sm:px-6 py-6 sm:py-8` (keep the existing `space-y-*` value unchanged for each file):

- StatePage.tsx: `"max-w-4xl mx-auto px-4 sm:px-6 py-6 sm:py-8 space-y-6"`
- FeedPage.tsx: `"max-w-4xl mx-auto px-4 sm:px-6 py-6 sm:py-8 space-y-6"`
- ConnectionsPage.tsx: `"max-w-4xl mx-auto px-4 sm:px-6 py-6 sm:py-8 space-y-8"`
- EvolutionPage.tsx: `"max-w-4xl mx-auto px-4 sm:px-6 py-6 sm:py-8 space-y-8"`
- AgentsPage.tsx: `"max-w-4xl mx-auto px-4 sm:px-6 py-6 sm:py-8 space-y-8"`
- PluginsPage.tsx: `"max-w-4xl mx-auto px-4 sm:px-6 py-6 sm:py-8 space-y-8"`

Note: ChatPage.tsx already uses `px-4` so no change needed.

- [ ] **Step 2: Type-check and build**

Run: `cd dashboard && npx tsc --noEmit && npm run build`
Expected: No errors, build succeeds

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/StatePage.tsx dashboard/src/pages/FeedPage.tsx dashboard/src/pages/ConnectionsPage.tsx dashboard/src/pages/EvolutionPage.tsx dashboard/src/pages/AgentsPage.tsx dashboard/src/pages/PluginsPage.tsx
git commit -m "feat(dashboard): responsive padding for all main pages"
```

---

## Chunk 3: Verification

### Task 7: Final build and manual verification

**Files:** None (verification only)

- [ ] **Step 1: Full type-check**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 2: Production build**

Run: `cd dashboard && npm run build`
Expected: Build succeeds

- [ ] **Step 3: Manual test checklist**

Open the dashboard in a browser and test with DevTools device emulation:

1. **375px (iPhone SE):** Sidebar hidden, hamburger visible, tap hamburger opens sidebar overlay, tap backdrop closes it, tap conversation closes sidebar and navigates, conversation three-dot menu tappable, settings tabs scroll horizontally
2. **768px (iPad portrait):** Same behavior as mobile but roomier
3. **1024px (iPad landscape):** Sidebar always visible, hamburger hidden, collapse toggle works, current desktop behavior preserved
4. **1440px (desktop):** No visual changes from current behavior

- [ ] **Step 4: Final commit with build artifacts**

```bash
git add dashboard/dist/
git commit -m "build: rebuild dashboard with mobile responsive layout"
```
