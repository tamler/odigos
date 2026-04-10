# Gemini Handoff: Visual Polish -- Loading Animation + Voice Orb

## Goal
Make the chat loading state and voice mode orb feel premium and polished. These are high-visibility elements that define perceived quality.

## Priority: HIGH -- these are the most visible UI interactions

---

## Task 1: Chat Thinking/Loading Animation

**File:** `dashboard/src/components/ChatPanel.tsx`

**Current state (lines ~570-580):**
Three bouncing dots with muted foreground color + status text ("Thinking...", "Generating..."). Basic and functional but feels generic.

**What we want:**
- A smooth, elegant thinking indicator that feels like intelligence is working
- Should have distinct visual phases:
  1. **Thinking** (before streaming): the primary indicator, should feel contemplative
  2. **Generating** (during streaming, below content): subtle, secondary
- Animation should be smooth/fluid, not choppy or aggressive
- Must work on both light and dark themes
- Must look good on mobile

**Design direction:**
- Consider a gentle wave or breathing animation rather than bouncing dots
- The status text should feel integrated, not tacked on
- Look at how ChatGPT, Claude.ai, or Perplexity handle their thinking states for inspiration
- Keep it minimal -- no skeletons, no shimmer effects on fake content
- The Loader component at `dashboard/src/components/ui/loader.tsx` has 13+ variants you can use or modify

**Constraints:**
- No external animation libraries (no framer-motion, no lottie)
- CSS/Tailwind animations only
- Must not cause layout shift when appearing/disappearing

---

## Task 2: Voice Orb Polish

**File:** `dashboard/src/components/VoiceOrb.tsx`

**Current state:**
A 128px circular button with color-coded states (primary=listening, blue=processing, purple=thinking, emerald=speaking). Has basic amplitude rings that expand during listening. Uses Lucide icons inside.

**What we want:**
- Premium, fluid orb that feels alive and responsive
- Amplitude visualization during listening should be organic and mesmerizing, not just two expanding circles
- The orb should breathe/pulse subtly even when idle
- Transitions between states should be smooth, not abrupt color swaps
- Speaking state should visualize audio output (waveform-like, not just a static speaker icon)
- The glow effect behind the orb should feel volumetric and natural

**Design direction:**
- Think Apple Siri orb, Google Assistant orb, or the Humane AI pin light
- The amplitude rings could be multiple layers with different speeds/delays
- Consider gradient transitions between state colors instead of hard swaps
- The inner icon should have subtle animation per state (breathing mic, pulsing waves, etc.)
- Canvas-based is fine for the amplitude visualization if CSS alone isn't smooth enough

**Constraints:**
- No external animation libraries
- CSS/Tailwind + possibly canvas for amplitude viz
- Must be performant on mobile (no jank at 60fps)
- The `useVoiceMode` hook at `dashboard/src/hooks/useVoiceMode.ts` provides `amplitude` (0-1 float) at ~60fps via `onAmplitudeChange`
- Voice phases: idle, listening, processing, thinking, speaking

---

## Task 3: Mobile Header New Chat Button

**File:** `dashboard/src/layouts/AppLayout.tsx`

**Already done -- just verify it looks right:**
The empty div placeholder on the mobile header (right side) has been replaced with a `<Button>` that calls `handleNewChat`. Just make sure the + icon is visually balanced with the hamburger menu on the left.

---

## Technical Context

- **Framework:** React 19 + TypeScript + Vite
- **Styling:** Tailwind CSS 4, CSS variables for theming (see `dashboard/src/index.css`)
- **Icons:** lucide-react
- **UI components:** shadcn/ui pattern in `dashboard/src/components/ui/`
- **Theme:** supports light + dark mode via CSS class on root
- **Build:** `cd dashboard && npm run build` -- must pass with no errors
- **Type check:** `cd dashboard && npx tsc --noEmit` -- must pass

## Testing
- Check both light and dark themes
- Test on mobile viewport (375px width)
- Voice orb: test all 5 states visually (can mock with state controls)
- Loading: send a message and observe the thinking → streaming transition
- Verify no layout shift when indicators appear/disappear
