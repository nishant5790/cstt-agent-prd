"""Request dependencies — workspace identity.

Every API call is scoped to a workspace. The frontend sends `X-Workspace-Id`;
if absent we mint a new id and return it in the response header so the client
can persist it (e.g. in localStorage). This gives per-user isolation without
requiring auth for the MVP.
"""
from __future__ import annotations

import re
import uuid

from fastapi import Depends, Header, Response

_WS_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
def workspace_id(
    response: Response,
    x_workspace_id: str | None = Header(default=None, alias="X-Workspace-Id"),
) -> str:
    """Return a validated workspace id, creating one when none is supplied."""
    ws = (x_workspace_id or "").strip()
    if not ws or not _WS_RE.match(ws):
        ws = uuid.uuid4().hex
    # echo it back so the client can store and reuse it
    response.headers["X-Workspace-Id"] = ws
    return ws

def is_valid_workspace_id(ws: str) -> bool:
    """True if `ws` is a syntactically valid workspace id (admin-route guard)."""
    return bool(_WS_RE.match((ws or "").strip()))


def current_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict:
    """Resolve the authenticated user from a `Bearer <jwt>` Authorization header.

    Raises 401 when the token is missing, malformed, expired, or the user no
    longer exists. Returns the public (secret-free) user record.
    """
    import jwt
    from fastapi import HTTPException, status

    from app.auth.security import decode_token
    from app.auth.users import get_user, public_user

    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not authorization or not authorization.lower().startswith("bearer "):
        raise cred_exc
    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = decode_token(token)
    except jwt.PyJWTError:
        raise cred_exc
    rec = get_user(claims.get("sub", ""))
    if not rec:
        raise cred_exc
    return public_user(rec)


def session_owner(
    sid: str,
    user: dict = Depends(current_user),
) -> str:
    """Validate that the path `sid` is a session owned by the current user.

    A session id is also the storage/state/retrieval namespace for that
    session's private knowledge base. Ownership is enforced against the user's
    own session list (no auto-creation side effects), so guessing another
    user's id yields 404, not access.
    """
    from fastapi import HTTPException

    s = (sid or "").strip()
    if not _WS_RE.match(s):
        raise HTTPException(status_code=400, detail="invalid session id")
    if s not in (user.get("sessions") or []):
        raise HTTPException(status_code=404, detail="session not found")
    return s