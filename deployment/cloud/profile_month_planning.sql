CREATE TABLE IF NOT EXISTS catatriage_hospital.account_login_names(
 username TEXT PRIMARY KEY REFERENCES catatriage_hospital.users(username) ON DELETE CASCADE,
 login_name TEXT NOT NULL UNIQUE, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS catatriage_hospital.surgery_month_plans(
 case_id TEXT PRIMARY KEY REFERENCES catatriage_hospital.cases(case_id) ON DELETE CASCADE,
 doctor_username TEXT NOT NULL REFERENCES catatriage_hospital.users(username),
 suggested_month TEXT, approved_month TEXT, approval_reason TEXT NOT NULL DEFAULT '',
 approved_by TEXT, approved_at TEXT, evidence_hash TEXT NOT NULL,
 assessment_json TEXT NOT NULL DEFAULT '{}', suggestion_json TEXT NOT NULL DEFAULT '{}'
);
ALTER TABLE catatriage_hospital.account_login_names ENABLE ROW LEVEL SECURITY;
ALTER TABLE catatriage_hospital.surgery_month_plans ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON catatriage_hospital.account_login_names,catatriage_hospital.surgery_month_plans FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE,DELETE ON catatriage_hospital.account_login_names,catatriage_hospital.surgery_month_plans TO catatriage_app;
CREATE POLICY app_access ON catatriage_hospital.account_login_names TO catatriage_app USING(true) WITH CHECK(true);
CREATE POLICY app_access ON catatriage_hospital.surgery_month_plans TO catatriage_app USING(true) WITH CHECK(true);
