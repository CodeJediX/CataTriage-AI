ALTER TABLE catatriage_hospital.cases ADD COLUMN IF NOT EXISTS is_archived INTEGER NOT NULL DEFAULT 0;
CREATE TABLE catatriage_hospital.account_archives(
 entity_type TEXT NOT NULL CHECK(entity_type IN ('patient','doctor')), entity_key TEXT NOT NULL,
 archived_by TEXT NOT NULL, archived_at TEXT NOT NULL,
 previous_state TEXT NOT NULL DEFAULT '{}', restored_at TEXT,
 PRIMARY KEY(entity_type,entity_key)
);
ALTER TABLE catatriage_hospital.account_archives ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON catatriage_hospital.account_archives FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE,DELETE ON catatriage_hospital.account_archives TO catatriage_app;
CREATE POLICY app_access ON catatriage_hospital.account_archives TO catatriage_app USING(true) WITH CHECK(true);
