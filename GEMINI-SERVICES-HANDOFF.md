# Gemini Handoff: Services Settings UI

## Goal

Create a dedicated **Services** tab in the settings page that manages external service API keys through the unified `services` dict. Currently, service keys are only configurable via `config.yaml`. This tab puts them in the dashboard.

## Priority: MEDIUM -- unblocks features that users configure manually today

---

## What Are Services?

The backend has a `services` dict in Settings that maps service names to API keys. Adding a key auto-enables all features it powers:

| Service Key | Value Format | What It Enables |
|-------------|-------------|-----------------|
| `kie_ai` | API key | Image generation (Z-Image) + Music generation |
| `groq` | API key | Whisper STT (fast speech-to-text) |
| `brave` | API key | Brave web search |
| `google` | `api_key:cx_id` | Google Custom Search |
| `telegram` | Bot token | Telegram bot channel |
| `notebooklm` | Cookie string | NotebookLM integration |
| `searxng` | URL | SearxNG search (self-hosted) |

The backend API already handles everything: GET returns masked keys, POST accepts new/updated/removed keys. No backend changes needed.

---

## Task: Create ServicesTab.tsx

**New file:** `dashboard/src/pages/settings/ServicesTab.tsx`

### Data Flow

```
GET /api/settings → response.services = { "kie_ai": "****", "groq": "****" }
                                         (masked if configured, absent if not)

POST /api/settings { services: { "kie_ai": "new-key" } }   → sets key
POST /api/settings { services: { "kie_ai": "" } }          → removes key
POST /api/settings { services: { "kie_ai": "****" } }      → no change (masked = skip)
```

### UI Structure

One card per service, each showing:
- Service name + icon + short description of what it enables
- Status badge: "Connected" (green) if key exists, "Not configured" (muted) if absent
- A single API key input field (type="password")
- Save button per service
- Optional: "Remove" button when connected (sends empty string)

### Service Definitions (hardcode these)

```typescript
const SERVICES = [
  {
    id: 'kie_ai',
    name: 'Kie.ai',
    description: 'Image generation (Z-Image) and music generation',
    placeholder: 'Paste Kie.ai API key',
    icon: 'Sparkles',     // lucide-react
    color: 'text-violet-500',
  },
  {
    id: 'groq',
    name: 'Groq',
    description: 'Fast speech-to-text via Whisper',
    placeholder: 'Paste Groq API key',
    icon: 'Mic',
    color: 'text-orange-500',
  },
  {
    id: 'brave',
    name: 'Brave Search',
    description: 'Web search powered by Brave',
    placeholder: 'Paste Brave API key',
    icon: 'Search',
    color: 'text-orange-400',
  },
  {
    id: 'google',
    name: 'Google Search',
    description: 'Google Custom Search. Format: api_key:cx_id',
    placeholder: 'API_KEY:CX_ID',
    icon: 'Globe',
    color: 'text-blue-500',
  },
  {
    id: 'telegram',
    name: 'Telegram',
    description: 'Telegram bot channel for mobile chat',
    placeholder: 'Paste bot token from @BotFather',
    icon: 'Send',
    color: 'text-sky-500',
  },
  {
    id: 'notebooklm',
    name: 'NotebookLM',
    description: 'NotebookLM integration',
    placeholder: 'Paste NotebookLM cookie',
    icon: 'BookOpen',
    color: 'text-green-500',
  },
  {
    id: 'searxng',
    name: 'SearxNG',
    description: 'Self-hosted search. Value is the SearxNG base URL.',
    placeholder: 'https://searxng.example.com',
    icon: 'Server',
    color: 'text-teal-500',
  },
] as const
```

### Pattern to Follow

Follow the exact same pattern as IntegrationsTab.tsx (same file, `dashboard/src/pages/settings/IntegrationsTab.tsx`). Specifically:

1. **Load settings** on mount and when `active` prop changes:
   ```typescript
   const load = useCallback(async () => {
     const data = await get<{ services: Record<string, string> }>('/api/settings')
     setServices(data.services || {})
   }, [])
   ```

2. **Per-service save** -- each service has its own input + save button:
   ```typescript
   async function saveService(id: string, value: string) {
     await post('/api/settings', { services: { [id]: value } })
     toast.success(`${name} saved`)
     load() // reload to get masked value
   }
   ```

3. **Remove service** -- send empty string:
   ```typescript
   async function removeService(id: string) {
     await post('/api/settings', { services: { [id]: '' } })
     toast.success(`${name} removed`)
     load()
   }
   ```

4. **Status badge** -- check if `services[id]` exists and is non-empty:
   ```typescript
   const isConfigured = !!services[id]
   ```

### Visual Layout

```
Services
  Configure API keys for external services. Adding a key automatically
  enables all features it powers.

  +--------------------------------------------------+
  | [Sparkles icon] Kie.ai               Connected   |
  | Image generation (Z-Image) and music generation  |
  |                                                  |
  | API Key  [*************] [Save] [Remove]         |
  +--------------------------------------------------+

  +--------------------------------------------------+
  | [Mic icon] Groq                  Not configured  |
  | Fast speech-to-text via Whisper                  |
  |                                                  |
  | API Key  [Paste Groq API key   ] [Save]          |
  +--------------------------------------------------+

  ... (one card per service)
```

### Card Component

Each service card should be a `<section>` matching the IntegrationsTab style:

```
<section className="space-y-4">
  Header row: icon + name (left), status badge (right)
  Card body: rounded-lg border border-border/40 bg-card p-4 shadow-sm
    - description text (text-sm text-muted-foreground)
    - input row: Label + Input[type=password] + Save Button
    - if configured: Remove button (variant="ghost", destructive)
</section>
```

---

## Wire Into SettingsPage

**File:** `dashboard/src/pages/SettingsPage.tsx`

1. Add import:
   ```typescript
   import ServicesTab from './settings/ServicesTab'
   ```

2. Add to SECTIONS array (after 'integrations'):
   ```typescript
   { id: 'services', label: 'Services', icon: Key },
   ```
   Import `Key` from lucide-react.

3. Add render case:
   ```typescript
   {resolvedTab === 'services' && <ServicesTab active={true} />}
   ```

---

## What NOT to Do

- Do NOT modify any backend files -- the API already handles everything
- Do NOT add external dependencies
- Do NOT combine this with IntegrationsTab -- Services is its own tab
- Do NOT add "test connection" buttons -- just save the key, features auto-enable
- Do NOT show the actual key value -- always use type="password" inputs
- Do NOT create a separate API endpoint -- use existing POST /api/settings

## Technical Context

- **Framework:** React 19 + TypeScript + Vite
- **Styling:** Tailwind CSS 4, CSS variables for theming (see `dashboard/src/index.css`)
- **Icons:** lucide-react (already imported throughout)
- **UI components:** shadcn/ui pattern in `dashboard/src/components/ui/`
- **API helpers:** `import { get, post } from '@/lib/api'`
- **Toasts:** `import { toast } from 'sonner'`
- **Theme:** supports light + dark mode via CSS class on root

## Verification

- `cd dashboard && npm run build` -- must pass with no errors
- `cd dashboard && npx tsc --noEmit` -- must pass
- Test both light and dark themes
- Test on mobile viewport (375px width)
- Verify saving a key shows "Connected" badge after reload
- Verify removing a key shows "Not configured" after reload
- Verify masked values ("****") don't get sent back as the actual value

---

## Communication Log

- **[2026-04-03] Services UI Complete:** Created `ServicesTab.tsx`, wired it into `SettingsPage.tsx` and `AppLayout.tsx`. Added `Key` icon from lucide-react. Verified build and TSC.
- **[2026-04-03] Contextual Email Link:** Added "Email" link to `ChatPanel.tsx` footer with a real-time "new mail" ping indicator that syncs with `useUIStore`.
- **[2026-04-03] Build Fixes:** Fixed unused variable/import errors in `ArtifactPreview.tsx` that were blocking the production build.
