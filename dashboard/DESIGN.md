# Odigos Dashboard Design System

The visual language of the Odigos dashboard. Follow this when adding new components or pages.

## Philosophy

**AI-native developer tool.** Function over ornament. Dark-mode native. Terminal-adjacent without being cosplay-terminal. Brutalist leanings — no gradients, no decorative illustrations, restrained use of color. Information is structured by typography and whitespace, not by visual chrome.

Three-layer hierarchy on every surface:
1. **Display** — the headline action or value (largest, primary color, ~1.25rem+)
2. **Body** — the substance (default size, foreground color)
3. **Metadata** — timestamps, tags, secondary info (smallest, muted-foreground, ~0.75rem)

Don't introduce a fourth layer. If you need more separation, you're trying to fit too much on one surface.

---

## Color Tokens

All colors are defined as OKLCH CSS variables in `src/index.css`. Never hardcode hex values in components — always reference the token.

### Surface Tokens

| Token | Light | Dark | Usage |
|---|---|---|---|
| `--background` | white | near-black | Page background |
| `--foreground` | near-black | near-white | Primary text |
| `--card` | white | dark charcoal | Card surfaces |
| `--card-foreground` | near-black | near-white | Card text |
| `--popover` | white | dark charcoal | Popover/tooltip surfaces |
| `--muted` | light gray | dark gray | Muted backgrounds |
| `--muted-foreground` | gray | light gray | Secondary text, metadata |
| `--border` | light gray | white/10% | Borders, dividers |
| `--ring` | gray | gray | Focus rings |

### Action Tokens

| Token | Usage |
|---|---|
| `--primary` | Primary buttons, important UI |
| `--primary-foreground` | Text on primary surfaces |
| `--secondary` | Secondary buttons, less important UI |
| `--accent` | Hover states, subtle highlights |
| `--destructive` | Delete buttons, error states |

### Chart & Kanban

- `--chart-1` through `--chart-5`: ordered chart series colors
- `--kanban-board-circle-{blue,cyan,gray,green,indigo,pink,purple,red,violet,yellow}`: vibrant categorical colors for kanban board labels. **These are the only place we use saturated color in the UI.** Don't use them for general decoration.

### Tone Conventions

For status/severity indicators:
- **Default / info** → `bg-primary` / `text-primary`
- **Warning** → `bg-amber-500 dark:bg-amber-400`
- **Danger / error** → `bg-red-500 dark:bg-red-400` (or `bg-destructive`)
- **Success** → `bg-emerald-500 dark:bg-emerald-400`

---

## Typography

**Single font: Geist Variable.** Loaded via `@fontsource-variable/geist`. No additional fonts.

### Sizes

Use Tailwind's semantic sizes. The `chat-text` class system overrides sizing across the app via `data-chat-size` on body (`small` 13px / `medium` 15px default / `large` 17px).

| Tailwind class | Size | Usage |
|---|---|---|
| `text-xs` | 12px | Metadata, tags, timestamps |
| `text-sm` | 14px | Secondary content, captions |
| `text-base` | 16px | Body text |
| `text-lg` | 18px | Section headings |
| `text-xl` | 20px | Page sub-headings |
| `text-2xl` | 24px | Page titles |
| `text-3xl` | 30px | Hero headings (sparingly) |

**Never use** `text-4xl` and above. If something needs to be that big, it's probably wrong.

### Weight

- `font-medium` (500) is the default for emphasis. Use this for buttons, labels, headings.
- `font-semibold` (600) for stronger emphasis (page titles).
- `font-bold` (700) almost never — only for marketing surfaces, not the dashboard.
- `font-mono` (Geist Mono via Tailwind) for code, IDs, timestamps where alignment matters.

### Numbers

Use `tabular-nums` for any numeric values that may update or align in columns (counters, budgets, timestamps).

---

## Radius

Base radius is `0.625rem` (10px). All other radii are derived from this:

| Token | Value | Usage |
|---|---|---|
| `--radius-sm` | 6px | Small chips, badges |
| `--radius-md` | 8px | Default buttons, inputs |
| `--radius-lg` | 10px | Cards, dialogs |
| `--radius-xl` | 14px | Large cards |
| `--radius-2xl` | 18px | Hero cards |
| `--radius-3xl` | 22px | (rarely used) |
| `--radius-4xl` | 26px | (rarely used) |

Avoid `rounded-full` except for avatars, dot indicators, and progress fills. Pills should be `rounded-full`. Most other surfaces should respect the radius scale.

---

## Spacing

Use Tailwind's default spacing scale. No custom spacing tokens. Common patterns:

- **Card padding**: `p-4` (16px) for compact, `p-6` (24px) for default
- **Section spacing**: `space-y-4` or `space-y-6`
- **Inline gaps**: `gap-2` (8px) for tight, `gap-3` (12px) for default, `gap-4` (16px) for loose
- **Button padding**: matches existing Button variants, don't override

---

## Animation

CSS-only. We do not use a runtime animation library (no Framer Motion / Motion).

### Existing Keyframes

Defined in `src/index.css`. Reference via `animate-[<keyframe>_<duration>_<easing>_<iteration>]` in Tailwind.

| Keyframe | Duration | Usage |
|---|---|---|
| `skeleton-shimmer` | 2s | Skeleton placeholders (use `.skeleton-shimmer` class) |
| `cursor-blink` | 1s | Terminal cursors, blink indicators |
| `fluid-pulse` | 3s | Ambient breathing on orbs/blobs (`animate-fluid-pulse`) |
| `orb-glow` | 4s | Glowing voice/morph orbs |
| `float` | 6s | Vertical floating accent |
| `waveform` | 1.2s | Audio waveform bars |
| `dot-matrix` | 1.4s | Dot grid loader (used by `DotMatrixLoader`) |
| `comment-thread-expand` | — | Inline comment thread reveal |
| `suggestion-swipe-accept` | — | Accept-suggestion exit animation |
| `suggestion-swipe-reject` | — | Reject-suggestion exit animation |

`prefers-reduced-motion` is respected globally — animations are reduced to 0.01ms.

### When to add a new keyframe

Only add a new keyframe if:
1. The motion is reusable across multiple components
2. It can't be expressed with existing Tailwind utilities (`animate-pulse`, `animate-spin`, etc.)
3. It serves a functional purpose (status feedback, state transition), not decoration

---

## Loaders

Twelve variants in `src/components/ui/Loader.tsx`. Pick the one that matches the context:

| Variant | When to use |
|---|---|
| `circular` | Default for short async ops |
| `classic` | Generic spinner, fancier than circular |
| `pulse` | Ambient "in progress" indicator |
| `pulse-dot` | Single-dot pulse, very subtle |
| `dots` | Three-dot bounce, "loading..." feel |
| `typing` | Typing indicator (chat-style) |
| `wave` | Audio/voice processing |
| `bars` | Equalizer-style |
| `terminal` | Terminal cursor blink, code generation |
| `text-blink` | Blinking text label ("Thinking") |
| `text-shimmer` | Shimmer-sweep text label ("Thinking") |
| `loading-dots` | "Thinking..." with animated dots |
| `thinking` | Three blob-pulses, agent thinking indicator |
| `dot-matrix` | Grid of dots, "agent processing" indicator |

Default to `circular` for unknown cases. Reach for `thinking` or `dot-matrix` when the agent is doing background work that may take a few seconds.

---

## Components

Built on shadcn + Radix. Located in `src/components/ui/`.

### Use these directly

- `Button` — variants: `default`, `destructive`, `outline`, `secondary`, `ghost`, `link`. Sizes: `sm`, `default`, `lg`, `icon`.
- `Card` — wrapper with rounded-xl + ring. Use for grouped content.
- `Dialog` — Radix dialog wrapper.
- `Input`, `Textarea` — minimal styled inputs.
- `Tooltip`, `DropdownMenu`, `Select`, `ScrollArea` — Radix-based.
- `Loader` — see Loaders section above.
- `SegmentedProgressBar` — N-segment progress indicator with auto-toned warning/danger colors.
- `Markdown`, `CodeBlock` — Tiptap + CodeMirror integrated rendering.
- `Skeleton` — shimmer placeholder.

### Patterns

**Status badge**: small pill with colored background using one of the tone conventions.
```tsx
<span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded-sm bg-amber-500/10 text-amber-600 dark:text-amber-400">
  warning
</span>
```

**Metadata row**: muted-foreground, smallest text, gap-2.
```tsx
<div className="flex items-center gap-2 text-xs text-muted-foreground">
  <span>3 min ago</span>
  <span>·</span>
  <span>v2.1</span>
</div>
```

**Three-layer card**: display + body + metadata.
```tsx
<Card>
  <h3 className="font-semibold text-lg">Display heading</h3>
  <p className="text-sm text-muted-foreground mt-1">Body text describing the thing.</p>
  <div className="flex items-center gap-2 text-xs text-muted-foreground mt-3">
    <span>metadata</span>
  </div>
</Card>
```

---

## Don'ts

- **No gradients** in production UI. Voice orbs and decorative surfaces excepted.
- **No drop shadows** beyond `shadow-xs`. Use `ring-1` for separation.
- **No skeuomorphism**. No "physical button" effects, no embossed text.
- **No emoji in interface chrome**. Lucide icons only. Emoji is fine in user content.
- **No new fonts**. Geist only.
- **No animation library**. CSS keyframes only.
- **No hardcoded colors**. Always reference CSS variables or Tailwind tokens.
- **No `text-4xl`+ headings** in dashboard surfaces.
