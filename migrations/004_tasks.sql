-- tasks table is now defined in the initial schema (001_initial.sql / schema.sql)
-- scheduled_at, priority, payload_json, started_at, recurrence_json, created_by columns
-- were removed in the schema rewrite; schema.sql defines the canonical task columns.
SELECT 1; -- no-op placeholder so migration is recorded
