"""Local JSON state store (development). One file per workspace + sessions dir."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from app.core.config import settings
from .base import new_workspace_state

_lock = threading.RLock()

class LocalStateStore:
    def __init__(self) -> None:
        self.root = Path(settings().local_data_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    def _ws_dir(self, ws: str) -> Path:
        d = self.root / ws
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _ws_file(self, ws: str) -> Path:
        return self._ws_dir(ws) / "_state.json"

    def _sess_file(self, ws: str, sid: str) -> Path:
        d = self._ws_dir(ws) / "_sessions"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{sid}.json"

    # --- workspace ---
    def get_workspace(self, ws: str) -> dict:
        with _lock:
            f = self._ws_file(ws)
            if not f.exists():
                state = new_workspace_state()
                f.write_text(json.dumps(state), encoding="utf-8")
                return state
            return json.loads(f.read_text(encoding="utf-8"))

    def update_workspace(self, ws: str, **fields: Any) -> dict:
        with _lock:
            state = self.get_workspace(ws)
            state.update(fields)
            state["updated"] = time.time()
            self._ws_file(ws).write_text(json.dumps(state), encoding="utf-8")
            return state

    def list_workspaces(self) -> list[str]:
        return sorted(p.name for p in self.root.iterdir()
                      if p.is_dir() and (p / "_state.json").exists())

    def delete_workspace(self, ws: str) -> None:
        import shutil
        with _lock:
            d = self.root / ws
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)

    # --- sessions ---
    def save_session(self, ws: str, sid: str, state: dict) -> None:
        with _lock:
            self._sess_file(ws, sid).write_text(json.dumps(state), encoding="utf-8")

    def load_session(self, ws: str, sid: str) -> dict | None:
        with _lock:
            f = self._sess_file(ws, sid)
            return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None

    def delete_session(self, ws: str, sid: str) -> None:
        with _lock:
            f = self._sess_file(ws, sid)
            if f.exists():
                f.unlink()