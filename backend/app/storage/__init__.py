"""Storage abstraction: per-workspace object store with Local and Azure Blob
backends. The rest of the app depends only on the `Storage` protocol, so dev
runs against the local filesystem and prod against Azure Blob with no code
changes.

Layout per workspace (logical paths, identical across backends):
    {workspace_id}/inputs/<file>
    {workspace_id}/processing/<ckm.json | knowledge_graph.json | transcripts/* | assets/*>
    {workspace_id}/outputs/<DECK--*.pptx>
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import settings
from app.core.logging import get_logger
from .base import Storage

log = get_logger("storage")

@lru_cache(maxsize=1)
def get_store() -> Storage:
    cfg = settings()
    if cfg.storage_azure:
        from .blob_store import BlobStorage
        log.info("storage backend: azure blob (container=%s)", cfg.blob_container)
        return BlobStorage()
    from .local_store import LocalStorage
    log.info("storage backend: local (%s)", cfg.local_data_dir)
    return LocalStorage()


__all__ = ["Storage", "get_store"]