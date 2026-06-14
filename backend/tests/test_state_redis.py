"""Offline regression for the Redis state backend (fakeredis, no server)."""
from __future__ import annotations

import pytest

fakeredis = pytest.importorskip("fakeredis")


@pytest.fixture()
def store():
    from app.state.state_redis import RedisStateStore
    client = fakeredis.FakeStrictRedis(decode_responses=True)
    return RedisStateStore(client=client)


def test_workspace_crud(store):
    ws = "s1"
    st = store.get_workspace(ws)            # auto-creates default state
    assert st["built"] is False
    store.update_workspace(ws, built=True, blocks=5)
    assert store.get_workspace(ws)["blocks"] == 5
    assert ws in store.list_workspaces()
    store.delete_workspace(ws)
    assert ws not in store.list_workspaces()


def test_sessions_roundtrip(store):
    ws, sid = "s1", "sess-1"
    assert store.load_session(ws, sid) is None
    store.save_session(ws, sid, {"sid": sid, "status": "drafted"})
    assert store.load_session(ws, sid)["status"] == "drafted"


def test_delete_workspace_cascades_sessions(store):
    ws, sid = "s2", "sess-2"
    store.save_session(ws, sid, {"x": 1})
    store.delete_workspace(ws)
    assert store.load_session(ws, sid) is None


def test_delete_session(store):
    ws, sid = "s3", "sess-3"
    store.save_session(ws, sid, {"x": 1})
    store.delete_session(ws, sid)
    assert store.load_session(ws, sid) is None
