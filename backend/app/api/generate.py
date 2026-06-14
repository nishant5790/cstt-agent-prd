"""Generation routes — render an approved plan into a downloadable .pptx.

POST /api/sessions/{sid}/generate   -> build the deck, store it, return a link
GET  /api/sessions/{sid}/download   -> stream the generated deck
"""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response

from app.agents.analysis_agent import DeckPlan
from app.agents.ppt_agent import PptAgent, safe_filename
from app.api.deps import session_owner
from app.state import get_state

router = APIRouter(prefix="/api/sessions", tags=["generation"])

_state = get_state()
_ppt = PptAgent()

_PPTX_MIME = ("application/vnd.openxmlformats-officedocument."
              "presentationml.presentation")


def _plan_id(ws: str) -> str:
    pid = _state.get_workspace(ws).get("plan_id")
    if not pid:
        raise HTTPException(409, "no active plan — draft and approve first")
    return pid


@router.post("/{sid}/generate")
def generate(ws: str = Depends(session_owner)) -> dict:
    from app.storage import get_store
    pid = _plan_id(ws)
    session = _state.load_session(ws, pid)
    if session is None:
        raise HTTPException(404, "plan not found")
    if not session.get("plan"):
        raise HTTPException(409, "no plan to generate — draft and approve first")

    plan = DeckPlan.model_validate(session["plan"])
    data = _ppt.build(plan)

    filename = f"DECK--{safe_filename(plan.deck_title)}.pptx"
    rel = f"deck-{pid}.pptx"
    get_store().put_bytes(ws, "outputs", rel, data)

    deck = {"rel": rel, "filename": filename,
            "slides": len(plan.slides), "bytes": len(data),
            "generated_at": time.time()}
    session["deck"] = deck
    _state.save_session(ws, pid, session)
    _state.update_workspace(ws, deck=deck)

    return {"ok": True, "sid": ws, "filename": filename,
            "slides": len(plan.slides), "bytes": len(data),
            "download_url": f"/api/sessions/{ws}/download"}


@router.get("/{sid}/download")
def download_deck(ws: str = Depends(session_owner)) -> Response:
    from app.storage import get_store
    deck = _state.get_workspace(ws).get("deck")
    if not deck:
        raise HTTPException(404, "no generated deck for this session")
    data = get_store().get_bytes(ws, "outputs", deck["rel"])
    if data is None:
        raise HTTPException(404, "deck file missing from store")
    return Response(
        content=data,
        media_type=_PPTX_MIME,
        headers={"Content-Disposition":
                 f'attachment; filename="{Path(deck["filename"]).name}"'},
    )