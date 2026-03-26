-- Fitness functions: user-defined optimization targets
CREATE TABLE IF NOT EXISTS fitness_functions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    metric TEXT NOT NULL,          -- what to measure: "response_speed", "recall_accuracy", "user_satisfaction", etc.
    target_score REAL,             -- goal score (NULL = no specific target, just improve)
    current_score REAL DEFAULT 0,
    weight REAL DEFAULT 1.0,       -- relative importance when multiple functions exist
    enabled INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Trial patterns: success/failure learning from past trials
CREATE TABLE IF NOT EXISTS trial_patterns (
    id TEXT PRIMARY KEY,
    trial_id TEXT NOT NULL,
    pattern_type TEXT NOT NULL CHECK (pattern_type IN ('success', 'failure')),
    target TEXT NOT NULL,          -- what was changed: "prompt_section", "routing_rule", "new_skill"
    target_name TEXT,              -- which specific target
    hypothesis TEXT NOT NULL,
    score_delta REAL,              -- how much the score changed
    context TEXT,                  -- JSON: evaluation summary at time of trial
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_trial_patterns_type ON trial_patterns(pattern_type);

-- Evolution operating mode
-- Stored in agent_meta table (key: "evolution_mode", value: "continuous"|"converge"|"supervised")
