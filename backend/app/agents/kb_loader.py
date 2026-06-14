"""Load a workspace's CKM and knowledge graph from the storage backend.

The build pipeline persists `processing/ckm.json` and
`processing/knowledge_graph.json`. Planning happens later, per request, so it
reloads them from the store (works across replicas).
"""
from __future__ import annotations

import json

from app.core.ckm import CKM, KnowledgeGraph
from app.core.logging import get_logger

log = get_logger("kb")


def _load(ws: str, rel: str) -> dict | None:
    from app.storage import get_store
    raw = get_store().get_bytes(ws, "processing", rel)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def load_ckm(ws: str) -> CKM | None:
    data = _load(ws, "ckm.json")
    return CKM.model_validate(data) if data else None


def load_graph(ws: str) -> KnowledgeGraph | None:
    data = _load(ws, "knowledge_graph.json")
    return KnowledgeGraph.model_validate(data) if data else None