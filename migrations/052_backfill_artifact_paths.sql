-- Backfill file_path for existing artifacts that have NULL file_path

-- Generated images (in data/files/ by bare filename)
UPDATE artifacts SET file_path = 'data/files/' || filename
WHERE file_path IS NULL AND filename LIKE 'generated_%';

-- Text artifacts created by create_artifact tool (in data/artifacts/{id}/)
UPDATE artifacts SET file_path = 'data/artifacts/' || id || '/' || filename
WHERE file_path IS NULL AND length(id) > 20 AND filename NOT LIKE 'generated_%';

-- Uploads (in data/files/ with ID prefix)
UPDATE artifacts SET file_path = 'data/files/' || id || '_' || filename
WHERE file_path IS NULL AND length(id) <= 20;
