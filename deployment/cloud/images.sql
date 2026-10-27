CREATE TABLE catatriage_hospital.file_objects (
 object_key TEXT PRIMARY KEY, content BYTEA NOT NULL CHECK(octet_length(content)<=8388608)
);
CREATE TABLE catatriage_hospital.pending_uploads (
 id TEXT PRIMARY KEY, owner_name TEXT NOT NULL, action_path TEXT NOT NULL, target_id TEXT NOT NULL,
 field_name TEXT NOT NULL, original_name TEXT NOT NULL, expected_size INTEGER NOT NULL CHECK(expected_size BETWEEN 1 AND 8388608),
 expires_at BIGINT NOT NULL
);
CREATE TABLE catatriage_hospital.upload_chunks (
 upload_id TEXT NOT NULL REFERENCES catatriage_hospital.pending_uploads(id) ON DELETE CASCADE,
 chunk_index INTEGER NOT NULL CHECK(chunk_index BETWEEN 0 AND 7),
 content BYTEA NOT NULL CHECK(octet_length(content)<=1048576), PRIMARY KEY(upload_id,chunk_index)
);
ALTER TABLE catatriage_hospital.file_objects ENABLE ROW LEVEL SECURITY;
ALTER TABLE catatriage_hospital.pending_uploads ENABLE ROW LEVEL SECURITY;
ALTER TABLE catatriage_hospital.upload_chunks ENABLE ROW LEVEL SECURITY;
CREATE POLICY app_server_access ON catatriage_hospital.file_objects TO catatriage_app USING(true) WITH CHECK(true);
CREATE POLICY app_server_access ON catatriage_hospital.pending_uploads TO catatriage_app USING(true) WITH CHECK(true);
CREATE POLICY app_server_access ON catatriage_hospital.upload_chunks TO catatriage_app USING(true) WITH CHECK(true);
GRANT SELECT,INSERT,UPDATE,DELETE ON catatriage_hospital.file_objects,catatriage_hospital.pending_uploads,catatriage_hospital.upload_chunks TO catatriage_app;
