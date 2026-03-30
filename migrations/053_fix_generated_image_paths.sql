-- Fix generated images that were incorrectly placed in data/artifacts/ by migration 052
UPDATE artifacts SET file_path = 'data/files/' || filename
WHERE filename LIKE 'generated_%' AND file_path LIKE 'data/artifacts/%';
