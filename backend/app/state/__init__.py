"""Workspace + session state store. Local JSON for dev, Azure Table for prod.

The app depends only on the `StateStore` protocol, so switching backends is an
env flag (`STATE_BACKEND=local|azure`, defaults to STORAGE_BACKEND).
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import settings
from app.core.logging import get_logger
from .base import StateStore, new_workspace_state

log = get_logger("state")

@lru_cache(maxsize=1)
def get_state() -> StateStore:
    cfg = settings()
    if cfg.state_redis:
        from .state_redis import RedisStateStore
        log.info("state backend: redis (ns=%s)", cfg.redis_namespace)
        return RedisStateStore()
    if cfg.state_azure:
        from .state_table import TableStateStore
        log.info("state backend: azure table (%s / %s)",
            cfg.workspace_table, cfg.session_table)
        return TableStateStore()
    from .state_local import LocalStateStore
    log.info("state backend: local json (%s)", cfg.local_data_dir)
    return LocalStateStore()

__all__ = ["StateStore", "get_state", "new_workspace_state"]


