"""Offline regression for deck generation (no Azure)."""
from __future__ import annotations

import pytest


@pytest.fixture()
def ws_with_plan(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("STATE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path / "workspaces"))

    from app import storage, state
    storage.get_store.cache_clear()
    state.get_state.cache_clear()

    yield "ws-gen"

    storage.get_store.cache_clear()
    state.get_state.cache_clear()


def _plan():
    from app.agents.analysis_agent import DeckPlan, SlidePlan
    return DeckPlan(
        deck_title="Prospect Workflow — Training",
        topic="Prospect Workflow", audience="beginner",
        slides=[
            SlidePlan(title="Prospect Workflow", bullets=["Audience: beginner"]),
            SlidePlan(title="Login", bullets=["Log into the Salesforce UAT portal"],
                      notes="demo note"),
            SlidePlan(title="Accept", bullets=["Change the prospect status to accepted"]),
        ],
    )


def test_ppt_build_returns_valid_pptx_bytes():
    from io import BytesIO
    from pptx import Presentation
    from app.agents.ppt_agent import PptAgent

    data = PptAgent().build(_plan())
    assert data[:2] == b"PK"  # pptx is a zip
    prs = Presentation(BytesIO(data))
    assert len(prs.slides) == 3


def test_generate_and_download_via_store(ws_with_plan):
    from app.state import get_state
    from app.storage import get_store
    from app.agents.ppt_agent import PptAgent
    ws = ws_with_plan
    sid = "sid-1"

    plan = _plan()
    get_state().save_session(ws, sid, {"sid": sid, "plan": plan.model_dump()})

    data = PptAgent().build(plan)
    rel = f"deck-{sid}.pptx"
    get_store().put_bytes(ws, "outputs", rel, data)
    session = get_state().load_session(ws, sid)
    session["deck"] = {"rel": rel, "filename": "DECK.pptx", "slides": 3}
    get_state().save_session(ws, sid, session)

    again = get_state().load_session(ws, sid)
    assert again["deck"]["rel"] == rel
    assert get_store().get_bytes(ws, "outputs", rel)[:2] == b"PK"