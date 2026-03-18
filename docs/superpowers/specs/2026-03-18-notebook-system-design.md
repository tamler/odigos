# Notebook System Design (V1)

## Goal

Built-in markdown notebook with agent integration. Users create notebooks for different purposes (journal, research, creative writing, meetings). The agent reads notebook content contextually, can suggest or add entries based on collaboration level, and activates relevant skills based on notebook mode. First mode: journal with guided prompts.

## Architecture

Self-contained module, guarded by `notebooks.enabled` config flag.

```
odigos/core/notebook_store.py    # CRUD for notebooks and entries
odigos/api/notebooks.py          # REST endpoints (follows existing api/ convention)

dashboard/src/pages/
    NotebookPage.tsx             # Split view: BlockNote editor + contextual chat

skills/
    journal.md                   # Journal mode skill (Anthropic SKILL.md format)

data/notebooks/                  # Disk backup (markdown files)
migrations/038_notebooks.sql
```

## Data Model

### Migration (038)

```sql
CREATE TABLE IF NOT EXISTS notebooks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    mode TEXT DEFAULT 'general',
    collaboration TEXT DEFAULT 'read',
    share_with_agent INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notebook_entries (
    id TEXT PRIMARY KEY,
    notebook_id TEXT NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    entry_type TEXT DEFAULT 'user',
    status TEXT DEFAULT 'active',
    mood TEXT,
    metadata TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_notebook_entries_notebook ON notebook_entries(notebook_id);
CREATE INDEX IF NOT EXISTS idx_notebooks_mode ON notebooks(mode);
```

### Fields

**Notebook:**
- `mode`: general, journal, research, creative, meetings
- `collaboration`: read (agent sees only), suggest (agent proposes, user accepts), active (agent writes directly)
- `share_with_agent`: 0 = content isolated from general agent context. 1 = agent can use this notebook's content in other conversations. Default 0. User-configurable per notebook.

**Entry:**
- `entry_type`: user (written by user), agent_suggestion (pending approval), agent (accepted/auto-written), prompt (guided question from skill)
- `status`: active, pending (agent suggestion awaiting approval), accepted, rejected
- `mood`: optional emoji/text for journal entries
- `metadata`: JSON for extensible fields (tags, prompt_id, etc.)

## API Endpoints

Prefix: `/api/notebooks`

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | List all notebooks |
| POST | `/` | Create a notebook |
| GET | `/{id}` | Get notebook with entries |
| PATCH | `/{id}` | Update notebook settings (title, mode, collaboration, share) |
| DELETE | `/{id}` | Delete notebook + entries |
| POST | `/{id}/entries` | Add an entry |
| PATCH | `/{id}/entries/{entry_id}` | Update entry content or status |
| DELETE | `/{id}/entries/{entry_id}` | Delete an entry |
| POST | `/{id}/entries/{entry_id}/accept` | Accept agent suggestion |
| POST | `/{id}/entries/{entry_id}/reject` | Reject agent suggestion |

## Agent Integration

### Context assembly

When the user is chatting from the notebook page, the contextual chat passes `notebook_id` in the WebSocket message payload: `{type: "chat", content: "...", notebook_id: "..."}`. This flows through: ws.py → agent_service.handle_message(msg) → agent._run() → executor.execute() → context_assembler.build(). The `notebook_id` is carried on the `UniversalMessage.metadata` dict (existing field). `ContextAssembler.build()` reads `notebook_id` from a new keyword parameter and queries notebook content. The agent's context includes:

- The notebook's title, mode, and recent entries (last 10)
- The mode-appropriate skill is available (agent decides whether to activate)
- If `share_with_agent=0`, this notebook's content is NOT included in general conversation context

When the user is in regular chat (not on a notebook page), notebooks with `share_with_agent=1` contribute to the agent's memory via the standard RAG pipeline (entries are embedded and searchable).

### Collaboration levels

**read:** Agent sees notebook content in context when on the notebook page. Doesn't create entries. Answers questions about the content.

**suggest:** Agent can create entries with `entry_type='agent_suggestion'` and `status='pending'`. UI shows these as greyed-out blocks with accept/reject buttons. Suggestions are NOT visible in the notebook until accepted.

**active:** Agent can create entries with `entry_type='agent'` and `status='active'`. These appear immediately in the notebook. Best for modes like meetings (agent adds action items in real-time) or research (agent adds relevant citations).

### Skill activation

The agent decides whether to activate a mode-specific skill based on the notebook's mode. The mode is included in the notebook context:

```
## Active notebook: "Evening Journal" (mode: journal, collaboration: suggest)
Recent entries: ...
```

If the agent has a `journal` skill loaded, it may activate it. The skill guides behavior -- it's not forced.

## Disk Backup

On every entry save, the notebook is exported to `data/notebooks/{notebook_id}.md`:

```markdown
# Evening Journal
Mode: journal | Collaboration: suggest | Share: no

---

## 2026-03-18 20:30

What went well today?

I finally got the plugin system design figured out...

---

## 2026-03-17 21:15

What's on my mind?

Thinking about the cowork layout idea...
```

This is a plain markdown file that can be version-controlled, synced, or edited externally. The agent can also read these files via the document helpers.

## Journal Mode Skill

Following Anthropic SKILL.md format:

```markdown
---
name: journal
description: Guide reflective journaling with prompts, mood tracking, and pattern recognition
---

# Journal Mode

When the user is working in a journal notebook, guide their reflection:

## Prompts
Offer one of these prompts when the user starts a new entry (rotate, don't repeat recently used):
- What went well today?
- What's on your mind right now?
- What challenged you today and how did you handle it?
- What are you grateful for?
- What would you do differently if you could redo today?
- What are you looking forward to?

## Mood
Ask about mood at the start of each entry. Accept emoji or text. Store in the entry's mood field.

## Behavior
- Be warm and non-judgmental
- Ask follow-up questions that deepen reflection
- Don't offer unsolicited advice unless asked
- Summarize patterns when asked ("how has my mood been this week?")
- Respect privacy -- journal content is personal

## Boundaries
- Don't use journal content outside the journal context unless the user has enabled sharing
- Don't reference journal entries in other conversations
- If the user seems distressed, be supportive but suggest professional help for serious concerns
```

## Frontend: NotebookPage.tsx

Split view:
- **Left (70%):** BlockNote editor with the notebook content. Entries displayed as blocks. Agent suggestions shown with accept/reject UI.
- **Right (30%):** Contextual chat panel. Same WebSocket connection, but messages include `notebook_id` so the agent knows the context. Shows prompts, mood questions, and agent responses.

Top bar: notebook title, mode selector, collaboration toggle, share toggle.

Notebook list as a sidebar or separate list view accessible from the notebook icon.

## Config

```yaml
notebooks:
  enabled: true
```

When disabled: API endpoints return 404 (guard inside handler, matching feed.py pattern), no tab in dashboard, no notebook-related context in agent. Router is always registered (consistent with existing pattern), endpoints check the flag internally.

## Content Isolation

Default behavior: notebook content is isolated from the general agent.

- `share_with_agent=0`: entries are NOT embedded in vector memory, NOT included in general RAG, NOT used for user profile dreaming. The agent only sees this content when the user is on the notebook page.
- `share_with_agent=1`: entries ARE embedded and searchable via RAG. User profile dreaming can analyze them. The notebook's mode determines HOW the content is used (fiction content informs writing style, not factual knowledge).

The heartbeat dreaming respects this boundary -- when analyzing notebooks for patterns, it only processes notebooks with `share_with_agent=1`, and tags extracted insights with the notebook mode so fiction insights don't contaminate factual knowledge.

## Files Modified/Created

| File | Change |
|---|---|
| `migrations/038_notebooks.sql` | New: notebooks + notebook_entries tables |
| `odigos/core/notebook_store.py` | New: NotebookStore CRUD + disk backup |
| `odigos/api/notebooks.py` | New: REST endpoints (guard inside handler) |
| `odigos/config.py` | Add NotebooksConfig with enabled flag |
| `odigos/main.py` | Register notebooks router (always, guard inside) |
| `odigos/core/context.py` | Add notebook_id kwarg to build(), include notebook content |
| `odigos/core/executor.py` | Pass notebook_id from message metadata to context |
| `odigos/api/ws.py` | Pass notebook_id from WS payload to message metadata |
| `dashboard/src/pages/NotebookPage.tsx` | New: split view BlockNote editor + contextual chat |
| `dashboard/src/App.tsx` | Add notebook route |
| `dashboard/src/layouts/AppLayout.tsx` | Add notebook nav icon (when enabled) |
| `skills/journal.md` | New: journal mode skill (Anthropic SKILL.md format) |
| `data/notebooks/` | Directory for disk backups |

## Out of Scope (V1)

- Other modes (research, creative, meetings) -- journal proves the pattern
- Cowork layout (V2 -- Phase 3)
- Real-time collaboration between multiple users
- Notebook sharing/export (beyond disk backup)
- Notebook templates
- Full BlockNote customization (use defaults)
