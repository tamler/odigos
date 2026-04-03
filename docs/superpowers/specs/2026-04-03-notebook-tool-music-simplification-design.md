# Notebook Tool + Music Simplification

**Date:** 2026-04-03
**Status:** Approved
**Goal:** Give the agent write access to notebooks, eliminate the special-purpose SongEditor, and simplify music generation to a single tool that composes naturally with existing capabilities.

## Problem

1. The agent cannot write to notebooks. It can read them (via context injection) and search titles (via `search_workspace`), but has no tool to create notebooks or add entries. This means it can't fulfill basic requests like "make a note of this", "write out this recipe", or "draft lyrics for me to review".

2. Music generation uses a brittle two-tool flow (`generate_music` creates a `.song.json` draft, `submit_music` generates audio) with a custom SongEditor UI embedded in ArtifactPreview. This duplicates what notebooks already do (text editing) and requires the agent to chain two tools correctly. The SongEditor also submitted via HTTP POST to a nonexistent endpoint.

3. `search_workspace` only matches notebook/board titles. Users forget document names but remember what's in them ("the one with the cat lyrics"). Content search is missing.

## Design

### 1. Notebook Tool

**File:** `odigos/tools/notebook.py` (new)
**Name:** `manage_notebook`
**Category:** `productivity`

Single tool with an `action` parameter, matching the `manage_files` / `data_table` pattern in this codebase.

#### Parameters

```python
parameters_schema = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["create", "append", "read", "list"],
            "description": "Action to perform",
        },
        "notebook_id": {
            "type": "string",
            "description": "Notebook ID (required for append/read)",
        },
        "title": {
            "type": "string",
            "description": "Notebook title (required for create)",
        },
        "content": {
            "type": "string",
            "description": "Entry content (required for create with initial entry, and append)",
        },
        "mode": {
            "type": "string",
            "enum": ["general", "journal", "research", "creative", "meetings"],
            "description": "Notebook mode (optional, default: general)",
        },
        "limit": {
            "type": "integer",
            "description": "Max entries to return for read (default: 20)",
        },
    },
    "required": ["action"],
}
```

#### Action behaviors

**`create`** — Creates a new notebook. If `content` is provided, also creates the first entry.
- Required: `title`
- Optional: `content`, `mode` (default: `"general"`)
- Sets `collaboration: "active"`, `share_with_agent: 1` (agent-created notebooks default to full access)
- Returns: notebook ID, title, path for navigation
- Triggers markdown backup

**`append`** — Adds an entry to an existing notebook.
- Required: `notebook_id`, `content`
- Entry type: `"agent"`, status: `"active"`
- Checks collaboration mode: if `"read"`, returns error explaining the notebook is read-only
- Returns: entry ID, confirmation
- Triggers markdown backup

**`read`** — Returns entries from a notebook.
- Required: `notebook_id`
- Optional: `limit` (default: 20)
- Returns: notebook title, mode, and entries (content, entry_type, created_at) ordered chronologically
- Truncates individual entries to 2000 chars to avoid bloating agent context

**`list`** — Lists all notebooks.
- No required params
- Returns: notebook ID, title, mode, updated_at for each
- Ordered by updated_at DESC, limit 20

#### Registration

In `main.py`, register unconditionally (notebooks are a core feature):

```python
from odigos.tools.notebook import ManageNotebookTool
tool_registry.register(ManageNotebookTool(db=_db))
```

#### Backup

Every `create` (with content) and `append` action calls the existing `_backup_to_disk` logic from `odigos/api/notebooks.py`. Extract that function to a shared location (`odigos/notebooks.py` or inline in the tool) so both the API and tool can use it.

### 2. Workspace Search Enhancement

**File:** `odigos/tools/workspace_search.py` (modify)

Add content search to the existing title search. When the query doesn't match titles, also search `notebook_entries.content`.

#### Changes

```sql
-- Current: title only
SELECT id, title, updated_at FROM notebooks WHERE title LIKE ? ...

-- New: title + content fallback
-- First search titles (fast, usually sufficient)
-- Then search entry content for notebooks not already matched
SELECT DISTINCT n.id, n.title, n.updated_at, 
       SUBSTR(e.content, 1, 100) AS snippet
FROM notebook_entries e
JOIN notebooks n ON n.id = e.notebook_id
WHERE e.content LIKE ?
  AND n.id NOT IN (title_matched_ids)
ORDER BY e.updated_at DESC LIMIT 5
```

Result format for content matches includes a snippet:
```
Notebook: "Creative Ideas" (id: abc123, updated: 2026-04-01, path: /notebooks/abc123)
  Match: "...wrote lyrics about a cat who travels the world..."
```

The tool description is updated to reflect it searches content too:
```
"Search for notebooks and kanban boards by name or content."
```

### 3. Music Tool Simplification

#### Delete

- `GenerateMusicTool` class (the draft creator) from `music_gen.py`
- `SongEditor` component from `ArtifactPreview.tsx`
- `SongData` interface from `ArtifactPreview.tsx`
- `.song.json` detection logic from `ArtifactPreview.tsx`
- `useChatStore` import from `ArtifactPreview.tsx` (was only needed for SongEditor)

#### Rename and simplify

`SubmitMusicTool` becomes `GenerateMusicTool`. It no longer requires an artifact_id or reads a `.song.json` draft. Instead it accepts lyrics/style/title directly:

```python
class GenerateMusicTool(BaseTool):
    name = "generate_music"
    category = "create"
    description = (
        "Generate a music track from lyrics or a description. "
        "Returns playable audio. For lyrics review before generating, "
        "write them to a notebook first and let the user edit."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Lyrics or description of the music to generate",
            },
            "style": {
                "type": "string",
                "description": "Musical style/genre (e.g., 'indie folk, acoustic')",
            },
            "title": {
                "type": "string",
                "description": "Song title",
            },
            "instrumental": {
                "type": "boolean",
                "description": "Instrumental only, no vocals (default false)",
            },
            "vocal_gender": {
                "type": "string",
                "enum": ["", "m", "f"],
                "description": "Preferred vocal gender (m=male, f=female)",
            },
        },
        "required": ["prompt"],
    }
```

The `execute` method takes these params directly and calls `_create_task` / `_poll_result` / `_download_audio` — the same Kie.ai flow, just without the draft indirection. All the fixes from earlier this session (provider-agnostic track extraction, HTTP error handling, config-driven provider/taskType) are preserved.

#### Registration

In `main.py`, only one tool is registered instead of two:

```python
from odigos.tools.music_gen import GenerateMusicTool
tool_registry.register(GenerateMusicTool(
    api_key=music_api_key,
    provider=settings.music_generation.provider,
    task_type=settings.music_generation.task_type,
    model=settings.music_generation.model,
    max_poll_seconds=settings.music_generation.max_poll_seconds,
    db=_db,
))
```

### 4. Capabilities Update

**File:** `data/agent/capabilities.md`

Replace the music section (lines 13-19) with:

```markdown
When the user asks you to create a song, music, or soundtrack:
- If they provide lyrics or a clear description, call generate_music directly.
- If they want to review/edit lyrics first, create a notebook with the lyrics,
  tell them to edit it, and generate when they say go.
- You can read lyrics from any notebook the user points you to.
Never just write lyrics and chords -- use generate_music to produce actual audio.
```

Update the tools summary (line 55) to include notebook capabilities:

```markdown
**Notebooks:** Create and write to notebooks with manage_notebook. Use for notes,
recipes, lyrics, meeting summaries, or any content the user might want to edit.
```

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `odigos/tools/notebook.py` | Create | New manage_notebook tool |
| `odigos/tools/music_gen.py` | Rewrite | Single GenerateMusicTool, delete draft logic |
| `odigos/tools/workspace_search.py` | Modify | Add content search |
| `odigos/main.py` | Modify | Register notebook tool, simplify music registration |
| `odigos/config.py` | No change | Already updated with provider/task_type/model |
| `data/agent/capabilities.md` | Modify | New music flow, notebook capabilities |
| `dashboard/src/components/ArtifactPreview.tsx` | Modify | Remove SongEditor, SongData, .song.json handling |
| `dashboard/src/layouts/AppLayout.tsx` | Modify | Remove socketRef from ArtifactPreview (no longer needed) |

## What This Enables

Beyond music, the notebook tool gives the agent general-purpose writing:
- "Make a note of this" — creates/appends to a notebook
- "Write out this recipe" — creates a notebook with the recipe
- "Summarize our conversation" — writes to a notebook the user can revisit
- "Add this to my research notes" — finds and appends to existing notebook
- "I have lyrics in my ideas notebook" — reads and passes to generate_music

The agent becomes a companion that can both read and write to the user's workspace, not just a chat-only assistant.
