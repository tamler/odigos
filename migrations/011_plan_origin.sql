-- Track who created a plan: 'user' (from chat), 'agent' (proactive), 'approved' (user approved proposal)
ALTER TABLE task_plans ADD COLUMN origin TEXT DEFAULT 'user';
