ALTER TABLE users ADD COLUMN email TEXT DEFAULT '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email) WHERE email != '';
