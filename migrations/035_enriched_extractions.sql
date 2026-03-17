-- User profile meta fields
ALTER TABLE user_profile ADD COLUMN activity_pattern TEXT DEFAULT '';
ALTER TABLE user_profile ADD COLUMN engagement_trend TEXT DEFAULT '';
ALTER TABLE user_profile ADD COLUMN unmet_needs TEXT DEFAULT '';
ALTER TABLE user_profile ADD COLUMN relationship_stage TEXT DEFAULT 'new';

-- Conversation summary tags
ALTER TABLE conversation_summaries ADD COLUMN tags TEXT DEFAULT '';

-- Experience confidence
ALTER TABLE agent_experiences ADD COLUMN confidence REAL DEFAULT 0.8;
ALTER TABLE agent_experiences ADD COLUMN applicability TEXT DEFAULT 'sometimes';
