"""Password hashing (stdlib PBKDF2) + JWT issue/verify (PyJWT).

No external crypto dependency for hashing — PBKDF2-HMAC-SHA256 with a per-user
random salt is stored as a self-describing string:
    pbkdf2_sha256${rounds}${salt_b64}${hash_b64}
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

import jwt

from app.core.config import settings

_PBKDF2_ROUNDS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS)
    return "pbkdf2_sha256${}${}${}".format(
        _PBKDF2_ROUNDS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(dk).decode("ascii"),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds_s, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        rounds = int(rounds_s)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


def create_access_token(sub: str, email: str) -> str:
    cfg = settings()
    now = int(time.time())
    payload = {
        "sub": sub,
        "email": email,
        "iat": now,
        "exp": now + cfg.jwt_ttl_minutes * 60,
    }
    return jwt.encode(payload, cfg.jwt_secret, algorithm=cfg.jwt_algorithm)


def decode_token(token: str) -> dict:
    """Return the JWT claims, or raise jwt.PyJWTError if invalid/expired."""
    cfg = settings()
    return jwt.decode(token, cfg.jwt_secret, algorithms=[cfg.jwt_algorithm])
