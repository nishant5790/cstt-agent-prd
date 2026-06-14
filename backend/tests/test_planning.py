"""Offline regression for the planning loop (LLM disabled -> deterministic path)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture()
def built_ws(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("STATE_BACKEND", "local")
    monkeypatch.setenv("RETRIEVAL_BACKEND", "local")
    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path / "workspaces"))

    from app.core import llm
    monkeypatch.setattr(llm, "available", lambda: False)
    monkeypatch.setattr(llm, "embeddings_available", lambda: False)
    monkeypatch.setattr(llm, "embed", lambda *a, **k: None)
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: None)

    from app import storage, state, retrieval
    for f in (storage.get_store, state.get_state, retrieval.get_retriever):
        f.cache_clear()

    from app.core.ckm import CKM, ContentBlock, KnowledgeGraph, Node, Edge
    from app.storage import get_store
    from app.state import get_state
    from app.retrieval import get_retriever

    ws = "ws-plan"
    blocks = [
        ContentBlock(id="b1", source="s.xlsx", modality="step",
                     title="Login", text="log into the salesforce uat portal"),
        ContentBlock(id="b2", source="s.xlsx", modality="step",
                     title="Accept", text="change the prospect status to accepted"),
        ContentBlock(id="b3", source="s.xlsx", modality="step",
                     title="Convert", text="change the prospect status to converted"),
    ]
    ckm = CKM(sources=["s.xlsx"], blocks=blocks)
    graph = KnowledgeGraph(
        nodes=[Node(id="topic::prospects", type="topic", label="Prospect Workflow"),
               Node(id="blk::b1", type="step", label="Login"),
               Node(id="blk::b2", type="step", label="Accept"),
               Node(id="blk::b3", type="step", label="Convert")],
        edges=[Edge(source="blk::b1", target="topic::prospects", relation="part_of"),
               Edge(source="blk::b2", target="topic::prospects", relation="part_of"),
               Edge(source="blk::b3", target="topic::prospects", relation="part_of")],
    )
    store = get_store()
    store.put_bytes(ws, "processing", "ckm.json", json.dumps(ckm.model_dump()).encode())
    store.put_bytes(ws, "processing", "knowledge_graph.json",
                    json.dumps(graph.model_dump()).encode())
    get_retriever().index(ws, blocks)
    get_state().update_workspace(ws, built=True, blocks=3, topics=["Prospect Workflow"])

    yield ws
    for f in (storage.get_store, state.get_state, retrieval.get_retriever):
        f.cache_clear()


def test_start_clarifies_when_vague(built_ws):
    from app.agents.conversation_agent import ConversationPlanner
    p = ConversationPlanner()
    out = p.start(built_ws, "make me something")  # no topic/audience
    assert out["status"] == "clarifying"
    assert out["questions"]


def test_full_loop_draft_revise_approve(built_ws):
    from app.agents.conversation_agent import ConversationPlanner
    from app.storage import get_store
    p = ConversationPlanner()

    out = p.start(built_ws, "beginner deck on Prospect Workflow")
    assert out["status"] == "drafted"
    assert out["plan"] and out["plan"]["slides"]
    sid = out["sid"]

    revised = p.revise(built_ws, sid, "add a slide about converting prospects")
    assert revised["status"] == "drafted"

    approved = p.approve(built_ws, sid)
    assert approved["status"] == "approved"
    assert get_store().exists(built_ws, "outputs", f"plan-{sid}.json")


def test_answer_advances_clarifying(built_ws):
    from app.agents.conversation_agent import ConversationPlanner
    p = ConversationPlanner()
    out = p.start(built_ws, "make me something")
    sid = out["sid"]
    ans = p.answer(built_ws, sid, {"q1": "Prospect Workflow", "q2": "beginner"})
    assert ans["status"] == "drafted"
    assert ans["plan"]