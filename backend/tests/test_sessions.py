"""Offline regression for the per-session model (auth + session-scoped KB).

Runs the full authenticated flow against the API with the LLM disabled (the
planner/analysis fall back to deterministic rules), a temp data dir and the
local state backend — no Redis/Azure needed. Build runs via the local in-thread
queue, so we poll status until built.
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

BUILD_FILE = ("data/inputs/qtest-Test steps.xlsx")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STATE_BACKEND", "local")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("QUEUE_BACKEND", "local")
    monkeypatch.setenv("RETRIEVAL_BACKEND", "local")
    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-which-is-long-enough-x")

    # disable the LLM -> deterministic offline pipeline
    from app.core import llm
    monkeypatch.setattr(llm, "available", lambda: False)
    monkeypatch.setattr(llm, "embeddings_available", lambda: False)
    monkeypatch.setattr(llm, "embed", lambda *a, **k: None)
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: None)
    monkeypatch.setattr(llm, "chat_text", lambda *a, **k: None)

    # rebuild cached singletons against the temp env
    from app.state import get_state
    from app.storage import get_store
    from app.retrieval import get_retriever
    get_state.cache_clear()
    get_store.cache_clear()
    get_retriever.cache_clear()

    # routers cache the state store at import; rebind to the fresh one so each
    # test is fully isolated regardless of order
    fresh_state = get_state()
    from app.api import knowledge, planning, generate as generate_api, sessions
    for mod in (knowledge, planning, generate_api, sessions):
        monkeypatch.setattr(mod, "_state", fresh_state, raising=False)

    from app.main import app
    with TestClient(app) as c:
        yield c

    get_state.cache_clear()
    get_store.cache_clear()
    get_retriever.cache_clear()


def _auth(client) -> dict:
    r = client.post("/api/auth/register",
                    json={"email": "u@x.com", "password": "secret12"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_session_requires_auth(client):
    assert client.get("/api/sessions").status_code == 401
    assert client.post("/api/sessions").status_code == 401


def test_create_list_and_isolation(client):
    h = _auth(client)
    sid = client.post("/api/sessions", headers=h,
                      json={"title": "Deck A"}).json()["sid"]
    listing = client.get("/api/sessions", headers=h).json()["sessions"]
    assert any(s["sid"] == sid and s["title"] == "Deck A" for s in listing)

    # a different user cannot see or touch this session
    r2 = client.post("/api/auth/register",
                     json={"email": "other@x.com", "password": "secret12"})
    h2 = {"Authorization": f"Bearer {r2.json()['access_token']}"}
    assert client.get("/api/sessions", headers=h2).json()["sessions"] == []
    assert client.get(f"/api/sessions/{sid}/status", headers=h2).status_code == 404


def test_full_flow(client):
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / BUILD_FILE
    assert src.exists(), f"missing sample: {src}"

    h = _auth(client)
    sid = client.post("/api/sessions", headers=h, json={}).json()["sid"]

    # upload
    with src.open("rb") as fh:
        up = client.post(f"/api/sessions/{sid}/upload", headers=h,
                         files=[("files", (src.name, fh,
                                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))])
    assert up.status_code == 200 and up.json()["saved"]

    # build + poll
    assert client.post(f"/api/sessions/{sid}/build", headers=h, json={}).json()["building"]
    for _ in range(60):
        st = client.get(f"/api/sessions/{sid}/status", headers=h).json()
        if not st.get("building"):
            break
        time.sleep(1)
    st = client.get(f"/api/sessions/{sid}/status", headers=h).json()
    assert st["built"], f"build failed: {st.get('error')}"
    assert st["blocks"] > 0

    # events feed populated
    evs = client.get(f"/api/sessions/{sid}/events", headers=h).json()
    assert evs["total"] >= 1
    stages = {e["stage"] for e in evs["events"]}
    assert "build" in stages

    # search
    sr = client.get(f"/api/sessions/{sid}/search", headers=h,
                    params={"q": "prospect status", "k": 3})
    assert sr.status_code == 200 and sr.json()["hits"]

    # plan: start -> (answer if clarifying) -> approve
    sess = client.post(f"/api/sessions/{sid}/plan/start", headers=h,
                       json={"request": "beginner deck on prospect conversion"}).json()
    if sess["status"] == "clarifying":
        answers = {q["id"]: "beginner; prospect conversion" for q in sess["questions"]}
        sess = client.post(f"/api/sessions/{sid}/plan/answer", headers=h,
                           json={"answers": answers}).json()
    assert sess["plan"], "no draft produced"
    sess = client.post(f"/api/sessions/{sid}/plan/approve", headers=h).json()
    assert sess["status"] == "approved"

    # generate + download
    gen_r = client.post(f"/api/sessions/{sid}/generate", headers=h)
    assert gen_r.status_code == 200, gen_r.text
    gen = gen_r.json()
    assert gen["ok"] and gen["bytes"] > 0
    dl = client.get(f"/api/sessions/{sid}/download", headers=h)
    assert dl.status_code == 200 and dl.content[:2] == b"PK"

    # session summary reflects plan + deck
    summary = client.get(f"/api/sessions/{sid}", headers=h).json()
    assert summary["has_plan"] and summary["has_deck"]

    # delete
    assert client.delete(f"/api/sessions/{sid}", headers=h).json()["ok"]
    assert client.get(f"/api/sessions/{sid}/status", headers=h).status_code == 404
