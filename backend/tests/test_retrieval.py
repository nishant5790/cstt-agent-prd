"""Regression tests for storage, state, build pipeline and graph-augmented retrieval.

Fully offline: embeddings and the chat LLM are disabled so the keyword path and
keyword labelling run deterministically (no Azure calls). Run from the backend dir:

    .\\.venv\\Scripts\\python.exe -m pytest tests -q
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
XLSX = BACKEND / "data" / "inputs" / "qtest-Test steps.xlsx"


@pytest.fixture()
def offline_ws(tmp_path, monkeypatch):
    """Isolated local workspace dir + LLM disabled; clears all cached factories."""
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("STATE_BACKEND", "local")
    monkeypatch.setenv("RETRIEVAL_BACKEND", "local")
    monkeypatch.setenv("QUEUE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path / "workspaces"))

    from app.core import llm
    monkeypatch.setattr(llm, "available", lambda: False)
    monkeypatch.setattr(llm, "embeddings_available", lambda: False)
    monkeypatch.setattr(llm, "embed", lambda *a, **k: None)

    # reset lru_cached singletons so they pick up the patched env
    from app import storage, state, retrieval
    storage.get_store.cache_clear()
    state.get_state.cache_clear()
    retrieval.get_retriever.cache_clear()

    yield "ws-test"

    storage.get_store.cache_clear()
    state.get_state.cache_clear()
    retrieval.get_retriever.cache_clear()


# --------------------------------------------------------------- storage / state
def test_storage_roundtrip(offline_ws):
    from app.storage import get_store
    store = get_store()
    ws = offline_ws
    store.put_bytes(ws, "inputs", "a.txt", b"hello")
    assert store.exists(ws, "inputs", "a.txt")
    assert store.get_bytes(ws, "inputs", "a.txt") == b"hello"
    names = [f["name"] for f in store.list(ws, "inputs")]
    assert "a.txt" in names
    store.delete(ws, "inputs", "a.txt")
    assert not store.exists(ws, "inputs", "a.txt")


def test_state_workspace(offline_ws):
    from app.state import get_state
    st = get_state()
    ws = offline_ws
    st.update_workspace(ws, built=True, blocks=3, topics=["x"])
    got = st.get_workspace(ws)
    assert got["built"] is True and got["blocks"] == 3
    assert ws in st.list_workspaces()
    st.delete_workspace(ws)


# --------------------------------------------------------------- retrieval core
def _blocks():
    from app.core.ckm import ContentBlock
    return [
        ContentBlock(id="b1", source="s.xlsx", modality="table_row",
                     title="Login", text="log into the salesforce uat portal"),
        ContentBlock(id="b2", source="s.xlsx", modality="table_row",
                     title="Accept", text="change the prospect status to accepted"),
        ContentBlock(id="b3", source="other.xlsx", modality="text",
                     title="Pricing", text="quarterly pricing discount tiers"),
    ]


def test_keyword_query(offline_ws):
    from app.retrieval import get_retriever
    r = get_retriever()
    ws = offline_ws
    assert r.index(ws, _blocks()) == 3
    hits = r.query(ws, "prospect status accepted", top_k=3, graph_expand=False)
    assert hits and hits[0].block_id == "b2"


def test_source_scope_filter(offline_ws):
    from app.retrieval import get_retriever
    r = get_retriever()
    ws = offline_ws
    r.index(ws, _blocks())
    hits = r.query(ws, "pricing discount", top_k=5, sources=["s.xlsx"],
                   graph_expand=False)
    assert all(h.source == "s.xlsx" for h in hits)  # other.xlsx excluded


def test_graph_expansion_pulls_neighbor(offline_ws):
    """b2 shares a topic with b1; a query matching only b1 should still surface b2."""
    import json
    from app.storage import get_store
    from app.retrieval import get_retriever
    ws = offline_ws
    r = get_retriever()
    r.index(ws, _blocks())

    graph = {
        "nodes": [
            {"id": "topic::salesforce", "type": "topic", "label": "Salesforce"},
            {"id": "blk::b1", "type": "step", "label": "Login"},
            {"id": "blk::b2", "type": "step", "label": "Accept"},
        ],
        "edges": [
            {"source": "blk::b1", "target": "topic::salesforce", "relation": "part_of"},
            {"source": "blk::b2", "target": "topic::salesforce", "relation": "part_of"},
        ],
    }
    get_store().put_bytes(ws, "processing", "knowledge_graph.json",
                          json.dumps(graph).encode())

    ids_no_graph = {h.block_id for h in r.query(ws, "login salesforce portal",
                                                top_k=1, graph_expand=False)}
    ids_graph = {h.block_id for h in r.query(ws, "login salesforce portal",
                                             top_k=3, graph_expand=True)}
    assert "b1" in ids_no_graph
    assert "b2" in ids_graph  # pulled in via shared topic


# --------------------------------------------------------------- full build path
@pytest.mark.skipif(not XLSX.exists(), reason="sample xlsx not present")
def test_build_pipeline_xlsx(offline_ws):
    from app.storage import get_store
    from app.state import get_state
    from app.api.knowledge import _build_worker
    ws = offline_ws
    store = get_store()
    store.put_bytes(ws, "inputs", XLSX.name, XLSX.read_bytes())
    get_state().update_workspace(ws, building=True, built=False)

    _build_worker(ws, None, None)

    st = get_state().get_workspace(ws)
    assert st["built"] is True
    assert st["blocks"] == 22
    assert st["error"] is None
    assert store.exists(ws, "processing", "index.json")
    assert store.exists(ws, "processing", "knowledge_graph.json")