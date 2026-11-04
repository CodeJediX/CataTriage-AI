"""Public competition access to the app's fictional fixtures."""

import os
from tempfile import TemporaryDirectory

from .settings import ALLOWED_KEYS


ENABLED = os.getenv("CATATRIAGE_JUDGE_DEMO") == "true"
ACCOUNTS = (
    {"role": "admin", "label": "Hospital admin", "username": "admin.nila", "password": "demo-admin", "target": "/admin", "summary": "Review hospital operations, the approved queue and the audit trail."},
    {"role": "doctor", "label": "Doctor", "username": "dr.maya", "password": "demo-doctor", "target": "/doctor", "summary": "Browse assigned cases, clinical review screens and patient follow-ups."},
    {"role": "technician", "label": "Technician / support", "username": "tech.alex", "password": "demo-tech", "target": "/support", "summary": "Explore the capture station and try a technical image quality check."},
)

ALLOWED_POSTS = (
    "/login", "/logout", "/api/assistant/chat", "/support/quality-check",
    "/real-lab/tabular", "/real-lab/fusion",
)

_workspace = None


def configure() -> None:
    """Select a fresh local fixture store before the database modules load."""
    if not ENABLED:
        return
    if os.getenv("CATATRIAGE_DATABASE_URL") or os.getenv("CATATRIAGE_HOSTED") == "true":
        raise RuntimeError("Judge mode requires a separate deployment without hospital database settings.")
    if os.getenv("VERCEL") and len(os.getenv("CATATRIAGE_SESSION_SECRET", "")) < 32:
        raise RuntimeError("The judge deployment requires its own session secret.")
    global _workspace
    _workspace = TemporaryDirectory(prefix="catatriage-judges-")
    os.environ["CATATRIAGE_DATA_DIR"] = _workspace.name
    for key in ALLOWED_KEYS:
        os.environ.pop(key, None)
    for account in ACCOUNTS:
        os.environ.pop(f"CATATRIAGE_{account['role'].upper()}_PASSWORD", None)
    os.environ["ADMIN_EMAIL"] = "judges@example.invalid"
