"""Private credential disclosure for dedicated competition accounts."""

import hashlib
import hmac
import os
import time


COOKIE = "catatriage_judge_access"
ACCESS_SECONDS = 4 * 60 * 60
ROLES = (
    ("admin", "Hospital admin", "judge.admin", "/admin"),
    ("doctor", "Doctor", "judge.doctor", "/doctor"),
    ("technician", "Technician / support", "judge.tech", "/support"),
)


def configured_key() -> str:
    key = os.getenv("CATATRIAGE_JUDGE_KEY", "")
    return key if len(key) >= 32 else ""


def _digest(key: str, purpose: str) -> str:
    return hmac.new(key.encode(), purpose.encode(), hashlib.sha256).hexdigest()


def access_code(key: str) -> str:
    return _digest(key, "judge-credential-access")[:24]


def accounts(key: str) -> list[dict]:
    return [
        {"role": role, "label": label, "username": username, "target": target,
         "password": _digest(key, f"judge-account:{username}")[:32]}
        for role, label, username, target in ROLES
    ]


def disclosure_token(key: str) -> str:
    expiry = str(int(time.time()) + ACCESS_SECONDS)
    return f"{expiry}.{_digest(key, f'judge-disclosure:{expiry}')}"


def can_view(key: str, token: str) -> bool:
    if not key or len(token) > 80:
        return False
    expiry, separator, signature = token.partition(".")
    if not separator or not expiry.isascii() or not expiry.isdecimal() or int(expiry) <= time.time():
        return False
    return hmac.compare_digest(signature.encode(), _digest(key, f"judge-disclosure:{expiry}").encode())
