-- Odigos Database Schema (consolidated)
-- Version: 1
--
-- This is the single source of truth for the database schema.
-- On fresh install, this file creates everything needed.
-- On existing databases, migrations still apply incrementally.
--
-- Tables grouped by domain. All CREATE statements are IF NOT EXISTS
-- so this file is safe to run on an existing database.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
PRAGMA cache_size = -65536;

-- ════════════════════════════════════════════════════════════════════
-- CONVERSATIONS & MESSAGES
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS conversations (
    id              TEXT PRIMARY KEY,
    title           TEXT,
    channel         TEXT NOT NULL,
    status          TEXT DEFAULT 'active',
    message_count   INTEGER DEFAULT 0,
    last_message_at TEXT,
    category        TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    parent_conversation_id TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    role            TEXT NOT NULL,
    content         TEXT,
    channel         TEXT,
    message_type    TEXT DEFAULT 'chat',
    model_used      TEXT,
    tokens_in       INTEGER,
    tokens_out      INTEGER,
    cost_usd        REAL,
    metadata_json   TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_conversations_status ON conversations(status);
CREATE INDEX IF NOT EXISTS idx_conversations_parent ON conversations(parent_conversation_id);

CREATE TABLE IF NOT EXISTS message_deliveries (
    id              TEXT PRIMARY KEY,
    message_id      TEXT NOT NULL REFERENCES messages(id),
    channel         TEXT NOT NULL,
    delivered_at    TEXT,
    seen_at         TEXT
);

CREATE INDEX IF NOT EXISTS idx_deliveries_message ON message_deliveries(message_id);

-- ════════════════════════════════════════════════════════════════════
-- ENTITY GRAPH & MEMORY
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    aliases_json TEXT,
    confidence REAL DEFAULT 1.0,
    status TEXT DEFAULT 'active',
    properties_json TEXT,
    summary TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    source TEXT,
    source_type TEXT,
    source_id TEXT,
    content_hash TEXT
);

CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT REFERENCES entities(id),
    relationship TEXT NOT NULL,
    target_id TEXT REFERENCES entities(id),
    strength REAL DEFAULT 1.0,
    metadata_json TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    last_confirmed TEXT
);

CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_rel ON edges(relationship);

CREATE TABLE IF NOT EXISTS conversation_summaries (
    id TEXT PRIMARY KEY,
    conversation_id TEXT REFERENCES conversations(id),
    start_message_idx INTEGER,
    end_message_idx INTEGER,
    summary TEXT NOT NULL,
    tags TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);

-- Structured memories (replaces memory_entries + user_facts)
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    keywords_json TEXT DEFAULT '[]',
    tags_json TEXT DEFAULT '[]',
    context_description TEXT,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    conversation_id TEXT,
    confidence REAL DEFAULT 0.8,
    status TEXT DEFAULT 'active',
    superseded_by TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(memory_type);
CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status);
CREATE INDEX IF NOT EXISTS idx_memories_source ON memories(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_memories_conversation ON memories(conversation_id);

-- Bidirectional memory links
CREATE TABLE IF NOT EXISTS memory_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_note_id TEXT REFERENCES memories(id) ON DELETE CASCADE,
    target_note_id TEXT REFERENCES memories(id) ON DELETE CASCADE,
    relationship TEXT NOT NULL,
    strength REAL DEFAULT 1.0,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(source_note_id, target_note_id)
);

CREATE INDEX IF NOT EXISTS idx_memory_links_source ON memory_links(source_note_id);
CREATE INDEX IF NOT EXISTS idx_memory_links_target ON memory_links(target_note_id);

-- Evolution queue (deferred memory refinement)
CREATE TABLE IF NOT EXISTS evolution_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    existing_memory_id TEXT REFERENCES memories(id),
    new_content TEXT NOT NULL,
    new_source_id TEXT,
    reason TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    processed_at TEXT
);

-- Vector search (sqlite-vec, 768-d embeddings)
CREATE VIRTUAL TABLE IF NOT EXISTS memory_vec USING vec0(
    id TEXT PRIMARY KEY,
    embedding FLOAT[768]
);

-- Full-text search
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    content, context_description, keywords_json,
    content='memories',
    content_rowid='rowid'
);

-- FTS sync triggers
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memory_fts(rowid, content, context_description, keywords_json)
    VALUES (new.rowid, new.content, new.context_description, new.keywords_json);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, content, context_description, keywords_json)
    VALUES ('delete', old.rowid, old.content, old.context_description, old.keywords_json);
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, content, context_description, keywords_json)
    VALUES ('delete', old.rowid, old.content, old.context_description, old.keywords_json);
    INSERT INTO memory_fts(rowid, content, context_description, keywords_json)
    VALUES (new.rowid, new.content, new.context_description, new.keywords_json);
END;

CREATE TABLE IF NOT EXISTS pending_brain_writes (
    id TEXT PRIMARY KEY,
    entity_id TEXT,
    fact_id TEXT,
    operation TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_pending_brain_created ON pending_brain_writes(created_at);

CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    artifact_path TEXT,
    conversation_id TEXT,
    source TEXT,
    read INTEGER DEFAULT 0,
    reaction TEXT,
    opened_at TEXT,
    discussed_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_notifications_created ON notifications(created_at);
CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(read);

-- ════════════════════════════════════════════════════════════════════
-- TASKS, GOALS, SCHEDULING
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS goals (
    id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    status TEXT DEFAULT 'active',
    created_by TEXT DEFAULT 'user',
    progress_note TEXT,
    reviewed_at TEXT,
    progress INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS todos (
    id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    scheduled_at TEXT,
    goal_id TEXT,
    conversation_id TEXT,
    result TEXT,
    error TEXT,
    created_by TEXT DEFAULT 'user',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reminders (
    id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    due_at TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    recurrence TEXT,
    conversation_id TEXT,
    created_by TEXT DEFAULT 'user',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_goals_status ON goals(status);
CREATE INDEX IF NOT EXISTS idx_todos_status ON todos(status);
CREATE INDEX IF NOT EXISTS idx_todos_scheduled ON todos(scheduled_at);
CREATE INDEX IF NOT EXISTS idx_reminders_status ON reminders(status);
CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(due_at);

CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'once',
    schedule TEXT,
    action TEXT NOT NULL,
    action_type TEXT DEFAULT 'remind',
    conversation_id TEXT,
    goal_id TEXT,
    enabled INTEGER DEFAULT 1,
    last_run_at TEXT,
    next_run_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_next ON scheduled_tasks(next_run_at);
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_type ON scheduled_tasks(type);

-- General-purpose task tracking. type field distinguishes task kinds:
--   background_poll: async tool execution (image gen, music gen)
--   (future types added here without new tables)
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    description TEXT,
    conversation_id TEXT,
    tool_name TEXT,
    external_task_id TEXT,
    arguments_json TEXT,
    result_json TEXT,
    error TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    created_at TEXT DEFAULT (datetime('now')),
    completed_at TEXT,
    persona TEXT,
    parent_task_id TEXT,
    concurrency_key TEXT DEFAULT 'default',
    max_runtime_seconds INTEGER DEFAULT 600,
    cancel_requested INTEGER DEFAULT 0,
    started_at TEXT,
    artifact_path TEXT,
    duration_ms INTEGER,
    cost_usd REAL,
    delivered_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_type ON tasks(type);
CREATE INDEX IF NOT EXISTS idx_tasks_type_status ON tasks(type, status);
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_task_id);

-- Task plans: multi-step plan persistence
CREATE TABLE IF NOT EXISTS task_plans (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    steps TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    sprint_contract TEXT,
    goal TEXT,
    status TEXT DEFAULT 'in_progress',
    origin TEXT DEFAULT 'user'
);

CREATE INDEX IF NOT EXISTS idx_task_plans_conv ON task_plans(conversation_id);

CREATE TABLE IF NOT EXISTS plan_outcomes (
    plan_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    outcome_score REAL,
    outcome_summary TEXT,
    evaluated_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS heartbeat_sessions (
    id TEXT PRIMARY KEY,
    goal_id TEXT,
    todo_id TEXT,
    plan_id TEXT,
    conversation_id TEXT,
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Legacy cron (kept for backwards compat)
CREATE TABLE IF NOT EXISTS cron_entries (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    schedule TEXT NOT NULL,
    action TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_run_at TEXT,
    next_run_at TEXT,
    conversation_id TEXT
);

-- ════════════════════════════════════════════════════════════════════
-- DOCUMENTS & CONTENT
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    source_url TEXT,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    ingested_at TEXT DEFAULT (datetime('now')),
    conversation_id TEXT,
    file_path TEXT,
    file_size INTEGER,
    content_hash TEXT,
    status TEXT NOT NULL DEFAULT 'ingested'
);

CREATE INDEX IF NOT EXISTS idx_documents_filename ON documents(filename);
CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents(content_hash);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);

CREATE TABLE IF NOT EXISTS document_text (
    document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    full_text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scraped_pages (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    title TEXT,
    summary TEXT,
    scraped_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_scraped_pages_url ON scraped_pages(url);

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    file_size INTEGER NOT NULL DEFAULT 0,
    file_path TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_artifacts_conversation ON artifacts(conversation_id);

CREATE TABLE IF NOT EXISTS message_artifacts (
    message_id      TEXT NOT NULL REFERENCES messages(id),
    artifact_id     TEXT NOT NULL REFERENCES artifacts(id),
    PRIMARY KEY (message_id, artifact_id)
);

CREATE TABLE IF NOT EXISTS channel_mappings (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    channel         TEXT NOT NULL,
    external_id     TEXT NOT NULL,
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(channel, external_id)
);

CREATE INDEX IF NOT EXISTS idx_channel_mappings_external ON channel_mappings(channel, external_id);
CREATE INDEX IF NOT EXISTS idx_messages_idempotency ON messages(json_extract(metadata_json, '$.idempotency_key'));

-- ════════════════════════════════════════════════════════════════════
-- ANALYTICS & TOOL TRACKING
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS query_log (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT UNIQUE NOT NULL,
    conversation_id TEXT NOT NULL,
    message_id TEXT,
    classification TEXT NOT NULL,
    classifier_tier INTEGER DEFAULT 1,
    classifier_confidence REAL,
    entities TEXT,
    search_queries TEXT,
    sub_questions TEXT,
    tools_used TEXT,
    duration_ms INTEGER,
    evaluation_score REAL,
    context_tokens INTEGER,
    response_tokens INTEGER,
    total_tokens INTEGER,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_query_log_classification ON query_log(classification);
CREATE INDEX IF NOT EXISTS idx_query_log_created ON query_log(created_at);

CREATE VIRTUAL TABLE IF NOT EXISTS query_log_vec USING vec0(
    query_log_rowid INTEGER PRIMARY KEY,
    embedding FLOAT[768]
);

CREATE TABLE IF NOT EXISTS skill_usage (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    message_id TEXT,
    skill_name TEXT NOT NULL,
    skill_type TEXT DEFAULT 'text',
    success INTEGER DEFAULT 1,
    evaluation_score REAL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_skill_usage_skill ON skill_usage(skill_name);

CREATE TABLE IF NOT EXISTS tool_errors (
    id TEXT PRIMARY KEY,
    tool_name TEXT NOT NULL,
    error_type TEXT,
    error_message TEXT,
    query_context TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tool_errors_tool ON tool_errors(tool_name);

CREATE TABLE IF NOT EXISTS tool_evaluations (
    id TEXT PRIMARY KEY,
    tool_name TEXT NOT NULL,
    quality_score REAL,
    relevant INTEGER,
    complete INTEGER,
    issues TEXT,
    query_context TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tool_evals_tool ON tool_evaluations(tool_name);

CREATE TABLE IF NOT EXISTS domain_performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL,
    date TEXT NOT NULL,
    avg_score REAL NOT NULL DEFAULT 0.0,
    eval_count INTEGER NOT NULL DEFAULT 0,
    avg_duration_ms REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL,
    UNIQUE(domain, date)
);

-- ════════════════════════════════════════════════════════════════════
-- AGENT EXPERIENCES & LEARNING
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS agent_experiences (
    id TEXT PRIMARY KEY,
    tool_name TEXT NOT NULL,
    situation TEXT NOT NULL,
    outcome TEXT NOT NULL,
    lesson TEXT NOT NULL,
    success INTEGER DEFAULT 1,
    times_applied INTEGER DEFAULT 0,
    confidence REAL DEFAULT 0.8,
    applicability TEXT DEFAULT 'sometimes',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_experiences_tool ON agent_experiences(tool_name);

CREATE TABLE IF NOT EXISTS corrections (
    id TEXT PRIMARY KEY,
    created_at TEXT DEFAULT (datetime('now')),
    conversation_id TEXT REFERENCES conversations(id),
    original_response TEXT,
    correction TEXT,
    context TEXT,
    category TEXT,
    applied_count INTEGER DEFAULT 0,
    consolidated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_corrections_conversation ON corrections(conversation_id);

-- ════════════════════════════════════════════════════════════════════
-- EVOLUTION ENGINE
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS checkpoints (
    id TEXT PRIMARY KEY,
    parent_id TEXT REFERENCES checkpoints(id),
    label TEXT,
    personality_snapshot TEXT,
    prompt_sections_snapshot TEXT,
    skills_snapshot TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

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

CREATE TABLE IF NOT EXISTS trial_overrides (
    id TEXT PRIMARY KEY,
    trial_id TEXT REFERENCES trials(id) ON DELETE CASCADE,
    target_type TEXT NOT NULL,
    target_name TEXT NOT NULL,
    override_content TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_trial_overrides_trial ON trial_overrides(trial_id);

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
    evaluator_agent TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_evaluations_trial ON evaluations(trial_id);
CREATE INDEX IF NOT EXISTS idx_evaluations_created ON evaluations(created_at);

CREATE TABLE IF NOT EXISTS rubric_cache (
    task_type TEXT PRIMARY KEY,
    rubric TEXT NOT NULL,
    usage_count INTEGER DEFAULT 1,
    last_used_at TEXT DEFAULT (datetime('now'))
);

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

CREATE TABLE IF NOT EXISTS fitness_functions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    metric TEXT NOT NULL,
    target_score REAL,
    current_score REAL DEFAULT 0,
    weight REAL DEFAULT 1.0,
    enabled INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS trial_patterns (
    id TEXT PRIMARY KEY,
    trial_id TEXT NOT NULL,
    pattern_type TEXT NOT NULL CHECK (pattern_type IN ('success', 'failure')),
    target TEXT NOT NULL,
    target_name TEXT,
    hypothesis TEXT NOT NULL,
    score_delta REAL,
    context TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_trial_patterns_type ON trial_patterns(pattern_type);

-- ════════════════════════════════════════════════════════════════════
-- OBSERVABILITY & APPROVAL
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS traces (
    id TEXT PRIMARY KEY,
    created_at TEXT DEFAULT (datetime('now')),
    conversation_id TEXT REFERENCES conversations(id),
    event_type TEXT NOT NULL,
    data_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_traces_conversation ON traces(conversation_id);
CREATE INDEX IF NOT EXISTS idx_traces_event_type ON traces(event_type);
CREATE INDEX IF NOT EXISTS idx_traces_timestamp ON traces(created_at);

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    tool_name TEXT NOT NULL,
    arguments_json TEXT,
    decision TEXT NOT NULL DEFAULT 'pending',
    requested_at TEXT DEFAULT (datetime('now')),
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_approvals_decision ON approvals(decision);

-- ════════════════════════════════════════════════════════════════════
-- MULTI-AGENT MESH
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS peer_messages (
    message_id TEXT PRIMARY KEY,
    direction TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    peer_name TEXT NOT NULL,
    message_type TEXT NOT NULL DEFAULT 'message',
    content TEXT NOT NULL,
    metadata_json TEXT,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'sent', 'delivered', 'failed', 'received', 'processed', 'expired', 'rejected')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    delivered_at TEXT,
    conversation_id TEXT,
    response_to TEXT,
    task_status TEXT
);

CREATE INDEX IF NOT EXISTS idx_peer_messages_peer ON peer_messages(peer_name);
CREATE INDEX IF NOT EXISTS idx_peer_messages_status ON peer_messages(status);

-- subagent_tasks table removed 2026-04-10. Sub-agent work now lives in the
-- unified tasks table (type='subagent') managed by SubagentManager.

CREATE TABLE IF NOT EXISTS agent_registry (
    agent_name TEXT PRIMARY KEY,
    role TEXT,
    description TEXT,
    specialty TEXT,
    netbird_ip TEXT,
    ws_port INTEGER DEFAULT 8001,
    status TEXT DEFAULT 'offline',
    last_seen TEXT,
    capabilities TEXT,
    evolution_score REAL,
    allow_external_evaluation INTEGER DEFAULT 0,
    parent TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS spawned_agents (
    id TEXT PRIMARY KEY,
    agent_name TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL,
    description TEXT,
    deploy_target TEXT DEFAULT '',
    proposal_id TEXT,
    config_snapshot TEXT,
    status TEXT DEFAULT 'deploying',
    deployed_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS contact_cards (
    id TEXT PRIMARY KEY,
    card_key TEXT NOT NULL UNIQUE,
    card_type TEXT NOT NULL CHECK (card_type IN ('connect', 'subscribe', 'invite')),
    issued_to TEXT,
    permissions TEXT NOT NULL DEFAULT 'mesh',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked', 'expired')),
    created_at TEXT DEFAULT (datetime('now')),
    expires_at TEXT,
    revoked_at TEXT,
    last_used_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_contact_cards_key ON contact_cards(card_key);

CREATE TABLE IF NOT EXISTS accepted_cards (
    id TEXT PRIMARY KEY,
    card_type TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    host TEXT NOT NULL,
    ws_port INTEGER DEFAULT 8001,
    card_key TEXT NOT NULL,
    feed_url TEXT,
    fingerprint TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'muted', 'revoked')),
    accepted_at TEXT DEFAULT (datetime('now')),
    last_connected_at TEXT
);

CREATE TABLE IF NOT EXISTS feed_entries (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    category TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS strategist_runs (
    id TEXT PRIMARY KEY,
    evaluations_analyzed INTEGER,
    hypotheses_generated TEXT,
    specialization_proposals TEXT,
    direction_log_id TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS specialization_proposals (
    id TEXT PRIMARY KEY,
    proposed_by TEXT,
    role TEXT NOT NULL,
    specialty TEXT,
    description TEXT NOT NULL,
    rationale TEXT,
    seed_knowledge TEXT,
    status TEXT DEFAULT 'pending',
    approved_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS deploy_targets (
    name TEXT PRIMARY KEY,
    host TEXT NOT NULL,
    method TEXT NOT NULL DEFAULT 'docker',
    ssh_user TEXT DEFAULT 'root',
    ssh_key_path TEXT,
    status TEXT DEFAULT 'available',
    last_used_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- ════════════════════════════════════════════════════════════════════
-- USERS & AUTH
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    email TEXT DEFAULT '',
    password_hash TEXT NOT NULL,
    display_name TEXT DEFAULT '',
    must_change_password INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS user_profile (
    id TEXT PRIMARY KEY DEFAULT 'owner',
    communication_style TEXT DEFAULT '',
    expertise_areas TEXT DEFAULT '',
    preferences TEXT DEFAULT '',
    recurring_topics TEXT DEFAULT '',
    correction_patterns TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    last_analyzed_at TEXT,
    conversation_count INTEGER DEFAULT 0,
    activity_pattern TEXT DEFAULT '',
    engagement_trend TEXT DEFAULT '',
    unmet_needs TEXT DEFAULT '',
    relationship_stage TEXT DEFAULT 'new'
);

INSERT OR IGNORE INTO user_profile (id) VALUES ('owner');

CREATE TABLE IF NOT EXISTS user_profile_v2 (
    id TEXT PRIMARY KEY,
    profile_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT DEFAULT (datetime('now'))
);


CREATE TABLE IF NOT EXISTS webauthn_credentials (
    id TEXT PRIMARY KEY,
    credential_id BLOB NOT NULL UNIQUE,
    public_key BLOB NOT NULL,
    sign_count INTEGER DEFAULT 0,
    name TEXT DEFAULT 'Passkey',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS push_subscriptions (
    endpoint TEXT PRIMARY KEY,
    subscription_json TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

-- ════════════════════════════════════════════════════════════════════
-- NOTEBOOKS & KANBAN
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS notebooks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    mode TEXT DEFAULT 'general',
    collaboration TEXT DEFAULT 'read',
    share_with_agent INTEGER DEFAULT 0,
    share_token TEXT,
    last_reviewed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_notebooks_mode ON notebooks(mode);

CREATE TABLE IF NOT EXISTS notebook_entries (
    id TEXT PRIMARY KEY,
    notebook_id TEXT NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    entry_type TEXT DEFAULT 'user',
    status TEXT DEFAULT 'active',
    mood TEXT,
    metadata TEXT,
    quote TEXT,
    trigger_type TEXT,
    viewed_at TEXT,
    parent_id TEXT REFERENCES notebook_entries(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_notebook_entries_notebook ON notebook_entries(notebook_id);

CREATE TABLE IF NOT EXISTS kanban_boards (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    share_token TEXT
);

CREATE TABLE IF NOT EXISTS kanban_columns (
    id TEXT PRIMARY KEY,
    board_id TEXT NOT NULL REFERENCES kanban_boards(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_kanban_columns_board ON kanban_columns(board_id);

CREATE TABLE IF NOT EXISTS kanban_cards (
    id TEXT PRIMARY KEY,
    board_id TEXT NOT NULL REFERENCES kanban_boards(id) ON DELETE CASCADE,
    column_id TEXT NOT NULL REFERENCES kanban_columns(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    position INTEGER NOT NULL DEFAULT 0,
    priority TEXT DEFAULT 'medium',
    due_at TEXT,
    metadata TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_kanban_cards_board ON kanban_cards(board_id);
CREATE INDEX IF NOT EXISTS idx_kanban_cards_column ON kanban_cards(column_id);

-- ════════════════════════════════════════════════════════════════════
-- KV & META
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS agent_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    division TEXT NOT NULL,
    github_path TEXT NOT NULL UNIQUE,
    cached_content TEXT,
    cached_at TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_agent_templates_division ON agent_templates(division);

-- ════════════════════════════════════════════════════════════════════
-- SKILL VERIFICATION & CONSOLIDATION
-- ════════════════════════════════════════════════════════════════════

-- Skill verification history
CREATE TABLE IF NOT EXISTS skill_verifications (
    id TEXT PRIMARY KEY,
    skill_name TEXT NOT NULL,
    scenarios_json TEXT,
    results_json TEXT,
    overall_score REAL,
    escalation_level INTEGER DEFAULT 0,
    diagnostics TEXT,
    model_used TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_skill_verifications_skill
    ON skill_verifications(skill_name);

-- Consolidation audit log
CREATE TABLE IF NOT EXISTS consolidation_log (
    id TEXT PRIMARY KEY,
    axis TEXT NOT NULL,
    corrections_processed INTEGER,
    operations_json TEXT,
    rules_before INTEGER,
    rules_after INTEGER,
    compacted INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
