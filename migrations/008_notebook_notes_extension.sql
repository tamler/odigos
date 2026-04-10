-- Add review sidecar columns to notebook_entries
ALTER TABLE notebook_entries ADD COLUMN quote TEXT;
ALTER TABLE notebook_entries ADD COLUMN trigger_type TEXT;
ALTER TABLE notebook_entries ADD COLUMN viewed_at TEXT;
ALTER TABLE notebook_entries ADD COLUMN parent_id TEXT REFERENCES notebook_entries(id);

-- Add review tracking to notebooks
ALTER TABLE notebooks ADD COLUMN last_reviewed_at TEXT;
