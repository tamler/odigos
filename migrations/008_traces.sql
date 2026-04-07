-- traces table is now defined in schema.sql with created_at instead of timestamp
-- action_log was dropped; both are handled by schema.sql
DROP TABLE IF EXISTS action_log;
