-- P1.2 (ADR-0010): built-in password credential for a subject. Nullable — passkey-only or OIDC
-- subjects have no password. The app stores an argon2id PHC string here (never a plaintext).
ALTER TABLE subjects ADD COLUMN IF NOT EXISTS password_hash text;
