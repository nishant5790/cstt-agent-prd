"""User store — persisted via the configured StateStore backend.

Users live under a reserved workspace id ("__users__") so they ride on the
existing local/azure/redis state backends without any schema change. The user
id is derived deterministically from the email, so lookups never need an index.

The reserved workspace never appears in list_workspaces() because none of the
backends index a workspace until get_workspace/update_workspace is called.
"""
from __future__ import annotations

import hashlib
import re
import time

from app.auth.security import hash_password, verify_password
from app.state import get_state

_USERS_WS = "__users__"
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MIN_PASSWORD = 8


class AuthError(Exception):
    """Raised on validation / credential failures (maps to HTTP 400/401)."""


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _uid(email: str) -> str:
    return hashlib.sha256(normalize_email(email).encode("utf-8")).hexdigest()[:32]


def get_user(uid: str) -> dict | None:
    return get_state().load_session(_USERS_WS, uid)


def get_user_by_email(email: str) -> dict | None:
    return get_state().load_session(_USERS_WS, _uid(email))


def create_user(email: str, password: str) -> dict:
    email = normalize_email(email)
    if not _EMAIL_RE.match(email):
        raise AuthError("invalid email address")
    if len(password or "") < _MIN_PASSWORD:
        raise AuthError(f"password must be at least {_MIN_PASSWORD} characters")
    if get_user_by_email(email):
        raise AuthError("email already registered")
    uid = _uid(email)
    rec = {
        "id": uid,
        "email": email,
        "password_hash": hash_password(password),
        "created": time.time(),
        "sessions": [],
    }
    get_state().save_session(_USERS_WS, uid, rec)
    return rec


def authenticate(email: str, password: str) -> dict:
    rec = get_user_by_email(email)
    if not rec or not verify_password(password, rec.get("password_hash", "")):
        raise AuthError("invalid email or password")
    return rec


def add_session(uid: str, sid: str) -> dict | None:
    """Record that `sid` belongs to user `uid` (for session-history listing)."""
    rec = get_user(uid)
    if not rec:
        return None
    sessions = rec.setdefault("sessions", [])
    if sid not in sessions:
        sessions.append(sid)
        get_state().save_session(_USERS_WS, uid, rec)
    return rec


def remove_session(uid: str, sid: str) -> dict | None:
    rec = get_user(uid)
    if not rec:
        return None
    sessions = rec.get("sessions", [])
    if sid in sessions:
        sessions.remove(sid)
        get_state().save_session(_USERS_WS, uid, rec)
    return rec


def public_user(rec: dict) -> dict:
    """User record without secrets, safe to return to the client."""
    return {
        "id": rec["id"],
        "email": rec["email"],
        "created": rec.get("created"),
        "sessions": rec.get("sessions", []),
    }
