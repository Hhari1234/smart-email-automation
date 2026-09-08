-- Add profile fields required by self-service registration.
-- Existing users remain intact: legacy accounts receive an empty name and NULL email.
ALTER TABLE users ADD COLUMN name TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN email TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique
ON users(email)
WHERE email IS NOT NULL AND email <> '';