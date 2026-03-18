# Kanban Board Design (V1)

## Goal

Shared kanban board between user and agent. User creates boards, manages cards. Agent has full read/write via tools. Boards are a communication and status view -- the user asks the agent to do things, the agent moves cards as work progresses. V1 is standalone; future versions link cards to goals/todos/plans.

## Architecture

Self-contained module, guarded by `kanban.enabled` config flag. Uses `ResourceStore` for CRUD (same as notebooks). Frontend uses `shadcn-kanban-board` component (already installed, zero-dependency drag-and-drop with keyboard accessibility).

```
odigos/api/kanban.py            # REST endpoints (uses require_feature("kanban"))
migrations/039_kanban.sql       # boards, columns, cards tables

dashboard/src/pages/KanbanPage.tsx   # Board list + board detail with drag-and-drop

skills/kanban.md                # Optional skill for agent kanban behavior
```

No new core module needed -- ResourceStore handles all storage. Notebook-specific logic (like disk backup) lives in the API layer; kanban-specific logic (like default columns, position management) lives in `kanban.py`.

## Data Model

### Migration (039)

```sql
CREATE TABLE IF NOT EXISTS kanban_boards (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kanban_columns (
    id TEXT PRIMARY KEY,
    board_id TEXT NOT NULL REFERENCES kanban_boards(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kanban_cards (
    id TEXT PRIMARY KEY,
    board_id TEXT NOT NULL REFERENCES kanban_boards(id) ON DELETE CASCADE,
    column_id TEXT NOT NULL REFERENCES kanban_columns(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    position INTEGER NOT NULL DEFAULT 0,
    priority TEXT DEFAULT 'medium',
    due_at TEXT,
    metadata TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_kanban_columns_board ON kanban_columns(board_id);
CREATE INDEX IF NOT EXISTS idx_kanban_cards_board ON kanban_cards(board_id);
CREATE INDEX IF NOT EXISTS idx_kanban_cards_column ON kanban_cards(column_id);
```

### Fields

**Board:** title + description. Simple container.

**Column:** title + position (integer for ordering). FK to board with cascade delete.

**Card:** title, description, position (integer within column), priority (low/medium/high/urgent), due_at (optional ISO datetime), metadata (JSON text for extensible fields like tags, links, assignee).

### Default Columns

When a board is created, auto-generate 4 columns:
- Backlog (position 0)
- Todo (position 1)
- In Progress (position 2)
- Done (position 3)

## API Endpoints

Prefix: `/api/kanban`

| Method | Path | Purpose |
|---|---|---|
| GET | `/boards` | List all boards |
| POST | `/boards` | Create a board (auto-creates default columns) |
| GET | `/boards/{id}` | Get board with columns and cards |
| PATCH | `/boards/{id}` | Update board title/description |
| DELETE | `/boards/{id}` | Delete board (cascades to columns + cards) |
| POST | `/boards/{id}/columns` | Add a column |
| PATCH | `/boards/{id}/columns/{col_id}` | Update column title or position |
| DELETE | `/boards/{id}/columns/{col_id}` | Delete column (cascades cards) |
| POST | `/boards/{id}/cards` | Create a card in a column |
| PATCH | `/boards/{id}/cards/{card_id}` | Update card fields (title, description, column_id, position, priority, due_at) |
| DELETE | `/boards/{id}/cards/{card_id}` | Delete a card |
| POST | `/boards/{id}/cards/{card_id}/move` | Move card to column + position (convenience endpoint for drag-drop) |
| PATCH | `/boards/{id}/reorder` | Bulk reorder columns and/or cards (batch position updates) |

### Move endpoint

`POST /boards/{id}/cards/{card_id}/move` accepts `{column_id, position}`. Updates the card's `column_id` and `position`, then reorders sibling cards in both the source and target columns to fill gaps. This is the primary endpoint the drag-and-drop frontend calls.

### Reorder endpoint

`PATCH /boards/{id}/reorder` accepts `{columns?: [{id, position}], cards?: [{id, column_id, position}]}`. Batch updates positions for multiple items. Used when the user reorders columns or does complex multi-card moves.

## Agent Integration

The agent gets two tools:

**KanbanTool** -- A single tool with actions:
- `list_boards` -- list all boards
- `get_board {board_id}` -- get board with all columns and cards
- `create_card {board_id, column_id, title, description?, priority?}` -- add a card
- `move_card {board_id, card_id, column_id, position?}` -- move a card between columns
- `update_card {board_id, card_id, ...fields}` -- update card fields
- `delete_card {board_id, card_id}` -- remove a card

The tool calls the same ResourceStore layer that the API uses. No separate code path.

### Context assembly

When the user is chatting from the kanban page, the contextual chat passes `{context: {board_id: "abc"}}` via the same `context_metadata` mechanism built for notebooks. `ContextAssembler.build()` checks for `context_metadata.get("board_id")` and includes the board's title, columns, and card summaries in the system prompt.

When not on the kanban page, boards are not included in general context (same isolation pattern as notebooks with `share_with_agent=0`). V2 can add a `share_with_agent` flag to boards.

## Frontend: KanbanPage.tsx

Two views, same pattern as NotebookPage:

### Board list (`/kanban`)
- List of boards with title, description snippet, card count
- Create board button (title input)
- Delete board button

### Board detail (`/kanban/:id`)
- Uses `shadcn-kanban-board` component (already installed at `src/components/kanban.tsx`)
- Columns rendered as `KanbanBoardColumn`, cards as `KanbanBoardCard`
- Drag-and-drop cards between columns (calls `POST /move` on drop)
- Drag-and-drop columns to reorder (calls `PATCH /reorder` on drop)
- Add card inline (title input at bottom of column)
- Card click opens detail view (inline expand or modal) for editing description, priority, due date
- Add/remove columns
- Back button to board list
- Top bar: board title, editable

### No contextual chat panel in V1
Unlike notebooks, kanban boards don't need a side chat panel in V1. The user interacts with the agent through the main chat. The `board_id` context metadata is wired but the chat panel is deferred to the cowork layout (Phase 3).

## Config

```yaml
kanban:
  enabled: true
```

Same pattern as notebooks: `require_feature("kanban")` on the router, `KanbanConfig` in config.py.

## Files Modified/Created

| File | Change |
|---|---|
| `migrations/039_kanban.sql` | New: boards, columns, cards tables |
| `odigos/api/kanban.py` | New: REST endpoints using ResourceStore + require_feature |
| `odigos/tools/kanban.py` | New: KanbanTool for agent read/write |
| `odigos/config.py` | Add KanbanConfig with enabled flag |
| `odigos/main.py` | Register kanban router, register KanbanTool |
| `odigos/core/context.py` | Add board_id check in context_metadata block |
| `dashboard/src/pages/KanbanPage.tsx` | New: board list + board detail with drag-drop |
| `dashboard/src/App.tsx` | Add kanban routes |
| `dashboard/src/layouts/AppLayout.tsx` | Add kanban nav icon |
| `skills/kanban.md` | New: kanban mode skill |

## Out of Scope (V1)

- Linking cards to goals/todos/task plans (V2 -- C approach)
- share_with_agent flag on boards
- Card labels/tags UI (stored in metadata, no UI yet)
- Card assignee (single user system for now)
- Contextual chat panel on board page (Phase 3 cowork layout)
- Card comments/activity log
- Board templates
