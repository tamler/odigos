# Notebook Review Sidecar (Odigos Workspace Phase 1)

**Date:** 2026-04-10
**Status:** Approved
**Group:** 3 (UI) — Odigos Workspace, Phase 1 of 3

## Research References

- [AnchoredAI](https://arxiv.org/html/2509.16128v1) — Inspiration for agent comments anchored to specific text via quoted references
- [jot](https://github.com/badlogic/jot) — Inline comment threads pattern (humans + agents participate)
- Existing Odigos notebook system — `notebook_entries` table + `_backup_to_disk` pattern

---

## Goal

Give the user an interactive surface where the agent can proactively comment on their notebook writing. The agent reads the notebook during heartbeat idle phases, adds anchored observations referencing specific quoted text, and the user sees those observations in a sidebar panel next to the document. The user can reply (their reply becomes a journal entry), mark observations as resolved ("dead"), and jump from a quote back to the source location in the document.

**Phase 1 scope:** notebook-only, agent-initiated via heartbeat, user replies via existing journal input. Extends the existing `notebook_entries` table rather than introducing a parallel system.

---

## Unification Principle

Before building anything new, check if an existing system can absorb it. This feature does NOT introduce a new table or new store module. It extends:

- `notebook_entries.entry_type='agent'` — already exists, was previously unused for reviews
- `_backup_to_disk()` — existing function, now writes a second sidecar file
- Existing notebook API endpoints — extended with new query params, no new routes
- Existing `AgentInputBar` — reused for replies, no new reply component

The only genuinely new pieces are (1) three columns on `notebook_entries`, (2) one heartbeat phase function, (3) one LLM prompt, (4) three frontend components.

---

## Section 1: Data Model

### Schema Changes

```sql
-- Add to existing notebook_entries table
ALTER TABLE notebook_entries ADD COLUMN quote TEXT;
ALTER TABLE notebook_entries ADD COLUMN trigger_type TEXT;
ALTER TABLE notebook_entries ADD COLUMN viewed_at TEXT;

-- Add to existing notebooks table
ALTER TABLE notebooks ADD COLUMN last_reviewed_at TEXT;
```

Migration: `migrations/008_notebook_notes_extension.sql`

### Field Semantics

**Existing `entry_type` values (no schema change, just conventions):**
- `user` — user's primary writing (unchanged)
- `agent` — proactive review comment, appears in sidebar panel
- `agent_suggestion` — editable suggestion (Phase 2+, unchanged behavior)

**Existing `status` values:**
- `active` — visible
- `rejected` — user rejected an agent_suggestion
- `dead` — NEW: user archived an agent review comment

**New fields:**
- `quote` (TEXT, nullable) — text from the notebook that the agent is commenting on. Only populated for `entry_type='agent'`.
- `trigger_type` (TEXT, nullable) — why the entry was created: `heartbeat`, `on-demand`, `scheduled`, `reply`. NULL for normal user entries.
- `viewed_at` (TEXT, nullable) — when the user last viewed this entry. Drives unread indicators.

### Notebook Backup File Split

`_backup_to_disk()` in `odigos/api/notebooks.py` now writes two files:

**`data/notebooks/{id}.md`** (existing, user's journal):
- Contains only entries with `entry_type='user'` and `entry_type='agent_suggestion'`
- Format unchanged: title + metadata header + entries separated by `---`

**`data/notebooks/{id}.note.md`** (new, agent review sidecar):
- Contains only entries with `entry_type='agent'` AND `status IN ('active', 'dead')`
- Sorted newest first
- Format:
  ```markdown
  ---
  file: data/notebooks/{id}.md
  title: {notebook title}
  updated: {iso timestamp}
  entries: {count}
  active: {active count}
  dead: {dead count}
  ---

  ## Contents

  1. [2026-04-10 14:46 · agent] Short body preview...
  2. ~~[2026-04-10 14:32 · agent] Older dead one~~ (dead)

  ---

  ## 2026-04-10T14:46:12Z · agent · heartbeat

  > "quoted text from the notebook"

  Body of the agent's observation.

  ---

  ## 2026-04-10T14:32:00Z · agent · heartbeat <dead/>

  > "older quoted text"

  Older observation, marked dead.
  ```

- If no agent entries exist, delete the `.note.md` file (no orphans)
- Same best-effort error handling as existing backup — log warning, don't raise

---

## Section 2: Backend API

Extends existing `/api/notebooks` endpoints. No new routes for the core flow.

### Extended query on entries list

```
GET /api/notebooks/{id}/entries
    ?entry_type=agent              # optional, filter by type
    &include_dead=false            # optional, include status='dead' entries
    &unread_only=false             # optional
-> { "entries": [NotebookEntry, ...], "unread_count": int }
```

The existing endpoint already returns entries; the additions are the query params and the `unread_count` in the response payload. `unread_count` is computed as `COUNT WHERE entry_type='agent' AND viewed_at IS NULL AND status='active'`.

### Extended POST for creating agent entries

```
POST /api/notebooks/{id}/entries
    body: {
      content: string,
      entry_type: "user" | "agent" | "agent_suggestion",
      quote?: string,
      trigger_type?: string,
      mood?: string,
    }
-> NotebookEntry
```

Existing handler; adds passthrough for the new fields. After insert, calls the extended `_backup_to_disk()` which writes both files.

### New endpoints for view tracking

```
POST /api/notebooks/{id}/entries/{entry_id}/view
-> { "ok": true }

POST /api/notebooks/{id}/mark-all-viewed?entry_type=agent
-> { "ok": true, "marked": int }
```

Both update `viewed_at = datetime('now')` for matching rows.

### Status toggle (for "dead" marking)

Uses existing `PATCH /api/notebooks/{id}/entries/{entry_id}` with `{"status": "dead"}` or `{"status": "active"}` in the body. Existing handler accepts status updates. After update, triggers backup.

### NotebookEntry Response Schema

```typescript
interface NotebookEntry {
  id: string
  notebook_id: string
  content: string
  entry_type: 'user' | 'agent' | 'agent_suggestion'
  status: 'active' | 'rejected' | 'dead'
  quote: string | null
  trigger_type: string | null
  mood: string | null
  metadata: Record<string, unknown> | null
  viewed_at: string | null
  created_at: string
}
```

The frontend derives `is_unread = entry_type === 'agent' && !viewed_at && status === 'active'`.

---

## Section 3: Heartbeat Review

### Module: `odigos/core/heartbeat/notes_review.py`

```python
REVIEW_INTERVAL_HOURS = 24
MAX_NOTEBOOKS_PER_CYCLE = 1
MIN_CONTENT_CHARS = 500
MAX_ACTIVE_NOTES_PER_NOTEBOOK = 10


async def review_notebooks(hb) -> int:
    """Phase 9.6: scan shared notebooks, review stale ones, add anchored notes.

    Returns number of notebooks reviewed (0 or 1).
    """
```

### Flow

1. Find the oldest `share_with_agent=true` notebook with `last_reviewed_at IS NULL OR last_reviewed_at < datetime('now', '-24 hours')`. LIMIT 1.
2. Skip if notebook has < 500 chars of user content (nothing to say).
3. Count existing active agent notes on the notebook. Skip if >= 10 (avoid spam).
4. Load user entries + existing agent notes (for the "don't repeat yourself" context).
5. Call LLM with `data/prompts/notebook_review.md` prompt using `background_model`.
6. Parse response JSON: `{"observations": [{"quote": str, "comment": str}, ...]}`.
7. For each observation:
   - Validate the quote appears in the notebook content (skip hallucinated quotes)
   - INSERT a new notebook_entry with `entry_type='agent'`, `trigger_type='heartbeat'`, `quote=...`, `content=comment`, `status='active'`
8. After the batch, call `_backup_to_disk()` to regenerate both files.
9. UPDATE `notebooks SET last_reviewed_at = datetime('now') WHERE id = ?`.
10. For each observation, publish a WebSocket message `{type: 'note_added', notebook_id, entry_id}` via the existing message bus.
11. For each observation, create a notification via the existing notification store: `{type: 'suggestion', title: f'Agent reviewed {notebook_title}', body: comment[:200], metadata: {notebook_id, entry_id}}`.
12. Return 1.

### Cost control

- Maximum 1 review per heartbeat cycle
- Minimum 24h between reviews of the same notebook
- Skip if content is too short or already has 10+ notes
- Uses `background_model` config (cheaper than default)
- Gated inside `run_evolution()` alongside other evolution work — only runs when idle and budget allows

### Review Prompt

`data/prompts/notebook_review.md`:

```markdown
You are a thoughtful reviewer for a user's personal notebook. Read the notebook
content and surface observations that might be useful to the user.

## Rules

- Focus on patterns, contradictions, and connections to things you know about the user
- Quote specific text when commenting. Never make a comment without anchoring.
- Maximum 3 observations per review. Quality over quantity.
- Do NOT comment on typos, style, grammar, or spelling.
- Do NOT repeat observations you've already made (listed below).
- Do NOT make judgmental comments. Be a helpful peer, not a critic.
- If nothing is worth saying, return an empty list.

## Existing agent notes on this notebook

{existing_notes_summary}

## Notebook content

{notebook_content}

## Output

Return valid JSON only, no markdown fences:

{{"observations": [{{"quote": "exact text from the notebook", "comment": "your observation"}}]}}

If nothing is worth noting, return {{"observations": []}}.
```

### Heartbeat Integration

In `odigos/core/heartbeat/orchestrator.py`, new phase after memory evolution (Phase 9.5), before outcome evaluation (Phase 10):

```python
# Phase 9.6: Notebook review
if hasattr(self, "notes_review_enabled") and self.notes_review_enabled:
    try:
        self.current_phase = "notebook_review"
        self.current_activity = "Reviewing shared notebooks"
        reviewed = await notes_review.review_notebooks(self)
        if reviewed > 0:
            logger.info("Notebook review: %d notebook(s) reviewed", reviewed)
    except Exception:
        logger.debug("Notebook review failed", exc_info=True)
    finally:
        self.current_phase = None
        self.current_activity = None
```

---

## Section 4: Frontend — NoteSidecar

### Component Tree

```
dashboard/src/components/notes/
  NoteSidecar.tsx            # Main panel — list + fetch + WebSocket subscription
  NoteEntry.tsx              # Single agent note card with quote + body + actions
  NoteTableOfContents.tsx    # Collapsible TOC at the top
```

### `NoteSidecar.tsx`

```typescript
interface NoteSidecarProps {
  notebookId: string
  onQuoteClick?: (quote: string) => void
  onReplyClick?: (quote: string) => void
}
```

Responsibilities:
- Fetches agent entries via `GET /api/notebooks/{id}/entries?entry_type=agent&include_dead={showDead}`
- Subscribes to WebSocket `note_added` messages for this notebook; refetches on match
- Renders:
  - Header: "Notes" title, unread count badge, "show dead" toggle, mark-all-viewed button
  - `NoteTableOfContents` (collapsed by default)
  - Scrollable list of `NoteEntry` components, newest first
- Auto-marks entries as viewed when scrolled into view (IntersectionObserver, 500ms delay, matches ActivityFeedSection pattern)
- Empty state: "The agent hasn't reviewed this notebook yet. Share with agent and it will review during idle time."
- Loading state: skeleton placeholders

### `NoteEntry.tsx`

Renders:
- **Header line:** time (relative), author `agent`, trigger badge (`heartbeat`, `on-demand`), unread dot if unread, status badge if dead
- **Quote block:** `>` styled quote, clickable — calls `onQuoteClick(quote)` to scroll the main editor to that text and highlight it
- **Body:** rendered via `<Markdown>` component
- **Actions:** "Reply" (calls `onReplyClick(quote)` to prefill the main AgentInputBar), "Mark dead" or "Mark active" (toggles status via PATCH), collapse/expand (dead entries collapse by default)
- **Styling:** `border-l-2 border-l-purple-400` for agent entries, dimmed for dead entries

### `NoteTableOfContents.tsx`

- Collapsed by default, shows summary line: `"3 notes · 1 dead"`
- Click to expand
- Expanded: numbered list, each item has `[HH:MM · author] {first 60 chars}`, strikethrough for dead
- Click item → scrolls entry into view + flashes highlight

### Integration with `NotebookPage.tsx`

Changes:
1. New state: `showNotes: boolean` — default `true` if `unread_count > 0` on initial fetch, otherwise `false`
2. New state: `selectedQuote: string | null` — tracked via text selection handler on the editor
3. New state: `replyPrefill: string | null` — set when user clicks "Reply" on a note
4. Header adds: `[Notes (3)]` button with unread count, toggles `showNotes`
5. Layout: when `showNotes=true`, split 60/40 between editor and NoteSidecar; otherwise full-width editor
6. `AgentInputBar` receives `prefill={replyPrefill}` — when non-null, input starts with a markdown quote block of the referenced text
7. Keyboard shortcut `Cmd+Shift+N` toggles the panel

```tsx
<div className="flex h-full">
  <div className={showNotes ? "flex-1 min-w-0" : "w-full"}>
    <MarkdownEditor ... onSelectionChange={setSelectedQuote} />
  </div>
  {showNotes && (
    <div className="w-[40%] border-l border-border overflow-y-auto">
      <NoteSidecar
        notebookId={notebookId}
        onQuoteClick={handleQuoteClick}
        onReplyClick={handleReplyClick}
      />
    </div>
  )}
</div>
```

### Quote-click jump behavior

```typescript
function handleQuoteClick(quote: string) {
  const content = editor.getText()
  const idx = content.toLowerCase().indexOf(quote.toLowerCase())
  if (idx === -1) {
    toast('Quoted text no longer in document')
    return
  }
  editor.commands.focus()
  editor.commands.setTextSelection({ from: idx + 1, to: idx + 1 + quote.length })
  // Use a one-shot CSS class for highlight fade
  // ...scroll into view
}
```

Best-effort, case-insensitive first match. If the text has changed, show a toast. No Tiptap decoration extension needed.

### WebSocket integration

The existing message bus gets a new message type:

```typescript
{ type: 'note_added', notebook_id: string, entry_id: string }
```

- Backend emits from the notes_review phase after each entry insert
- `NoteSidecar` subscribes via the existing notification WebSocket connection
- On matching `notebook_id`, triggers a refetch

### `notificationStore.ts` change

Handle the new `note_added` message type alongside existing notification types. It surfaces as a normal notification with `metadata.notebook_id` and `metadata.entry_id` so clicking "Discuss" navigates back to the notebook with the sidecar open.

---

## Section 5: New/Modified Files

### New Files

| File | Type | Purpose |
|------|------|---------|
| `migrations/008_notebook_notes_extension.sql` | Migration | Add quote/trigger_type/viewed_at, last_reviewed_at |
| `odigos/core/heartbeat/notes_review.py` | Module | `review_notebooks()` heartbeat phase |
| `data/prompts/notebook_review.md` | Prompt | LLM review prompt |
| `dashboard/src/components/notes/NoteSidecar.tsx` | Component | Main panel |
| `dashboard/src/components/notes/NoteEntry.tsx` | Component | Single entry card |
| `dashboard/src/components/notes/NoteTableOfContents.tsx` | Component | Collapsible TOC |
| `tests/test_notebook_review.py` | Test | Heartbeat review logic + gating |
| `tests/test_notebooks_notes.py` | Test | New query params + view endpoints + split backup |

### Modified Files

| File | Change |
|------|--------|
| `schema.sql` | Add columns to notebook_entries and notebooks |
| `odigos/api/notebooks.py` | Extend entries list with query params, add view endpoints, split `_backup_to_disk` into user file + note file |
| `odigos/core/heartbeat/orchestrator.py` | Add Phase 9.6: notes review |
| `odigos/core/heartbeat/maintenance.py` | Wire notes review into run_evolution if not already |
| `odigos/bootstrap.py` | Set `heartbeat.notes_review_enabled = True` |
| `dashboard/src/pages/NotebookPage.tsx` | Split-view toggle, text selection tracking, reply prefill, NoteSidecar integration |
| `dashboard/src/components/AgentInputBar.tsx` | Accept optional `prefill` prop |
| `dashboard/src/stores/notificationStore.ts` | Handle `note_added` WebSocket message |

### Deliberately NOT in Phase 1

- External edits to `.note.md` syncing back to DB
- Comment threads (parent/child relationships)
- Accept/reject workflow for agent_suggestion (that's its own existing flow)
- Agent editing the main document (not just adding notes)
- Inline autocomplete / writing assistance while typing
- Support for brain files and non-notebook documents
- Generic `document_notes` table — defer to Phase 3 when multi-file-type needs justify it
- `add_note` agent tool — heartbeat writes directly, user-invoked notes come in Phase 2
- Cross-notebook search of agent notes
- Purge dead notes older than N days

---

## Testing Scope

**Backend:**
- `test_notebooks_notes.py`: new query params filter correctly, view endpoints update viewed_at, POST supports new fields, `_backup_to_disk` writes both files correctly
- `test_notebook_review.py`: review skips notebooks < 500 chars, skips notebooks with 10+ notes, respects 24h interval, inserts entries with correct fields, regenerates backup, publishes WebSocket events

**Frontend:** manual smoke test + type check + build. No unit tests (matches existing dashboard pattern).

---

## Success Metrics

This feature is successful if:
- Users with `share_with_agent=true` notebooks see at least one agent observation per day
- The observations are actually read (viewed_at populated within 24h of creation)
- The observations lead to follow-up action (user replies, marks done, or edits the notebook) in > 30% of cases
- No user reports unwanted spam or surprise content additions
