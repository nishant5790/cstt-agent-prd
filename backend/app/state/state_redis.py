"""Redis state store (STATE_BACKEND=redis).

Durable when Redis has persistence enabled (AOF/RDB, or Azure Cache for Redis).
Implements the same StateStore protocol as the local-json and Azure-table
backends, so nothing else in the app changes.

Keys (namespaced by REDIS_NAMESPACE):
  {ns}:ws:{ws}                 -> workspace state JSON
  {ns}:ws:index                -> SET of workspace ids (for list_workspaces)
  {ns}:ws:{ws}:sessions        -> SET of session ids in the workspace
  {ns}:sess:{ws}:{sid}         -> session state JSON
"""
from __future__ import annotations

import json
import time
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from .base import new_workspace_state

log = get_logger("state")


class RedisStateStore:
    backend = "redis"

    def __init__(self, client=None) -> None:
        cfg = settings()
        self.ns = cfg.redis_namespace.rstrip(":")
        if client is not None:
            self.r = client
        else:
            import redis

            if not cfg.redis_url:
                raise RuntimeError("REDIS_URL required for redis state backend")
            self.r = redis.from_url(cfg.redis_url, decode_responses=True)

    # --- key helpers ---
    def _k_ws(self, ws: str) -> str:
        return f"{self.ns}:ws:{ws}"

    def _k_ws_index(self) -> str:
        return f"{self.ns}:ws:index"

    def _k_ws_sessions(self, ws: str) -> str:
        return f"{self.ns}:ws:{ws}:sessions"

    def _k_sess(self, ws: str, sid: str) -> str:
        return f"{self.ns}:sess:{ws}:{sid}"

    # --- workspace ---
    def get_workspace(self, ws: str) -> dict:
        raw = self.r.get(self._k_ws(ws))
        if raw is None:
            state = new_workspace_state()
            self._put_ws(ws, state)
            return state
        return json.loads(raw)

    def _put_ws(self, ws: str, state: dict) -> None:
        self.r.set(self._k_ws(ws), json.dumps(state))
        self.r.sadd(self._k_ws_index(), ws)

    def update_workspace(self, ws: str, **fields: Any) -> dict:
        state = self.get_workspace(ws)
        state.update(fields)
        state["updated"] = time.time()
        self._put_ws(ws, state)
        return state

    def list_workspaces(self) -> list[str]:
        return sorted(self.r.smembers(self._k_ws_index()))

    def delete_workspace(self, ws: str) -> None:
        for sid in list(self.r.smembers(self._k_ws_sessions(ws))):
            self.r.delete(self._k_sess(ws, sid))
        self.r.delete(self._k_ws_sessions(ws))
        self.r.delete(self._k_ws(ws))
        self.r.srem(self._k_ws_index(), ws)

    # --- sessions ---
    def save_session(self, ws: str, sid: str, state: dict) -> None:
        self.r.set(self._k_sess(ws, sid), json.dumps(state))
        self.r.sadd(self._k_ws_sessions(ws), sid)

    def load_session(self, ws: str, sid: str) -> dict | None:
        raw = self.r.get(self._k_sess(ws, sid))
        return json.loads(raw) if raw is not None else None

    def delete_session(self, ws: str, sid: str) -> None:
        self.r.delete(self._k_sess(ws, sid))
        self.r.srem(self._k_ws_sessions(ws), sid)
