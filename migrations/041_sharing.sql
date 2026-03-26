-- Add share_token for public link sharing
ALTER TABLE notebooks ADD COLUMN share_token TEXT;
ALTER TABLE kanban_boards ADD COLUMN share_token TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_notebooks_share_token ON notebooks(share_token) WHERE share_token IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_kanban_boards_share_token ON kanban_boards(share_token) WHERE share_token IS NOT NULL;
