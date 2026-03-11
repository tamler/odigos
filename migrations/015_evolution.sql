-- Checkpoints: snapshots of known-good agent state
CREATE TABLE IF NOT EXISTS checkpoints (
    id TEXT PRIMARY KEY,
    parent_id TEXT REFERENCES checkpoints(id),
    label TEXT,
    personality_snapshot TEXT,
    prompt_sections_snapshot TEXT,
    skills_snapshot TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Trials: time-boxed experiments on agent behavior
CREATE TABLE IF NOT EXISTS trials (
    id TEXT PRIMARY KEY,
    checkpoint_id TEXT REFERENCES checkpoints(id),
    hypothesis TEXT NOT NULL,
    target TEXT NOT NULL,
    change_description TEXT,
    status TEXT DEFAULT 'active',
    started_at TEXT DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,
    min_evaluations INTEGER DEFAULT 5,
    evaluation_count INTEGER DEFAULT 0,
    avg_score REAL,
    baseline_avg_score REAL,
    result_notes TEXT,
    direction_log_id TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_trials_status ON trials(status);

-- Trial overrides: ephemeral changes (deadman switch - never written to disk)
CREATE TABLE IF NOT EXISTS trial_overrides (
    id TEXT PRIMARY KEY,
    trial_id TEXT REFERENCES trials(id) ON DELETE CASCADE,
    target_type TEXT NOT NULL,
    target_name TEXT NOT NULL,
    override_content TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_trial_overrides_trial ON trial_overrides(trial_id);

-- Evaluations: C.1/C.2 scoring of past actions
CREATE TABLE IF NOT EXISTS evaluations (
    id TEXT PRIMARY KEY,
    message_id TEXT,
    conversation_id TEXT,
    task_type TEXT,
    rubric TEXT,
    scores TEXT,
    overall_score REAL,
    improvement_signal TEXT,
    implicit_feedback REAL,
    trial_id TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_evaluations_trial ON evaluations(trial_id);
CREATE INDEX IF NOT EXISTS idx_evaluations_created ON evaluations(created_at);

-- Rubric cache: reuse rubrics by task type
CREATE TABLE IF NOT EXISTS rubric_cache (
    task_type TEXT PRIMARY KEY,
    rubric TEXT NOT NULL,
    usage_count INTEGER DEFAULT 1,
    last_used_at TEXT DEFAULT (datetime('now'))
);

-- Failed trials log: prevent retry loops
CREATE TABLE IF NOT EXISTS failed_trials_log (
    id TEXT PRIMARY KEY,
    trial_id TEXT REFERENCES trials(id),
    hypothesis TEXT,
    target TEXT,
    change_description TEXT,
    scores_summary TEXT,
    failure_reason TEXT,
    lessons TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Direction log: agent's evolving self-assessment
CREATE TABLE IF NOT EXISTS direction_log (
    id TEXT PRIMARY KEY,
    analysis TEXT,
    direction TEXT,
    opportunities TEXT,
    hypotheses TEXT,
    confidence REAL,
    based_on_evaluations INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);
