ALTER TABLE webauthn_credentials ADD COLUMN user_id TEXT;
UPDATE webauthn_credentials SET user_id = (SELECT id FROM users LIMIT 1) WHERE user_id IS NULL;
