"""Offline regression for auth (register / login / me) via TestClient.

Uses an isolated temp data dir + local state backend so it never touches real
workspaces and needs no Redis/Azure.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STATE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    # rebuild the cached state store against the temp dir
    from app.state import get_state
    get_state.cache_clear()

    from app.main import app
    with TestClient(app) as c:
        yield c
    get_state.cache_clear()


def test_register_then_me(client):
    r = client.post("/api/auth/register",
                    json={"email": "a@b.com", "password": "secret12"})
    assert r.status_code == 201, r.text
    body = r.json()
    token = body["access_token"]
    assert body["user"]["email"] == "a@b.com"
    assert "password_hash" not in body["user"]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "a@b.com"


def test_duplicate_register_rejected(client):
    client.post("/api/auth/register", json={"email": "d@b.com", "password": "secret12"})
    r = client.post("/api/auth/register", json={"email": "d@b.com", "password": "secret12"})
    assert r.status_code == 400


def test_login_ok_and_wrong_password(client):
    client.post("/api/auth/register", json={"email": "c@b.com", "password": "secret12"})

    ok = client.post("/api/auth/login", json={"email": "c@b.com", "password": "secret12"})
    assert ok.status_code == 200
    assert ok.json()["access_token"]

    bad = client.post("/api/auth/login", json={"email": "c@b.com", "password": "wrongpass"})
    assert bad.status_code == 401


def test_me_requires_token(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me",
                      headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401


def test_short_password_rejected(client):
    r = client.post("/api/auth/register", json={"email": "e@b.com", "password": "short"})
    assert r.status_code == 422  # pydantic min_length
