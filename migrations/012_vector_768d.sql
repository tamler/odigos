-- Migrate vector table from 1536-d (OpenRouter API) to 768-d (local nomic-embed-text-v1.5)
-- sqlite-vec virtual tables cannot be ALTERed, so we drop and recreate.
-- Existing vectors become invalid with the new model and must be re-embedded.
DROP TABLE IF EXISTS memory_vectors;
