-- Backfill file_path for existing artifacts that have NULL file_path
-- Text artifacts created by create_artifact tool (in data/artifacts/)
UPDATE artifacts SET file_path = 'data/artifacts/' || id || '/' || filename
WHERE file_path IS NULL AND length(id) > 20;

-- Uploads and generated images (in data/files/, ID prefix pattern)
UPDATE artifacts SET file_path = 'data/files/' || id || '_' || filename
WHERE file_path IS NULL AND length(id) <= 20;
