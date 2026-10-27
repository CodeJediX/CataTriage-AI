from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from . import cloud_database

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("CATATRIAGE_DATA_DIR", str(APP_DIR / "data")))
UPLOAD_DIR = DATA_DIR / "uploads"
DOCTOR_IMAGE_DIR = DATA_DIR / "doctor_profiles"
DB_PATH = DATA_DIR / "hospital_admin.sqlite3"
SCHEMA_VERSION = 3
LOCAL_TZ = timezone(timedelta(hours=5, minutes=30))


def _initial_password(role: str, default: str) -> str:
    value = os.getenv(f"CATATRIAGE_{role.upper()}_PASSWORD", "")
    if os.getenv("CATATRIAGE_HOSTED") == "true" and len(value) < 16:
        raise RuntimeError("Hosted demo requires private role passwords of at least 16 characters.")
    return value or default


def now_iso() -> str:
    return datetime.now(LOCAL_TZ).replace(microsecond=0).isoformat()


def hash_password(password: str, salt_hex: str | None = None) -> str:
    salt = bytes.fromhex(salt_hex) if salt_hex else os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 210_000)
    return f"pbkdf2_sha256$210000${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    scheme, rounds, salt_hex, expected = encoded.split("$", 3)
    if scheme != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds)
    )
    return hmac.compare_digest(digest.hex(), expected)


@contextmanager
def connection(db_path: Path | str = DB_PATH):
    if cloud_database.enabled() and Path(db_path)==DB_PATH:
        with cloud_database.connection("hospital") as con:
            yield con
        return
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS users(
  username TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('doctor','admin','technician')),
  password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cases(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id TEXT NOT NULL UNIQUE,
  patient_alias TEXT NOT NULL,
  age INTEGER NOT NULL CHECK(age BETWEEN 1 AND 110),
  eye TEXT NOT NULL CHECK(eye IN ('Left','Right','Both','Not recorded')),
  modality TEXT NOT NULL CHECK(modality IN ('fundus','slit_lamp')),
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  waiting_since TEXT NOT NULL,
  approved_tier TEXT CHECK(approved_tier IN ('Tier 1','Tier 2','Tier 3') OR approved_tier IS NULL),
  approved_by TEXT,
  approval_reason TEXT,
  review_state TEXT NOT NULL DEFAULT 'pending',
  symptoms TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  image_path TEXT,
  image_sha256 TEXT,
  analysis_status TEXT NOT NULL DEFAULT 'not_run',
  analysis_json TEXT
);
CREATE TABLE IF NOT EXISTS appointments(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id TEXT NOT NULL UNIQUE REFERENCES cases(case_id) ON DELETE CASCADE,
  scheduled_date TEXT NOT NULL,
  slot TEXT NOT NULL,
  service TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS doctor_profiles(
  username TEXT PRIMARY KEY REFERENCES users(username) ON DELETE CASCADE,
  display_name TEXT NOT NULL,
  mobile TEXT NOT NULL,
  work_start TEXT NOT NULL,
  work_end TEXT NOT NULL,
  working_days TEXT NOT NULL,
  profile_image TEXT,
  whatsapp_phone TEXT NOT NULL DEFAULT '',
  google_email TEXT NOT NULL DEFAULT '',
  is_active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS google_access_requests(
  subject TEXT PRIMARY KEY, email TEXT NOT NULL, display_name TEXT NOT NULL, requested_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS google_identities(
  subject TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE REFERENCES users(username) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS leave_requests(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  doctor_username TEXT NOT NULL REFERENCES users(username),
  leave_date TEXT NOT NULL,
  leave_type TEXT NOT NULL CHECK(leave_type IN ('full_day','morning','evening')),
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','resolved','rejected')),
  affected_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  UNIQUE(doctor_username,leave_date,leave_type)
);
CREATE TABLE IF NOT EXISTS surgery_capacity(
  id INTEGER PRIMARY KEY CHECK(id=1),
  max_surgeries_per_day INTEGER NOT NULL CHECK(max_surgeries_per_day BETWEEN 1 AND 100),
  total_beds INTEGER NOT NULL CHECK(total_beds BETWEEN 0 AND 500),
  available_beds INTEGER NOT NULL CHECK(available_beds BETWEEN 0 AND 500),
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS surgeries(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id TEXT NOT NULL UNIQUE REFERENCES cases(case_id) ON DELETE CASCADE,
  surgery_date TEXT NOT NULL,
  slot TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'confirmed' CHECK(status IN ('suggested','confirmed','completed','cancelled')),
  confirmed_by TEXT NOT NULL,
  rationale TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS case_images(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
  eye_side TEXT NOT NULL CHECK(eye_side IN ('Left','Right','Both','Not recorded')),
  category TEXT NOT NULL DEFAULT 'clinical',
  image_path TEXT NOT NULL,
  image_sha256 TEXT NOT NULL,
  analysis_json TEXT,
  uploaded_by TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp TEXT NOT NULL,
  actor TEXT NOT NULL,
  role TEXT NOT NULL,
  action TEXT NOT NULL,
  case_id TEXT,
  details TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cases_tier ON cases(approved_tier);
CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status);
CREATE INDEX IF NOT EXISTS idx_audit_case ON audit_log(case_id);
CREATE INDEX IF NOT EXISTS idx_leave_date ON leave_requests(leave_date,status);
CREATE INDEX IF NOT EXISTS idx_surgery_date ON surgeries(surgery_date,status);
CREATE INDEX IF NOT EXISTS idx_case_images_case ON case_images(case_id);
"""


SEED_CASES = [
    ("DEMO-0001", "Nethmi Perera", 68, "Left", "slit_lamp", "awaiting_review", 74, "Tier 1", "dr.maya", "Doctor-entered demo priority: rapid functional decline."),
    ("DEMO-0002", "Kavindu Fernando", 57, "Right", "fundus", "scheduled", 52, "Tier 2", "dr.maya", "Doctor-entered demo priority: persistent symptoms."),
    ("DEMO-0003", "Dilani Jayasinghe", 73, "Both", "slit_lamp", "approved", 46, "Tier 2", "dr.kamal", "Doctor-entered demo priority after review."),
    ("DEMO-0004", "Sahan Wijesinghe", 49, "Right", "fundus", "awaiting_review", 38, None, None, None),
    ("DEMO-0005", "Ishara Gunawardena", 81, "Left", "slit_lamp", "approved", 31, "Tier 1", "dr.kamal", "Doctor-entered demo priority: mobility impact."),
    ("DEMO-0006", "Tharushi Ranasinghe", 64, "Right", "fundus", "scheduled", 26, "Tier 3", "dr.maya", "Doctor-entered routine demo priority."),
    ("DEMO-0007", "Dinesh Karunaratne", 55, "Left", "slit_lamp", "awaiting_review", 22, None, None, None),
    ("DEMO-0008", "Malini Abeysekara", 70, "Both", "fundus", "approved", 18, "Tier 2", "dr.kamal", "Doctor-entered demo priority."),
    ("DEMO-0009", "Rashmi Dissanayake", 62, "Right", "slit_lamp", "scheduled", 15, "Tier 3", "dr.maya", "Doctor-entered routine demo priority."),
    ("DEMO-0010", "Sunil Bandara", 77, "Left", "fundus", "approved", 12, "Tier 1", "dr.kamal", "Doctor-entered demo priority: severe reported limitation."),
    ("DEMO-0011", "Amaya Senanayake", 44, "Right", "slit_lamp", "awaiting_review", 9, None, None, None),
    ("DEMO-0012", "Roshan Ekanayake", 66, "Left", "fundus", "scheduled", 8, "Tier 2", "dr.maya", "Doctor-entered demo priority."),
    ("DEMO-0013", "Chamari Herath", 59, "Both", "slit_lamp", "approved", 6, "Tier 3", "dr.kamal", "Doctor-entered routine demo priority."),
    ("DEMO-0014", "Nimal Rathnayake", 72, "Left", "fundus", "awaiting_review", 4, None, None, None),
    ("DEMO-0015", "Sachini Peiris", 53, "Right", "slit_lamp", "approved", 3, "Tier 2", "dr.maya", "Doctor-entered demo priority."),
    ("DEMO-0016", "Lahiru Wickramasinghe", 69, "Both", "fundus", "awaiting_review", 1, None, None, None),
]

LEGACY_ALIASES = ["Aster","Birch","Cedar","Dahlia","Elm","Fern","Grove","Hazel","Iris","Juniper","Kestrel","Lotus","Maple","Nightingale","Olive","Pine"]


def audit(con: sqlite3.Connection, actor: str, role: str, action: str, case_id: str | None, details: str) -> None:
    con.execute(
        "INSERT INTO audit_log(timestamp,actor,role,action,case_id,details) VALUES(?,?,?,?,?,?)",
        (now_iso(), actor, role, action, case_id, details),
    )


def initialize_database(db_path: Path | str = DB_PATH, force_reset: bool = False) -> None:
    if cloud_database.enabled() and Path(db_path)==DB_PATH:
        if force_reset: raise RuntimeError("Cloud database reset requires an explicit migration.")
        with connection() as con:
            if not con.execute("SELECT version FROM schema_version LIMIT 1").fetchone():
                raise RuntimeError("Cloud database migrations have not been applied.")
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    DOCTOR_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    with connection(db_path) as con:
        con.executescript(SCHEMA)
        if "google_email" not in {r[1] for r in con.execute("PRAGMA table_info(doctor_profiles)")}:
            con.execute("ALTER TABLE doctor_profiles ADD COLUMN google_email TEXT NOT NULL DEFAULT ''")
        version = con.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        if version is None:
            con.execute("INSERT INTO schema_version(version) VALUES(?)", (SCHEMA_VERSION,))
        elif version[0] == 2:
            con.execute("UPDATE schema_version SET version=?", (SCHEMA_VERSION,))
        elif version[0] != SCHEMA_VERSION:
            raise RuntimeError(f"Unsupported demo DB schema {version[0]}")
        if force_reset:
            con.execute("DELETE FROM google_identities")
            con.execute("DELETE FROM google_access_requests")
            con.execute("DELETE FROM case_images")
            con.execute("DELETE FROM surgeries")
            con.execute("DELETE FROM leave_requests")
            con.execute("DELETE FROM surgery_capacity")
            con.execute("DELETE FROM doctor_profiles")
            con.execute("DELETE FROM appointments")
            con.execute("DELETE FROM audit_log")
            con.execute("DELETE FROM cases")
            con.execute("DELETE FROM users")
        if con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            users = [
                ("dr.maya", "Dr Maya Perera", "doctor", hash_password(_initial_password("doctor", "demo-doctor"))),
                ("dr.kamal", "Dr Kamal Silva", "doctor", hash_password(_initial_password("doctor", "demo-doctor"))),
                ("admin.nila", "Nila Fernando", "admin", hash_password(_initial_password("admin", "demo-admin"))),
                ("tech.alex", "Alex Fernando", "technician", hash_password(_initial_password("technician", "demo-tech"))),
            ]
            con.executemany("INSERT INTO users VALUES(?,?,?,?)", users)
        if con.execute("SELECT COUNT(*) FROM doctor_profiles").fetchone()[0] == 0:
            con.executemany(
                "INSERT INTO doctor_profiles(username,display_name,mobile,work_start,work_end,working_days,whatsapp_phone) VALUES(?,?,?,?,?,?,?)",
                [
                    ("dr.maya", "Dr Maya Perera", "+94 77 234 1180", "08:00", "16:00", "Mon,Tue,Wed,Thu,Fri", "+94772341180"),
                    ("dr.kamal", "Dr Kamal Silva", "+94 77 418 2260", "14:00", "23:00", "Mon,Tue,Wed,Thu,Fri,Sat", "+94774182260"),
                ],
            )
        con.execute(
            "INSERT OR IGNORE INTO surgery_capacity(id,max_surgeries_per_day,total_beds,available_beds,updated_at) VALUES(1,6,18,12,?)",
            (now_iso(),),
        )
        if con.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0:
            today = date.today()
            for idx, row in enumerate(SEED_CASES):
                case_id, alias, age, eye, modality, status, wait_days, tier, approver, reason = row
                created = datetime.combine(today - timedelta(days=wait_days), datetime.min.time(), LOCAL_TZ).isoformat()
                review_state = "approved" if tier else "pending"
                con.execute(
                    """INSERT INTO cases(case_id,patient_alias,age,eye,modality,status,created_at,waiting_since,
                    approved_tier,approved_by,approval_reason,review_state,symptoms,notes)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (case_id, alias, age, eye, modality, status, created, (today - timedelta(days=wait_days)).isoformat(),
                     tier, approver, reason, review_state, "Fictional visual symptoms for workflow demonstration.", "SIMULATED DEMO DATA"),
                )
                if idx in (1, 5, 8, 11):
                    appt_date = (today + timedelta(days=4 + idx)).isoformat()
                    con.execute(
                        "INSERT INTO appointments(case_id,scheduled_date,slot,service,created_by,created_at) VALUES(?,?,?,?,?,?)",
                        (case_id, appt_date, "09:30", "Demo ophthalmology clinic", "admin.nila", now_iso()),
                    )
            audit(con, "system", "system", "demo_seed", None, "Initialized 16 fictional cases and demo users; no patient data.")
        for old, seed in zip(LEGACY_ALIASES, SEED_CASES):
            con.execute("UPDATE cases SET patient_alias=? WHERE case_id=? AND patient_alias=?", (seed[1],seed[0],old))


def reset_database(db_path: Path | str = DB_PATH) -> None:
    initialize_database(db_path, force_reset=True)

