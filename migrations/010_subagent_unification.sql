-- Unify the old SubagentManager (subagent_tasks table + spawn_subagent tool)
-- with the new run_subagent pipeline. All sub-agent work now lives in the
-- unified tasks table with type='subagent'.

-- Add delivered_at column for peer delivery tracking (was on subagent_tasks)
ALTER TABLE tasks ADD COLUMN delivered_at TEXT;

-- Drop the old parallel table
DROP TABLE IF EXISTS subagent_tasks;

-- Note: any in-flight rows in subagent_tasks are lost on migration.
-- This is acceptable because the old system was broken (pre-existing
-- failing tests) and not reliably delivering results in production.
