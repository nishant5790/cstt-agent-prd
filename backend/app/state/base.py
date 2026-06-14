"""StateStore protocol + the canonical workspace-state shape."""
from __future__ import annotations

import time
from typing import Any, Protocol, runtime_checkable

def new_workspace_state() -> dict[str, Any]:
    """The default state for a freshly-created workspace."""
    return {
        "built": False,
        "building": False,
        "error": None,
        "topics": [],
        "blocks": 0,
        "sources": [],
        "updated": time.time(),
    }


@runtime_checkable
class StateStore(Protocol):
    # --- workspace ---
    def get_workspace(self, ws: str) -> dict: ...
    def update_workspace(self, ws: str, **fields: Any) -> dict: ...
    def list_workspaces(self) -> list[str]: ...
    def delete_workspace(self, ws: str) -> None: ...

    # --- planner sessions (used from Phase 4) ---
    def save_session(self, ws: str, sid: str, state: dict) -> None: ...
    def load_session(self, ws: str, sid: str) -> dict | None: ...
    def delete_session(self, ws: str, sid: str) -> None: ...