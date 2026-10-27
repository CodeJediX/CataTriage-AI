"""Postgres connection adapter for the app's existing parameterised SQL."""
from __future__ import annotations

import os
import re
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path

SCHEMAS = {"hospital": "catatriage_hospital", "doctor": "catatriage_doctor", "technician": "catatriage_technician"}


def enabled() -> bool:
    return bool(os.getenv("CATATRIAGE_DATABASE_URL"))


class Row(dict):
    def __getitem__(self, key):
        return tuple(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


def translate_sql(sql: str) -> str:
    sql = sql.replace("?", "%s")
    sql = re.sub(r"julianday\('now'\)\s*-\s*julianday\(([^)]+)\)", r"(CURRENT_DATE - CAST(\1 AS date))", sql, flags=re.I)
    sql = re.sub(r"datetime\('now'\)", "CAST(CURRENT_TIMESTAMP AS text)", sql, flags=re.I)
    sql = re.sub(r"date\('now'\)", "CAST(CURRENT_DATE AS text)", sql, flags=re.I)
    if "INSERT OR IGNORE" in sql.upper():
        sql = re.sub("INSERT OR IGNORE", "INSERT", sql, flags=re.I).rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    if "INSERT OR REPLACE INTO google_access_requests" in sql:
        sql = sql.replace("INSERT OR REPLACE", "INSERT") + " ON CONFLICT(subject) DO UPDATE SET email=excluded.email,display_name=excluded.display_name,requested_at=excluded.requested_at"
    return sql


class Cursor:
    def __init__(self, cursor): self.cursor = cursor
    def fetchone(self):
        result = self.cursor.fetchone()
        return Row(result) if result is not None else None
    def fetchall(self): return [Row(row) for row in self.cursor.fetchall()]
    def __iter__(self): return iter(self.fetchall())
    @property
    def rowcount(self): return self.cursor.rowcount


class Connection:
    def __init__(self, connection): self.raw = connection
    def execute(self, sql, parameters=()):
        if sql.strip().upper() == "BEGIN IMMEDIATE":
            # Serialise capacity/reassignment writes across all serverless instances.
            return Cursor(self.raw.execute("SELECT pg_advisory_xact_lock(724190341)"))
        return Cursor(self.raw.execute(translate_sql(sql), parameters))
    def executemany(self, sql, rows):
        cursor = self.raw.cursor()
        cursor.executemany(translate_sql(sql), rows)
        return Cursor(cursor)
    def commit(self): self.raw.commit()
    def rollback(self): self.raw.rollback()


@contextmanager
def connection(namespace="hospital"):
    import psycopg
    from psycopg.rows import dict_row
    schema = SCHEMAS[namespace]
    with psycopg.connect(os.environ["CATATRIAGE_DATABASE_URL"], row_factory=dict_row,
                         connect_timeout=10, prepare_threshold=None,
                         sslmode="verify-full",sslrootcert=str(Path(__file__).with_name("supabase-ca.crt"))) as raw:
        raw.execute(f'SET LOCAL search_path TO "{schema}", public')
        yield Connection(raw)
