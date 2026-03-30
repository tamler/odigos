-- Store the actual file path on artifacts so we stop guessing
ALTER TABLE artifacts ADD COLUMN file_path TEXT;
