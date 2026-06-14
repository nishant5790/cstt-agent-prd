"""Session routes — a session is a private, per-user knowledge base.

Each session owns its own uploaded files, CKM, retrieval index, plan and deck,
all namespaced by the session id (which doubles as the storage/state/retrieval
key). A user owns many sessions and can list / load / delete them.
"""
from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import current_user, session_owner
from app.auth.users import add_session, remove_session
from app.state import get_state

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

_state = get_state()


class CreateSessionIn(BaseModel):
    title: str | None = None


def _summary(sid: str, state: dict) -> dict:
    return {
        "sid": sid,
        "title": state.get("title") or "Untitled session",
        "created": state.get("created"),
        "updated": state.get("updated"),
        "built": bool(state.get("built")),
        "building": bool(state.get("building")),
        "blocks": int(state.get("blocks") or 0),
        "sources": state.get("sources", []),
        "topics": state.get("topics", []),
        "has_plan": bool(state.get("plan_id")),
        "has_deck": bool(state.get("deck")),
    }


@router.post("", status_code=201)
def create_session(body: CreateSessionIn | None = None,
                   user: dict = Depends(current_user)) -> dict:
    sid = uuid.uuid4().hex
    title = (body.title if body else None) or "New session"
    state = _state.update_workspace(
        sid, owner=user["id"], title=title, created=time.time(),
        built=False, building=False, error=None,
        topics=[], blocks=0, sources=[], events=[], plan_id=None, deck=None)
    add_session(user["id"], sid)
    return _summary(sid, state)


@router.get("")
def list_sessions(user: dict = Depends(current_user)) -> dict:
    out = []
    for sid in user.get("sessions", []):
        out.append(_summary(sid, _state.get_workspace(sid)))
    out.sort(key=lambda s: s.get("created") or 0, reverse=True)
    return {"sessions": out}


@router.get("/{sid}")
def get_session(ws: str = Depends(session_owner)) -> dict:
    state = _state.get_workspace(ws)
    plan = None
    plan_id = state.get("plan_id")
    if plan_id:
        plan = _state.load_session(ws, plan_id)
    return {**_summary(ws, state),
            "plan": plan, "deck": state.get("deck"),
            "events": state.get("events", [])}


@router.delete("/{sid}")
def delete_session(ws: str = Depends(session_owner),
                   user: dict = Depends(current_user)) -> dict:
    from app.retrieval import get_retriever
    from app.storage import get_store

    store = get_store()
    deleted = 0
    for category in ("inputs", "processing", "outputs"):
        for f in store.list(ws, category):
            store.delete(ws, category, f["name"])
            deleted += 1
    try:
        get_retriever().clear(ws)
    except Exception:
        pass
    _state.delete_workspace(ws)
    remove_session(user["id"], ws)
    return {"ok": True, "sid": ws, "files_deleted": deleted}
