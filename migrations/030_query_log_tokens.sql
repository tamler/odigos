ALTER TABLE query_log ADD COLUMN context_tokens INTEGER;
ALTER TABLE query_log ADD COLUMN response_tokens INTEGER;
ALTER TABLE query_log ADD COLUMN total_tokens INTEGER;
