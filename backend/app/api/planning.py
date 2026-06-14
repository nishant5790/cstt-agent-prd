"""Planning routes — the clarify -> draft -> revise -> approve deck loop.

Nested under a session (`/api/sessions/{sid}/plan/...`). The session is the
private knowledge base; its build must have completed first. One active plan
conversation per session — its id is tracked in the session state as `plan_id`,
so the client never has to juggle a separate plan id.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.agents.conversation_agent import ConversationPlanner, PlannerError
from app.api.deps import session_owner
from app.state import get_state

router = APIRouter(prefix="/api/sessions", tags=["planning"])

_planner = ConversationPlanner()
_state = get_state()


class StartIn(BaseModel):
    request: str
    sources: list[str] | None = None
    audience: str | None = None


class AnswerIn(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict)


class ReviseIn(BaseModel):
    feedback: str


def _require_built(ws: str) -> None:
    if not _state.get_workspace(ws).get("built"):
        raise HTTPException(409, "Knowledge base not built yet")


def _plan_id(ws: str) -> str:
    pid = _state.get_workspace(ws).get("plan_id")
    if not pid:
        raise HTTPException(409, "no active plan — start one first")
    return pid


@router.post("/{sid}/plan/start")
def start(body: StartIn, ws: str = Depends(session_owner)) -> dict:
    _require_built(ws)
    if not body.request.strip():
        raise HTTPException(400, "request is required")
    try:
        res = _planner.start(ws, body.request, sources=body.sources,
                             audience=body.audience)
    except (PlannerError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    # new plan supersedes any previous one — drop the stale generated deck
    _state.update_workspace(ws, plan_id=res["sid"], deck=None)
    return res


@router.post("/{sid}/plan/answer")
def answer(body: AnswerIn, ws: str = Depends(session_owner)) -> dict:
    try:
        return _planner.answer(ws, _plan_id(ws), body.answers)
    except (PlannerError, ValueError) as exc:
        raise HTTPException(400, str(exc))


@router.post("/{sid}/plan/revise")
def revise(body: ReviseIn, ws: str = Depends(session_owner)) -> dict:
    try:
        return _planner.revise(ws, _plan_id(ws), body.feedback)
    except (PlannerError, ValueError) as exc:
        raise HTTPException(400, str(exc))


@router.post("/{sid}/plan/approve")
def approve(ws: str = Depends(session_owner)) -> dict:
    try:
        return _planner.approve(ws, _plan_id(ws))
    except (PlannerError, ValueError) as exc:
        raise HTTPException(400, str(exc))


@router.get("/{sid}/plan")
def get_plan(ws: str = Depends(session_owner)) -> dict:
    try:
        return _planner.get(ws, _plan_id(ws))
    except PlannerError as exc:
        raise HTTPException(404, str(exc))