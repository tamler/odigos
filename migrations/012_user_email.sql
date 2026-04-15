-- Add email column to users so account creation can collect a real address.
-- Backfilled empty for any existing user; required for new signups via /api/auth/setup.
ALTER TABLE users ADD COLUMN email TEXT DEFAULT '';
