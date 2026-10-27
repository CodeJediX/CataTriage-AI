from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

from .database import DATA_DIR, LEGACY_ALIASES, SEED_CASES, now_iso
from . import cloud_database

DOCTOR_DB_PATH = DATA_DIR / "doctor_portal.sqlite3"
TECHNICIAN_DB_PATH = DATA_DIR / "technician_support.sqlite3"


@contextmanager
def role_connection(path: Path):
    if cloud_database.enabled() and path in {DOCTOR_DB_PATH, TECHNICIAN_DB_PATH}:
        namespace="doctor" if path==DOCTOR_DB_PATH else "technician"
        with cloud_database.connection(namespace) as con:
            yield con
        return
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


DOCTOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS patient_profiles(
 case_id TEXT PRIMARY KEY, doctor_username TEXT NOT NULL, full_name TEXT NOT NULL,
 phone TEXT NOT NULL, email TEXT NOT NULL, address TEXT NOT NULL, medical_history TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages(
 id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, sender TEXT NOT NULL,
 recipient TEXT NOT NULL, body TEXT NOT NULL, sent_at TEXT NOT NULL,
 delivery_channel TEXT NOT NULL DEFAULT 'local', delivery_status TEXT NOT NULL DEFAULT 'stored'
);
CREATE TABLE IF NOT EXISTS doctor_directory(
 username TEXT PRIMARY KEY, display_name TEXT NOT NULL, specialty TEXT NOT NULL,
 hospital TEXT NOT NULL, phone TEXT NOT NULL, email TEXT NOT NULL,
 working_hours TEXT NOT NULL DEFAULT '08:00-16:00', working_days TEXT NOT NULL DEFAULT 'Mon,Tue,Wed,Thu,Fri',
 profile_image TEXT, whatsapp_phone TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS self_assessments(
 id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, submitted_at TEXT NOT NULL,
 findings TEXT NOT NULL, review_status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notifications(
 id INTEGER PRIMARY KEY AUTOINCREMENT, doctor_username TEXT NOT NULL, title TEXT NOT NULL,
 body TEXT NOT NULL, due_date TEXT, is_read INTEGER NOT NULL DEFAULT 0
);
"""

TECH_SCHEMA = """
CREATE TABLE IF NOT EXISTS registrations(
 id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, entered_by TEXT NOT NULL,
 completeness INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quality_checks(
 id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, filename TEXT NOT NULL,
 format TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
 quality_status TEXT NOT NULL, feedback TEXT NOT NULL, checked_by TEXT NOT NULL, checked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS support_tickets(
 id INTEGER PRIMARY KEY AUTOINCREMENT, subject TEXT NOT NULL, status TEXT NOT NULL,
 owner TEXT NOT NULL, created_at TEXT NOT NULL
);
"""


def _ensure_column(con: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def sync_doctor_directory() -> None:
    from .database import connection
    with connection() as con:
        profiles=[dict(r) for r in con.execute("SELECT * FROM doctor_profiles")]
    with role_connection(DOCTOR_DB_PATH) as con:
        for doctor in profiles:
            con.execute("""INSERT INTO doctor_directory(username,display_name,specialty,hospital,phone,email,working_hours,working_days,profile_image,whatsapp_phone)
                VALUES(?,?,'Ophthalmology','CataTriage Demonstration Hospital',?,'',?,?,?,?)
                ON CONFLICT(username) DO UPDATE SET display_name=excluded.display_name,phone=excluded.phone,
                working_hours=excluded.working_hours,working_days=excluded.working_days,profile_image=excluded.profile_image,whatsapp_phone=excluded.whatsapp_phone""",
                (doctor["username"],doctor["display_name"],doctor["mobile"],doctor["work_start"]+"-"+doctor["work_end"],doctor["working_days"],doctor["profile_image"],doctor["whatsapp_phone"]))
            if doctor.get("email"):
                con.execute("UPDATE doctor_directory SET email=? WHERE username=?",(doctor["email"],doctor["username"]))


def initialize_role_databases(force_reset: bool = False) -> None:
    if cloud_database.enabled():
        if force_reset: raise RuntimeError("Cloud database reset is disabled.")
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with role_connection(DOCTOR_DB_PATH) as con:
        con.executescript(DOCTOR_SCHEMA)
        _ensure_column(con, "messages", "delivery_channel", "TEXT NOT NULL DEFAULT 'local'")
        _ensure_column(con, "messages", "delivery_status", "TEXT NOT NULL DEFAULT 'stored'")
        _ensure_column(con, "doctor_directory", "working_hours", "TEXT NOT NULL DEFAULT '08:00-16:00'")
        _ensure_column(con, "doctor_directory", "working_days", "TEXT NOT NULL DEFAULT 'Mon,Tue,Wed,Thu,Fri'")
        _ensure_column(con, "doctor_directory", "profile_image", "TEXT")
        _ensure_column(con, "doctor_directory", "whatsapp_phone", "TEXT NOT NULL DEFAULT ''")
        if force_reset:
            for table in ("patient_profiles", "messages", "doctor_directory", "self_assessments", "notifications"):
                con.execute(f"DELETE FROM {table}")
        if con.execute("SELECT COUNT(*) FROM patient_profiles").fetchone()[0] == 0:
            aliases = ["Nethmi Perera","Kavindu Fernando","Dilani Jayasinghe","Sahan Wijesinghe","Ishara Gunawardena","Tharushi Ranasinghe","Dinesh Karunaratne","Malini Abeysekara","Rashmi Dissanayake","Sunil Bandara","Amaya Senanayake","Roshan Ekanayake","Chamari Herath","Nimal Rathnayake","Sachini Peiris","Lahiru Wickramasinghe"]
            rows = []
            for index, alias in enumerate(aliases, 1):
                slug = alias.lower().replace(" ", ".")
                rows.append((f"DEMO-{index:04d}", "dr.maya" if index % 2 else "dr.kamal", alias, f"+94 77 300 {index:04d}", f"{slug}@example.invalid", f"{index}, Lake Road, Colombo", "Fictional demonstration history; no real patient data."))
            con.executemany("INSERT INTO patient_profiles VALUES(?,?,?,?,?,?,?)", rows)
            con.executemany("INSERT INTO doctor_directory(username,display_name,specialty,hospital,phone,email,working_hours,working_days,whatsapp_phone) VALUES(?,?,?,?,?,?,?,?,?)", [
                ("dr.maya","Dr Maya Perera","Ophthalmology","CataTriage Demonstration Hospital","+94 77 234 1180","maya@example.invalid","08:00-16:00","Mon,Tue,Wed,Thu,Fri","+94772341180"),
                ("dr.kamal","Dr Kamal Silva","Anterior Segment","CataTriage Demonstration Hospital","+94 77 418 2260","kamal@example.invalid","14:00-23:00","Mon,Tue,Wed,Thu,Fri,Sat","+94774182260"),
            ])
            con.execute("INSERT INTO messages(case_id,sender,recipient,body,sent_at) VALUES(?,?,?,?,?)", ("DEMO-0001","DEMO-0001","dr.maya","Synthetic message: vision has been changing this week.",now_iso()))
            con.execute("INSERT INTO self_assessments(case_id,submitted_at,findings,review_status) VALUES(?,?,?,?)", ("DEMO-0001",now_iso(),"Synthetic questionnaire: glare and reduced contrast reported.","Awaiting clinician review"))
            con.execute("INSERT INTO notifications(doctor_username,title,body,due_date) VALUES(?,?,?,?)", ("dr.maya","Follow-up due","Review fictional case DEMO-0001 before its appointment.",(date.today()+timedelta(days=2)).isoformat()))
        for old, seed in zip(LEGACY_ALIASES,SEED_CASES):
            con.execute("UPDATE patient_profiles SET full_name=? WHERE case_id=? AND full_name=?", (seed[1],seed[0],old+" Demo"))
    with role_connection(TECHNICIAN_DB_PATH) as con:
        con.executescript(TECH_SCHEMA)
        if force_reset:
            for table in ("registrations", "quality_checks", "support_tickets"):
                con.execute(f"DELETE FROM {table}")
        if con.execute("SELECT COUNT(*) FROM registrations").fetchone()[0] == 0:
            con.execute("INSERT INTO registrations(case_id,entered_by,completeness,created_at) VALUES(?,?,?,?)", ("DEMO-0001","tech.alex",100,now_iso()))
            con.execute("INSERT INTO support_tickets(subject,status,owner,created_at) VALUES(?,?,?,?)", ("Demo capture station calibration","Open","tech.alex",now_iso()))
