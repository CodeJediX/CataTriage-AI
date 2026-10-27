ALTER TABLE catatriage_hospital.account_security ADD COLUMN IF NOT EXISTS firebase_linked INTEGER NOT NULL DEFAULT 0;
ALTER TABLE catatriage_hospital.account_security ADD COLUMN IF NOT EXISTS firebase_pending INTEGER NOT NULL DEFAULT 0;
