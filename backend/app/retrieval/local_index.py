"""Local retriever — a per-workspace vector index persisted in the store.

The index is written to `processing/index.json` via the storage backend (not the
temp build dir), so any API replica can load it for queries. Uses cosine over
Azure embeddings when available, otherwise a deterministic keyword overlap score.
"""
from __future__ import annotations

import json
import re
from collections import Counter

from app.core import llm
from app.core.ckm import ContentBlock
from app.core.logging import get_logger
from .base import Hit
from .graph_expand import GraphExpander

log = get_logger("retrieval")

_INDEX_REL = "index.json"
_GRAPH_BOOST = 0.5  # neighbor bonus = _GRAPH_BOOST * seed_score
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9/_-]{2,}")


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


class LocalRetriever:
    backend = "local"

    def _store(self):
        from app.storage import get_store
        return get_store()

    # --- build ---
    def index(self, ws: str, blocks: list[ContentBlock]) -> int:
        docs = [{
            "id": b.id,
            "source": b.source,
            "title": b.title,
            "text": b.text,
            "modality": b.modality,
            "timestamp": b.timestamp,
        } for b in blocks]

        texts = [f"{b.title}\n{b.text}".strip() for b in blocks]
        vectors = llm.embed(texts) if texts else None
        model = "embedding" if vectors else "keyword"
        if vectors:
            for d, v in zip(docs, vectors):
                d["vector"] = v

        payload = {"model": model, "docs": docs}
        self._store().put_bytes(
            ws, "processing", _INDEX_REL,
            json.dumps(payload).encode("utf-8"),
        )
        log.info("indexed %d block(s) for ws=%s (mode=%s)", len(docs), ws, model)
        return len(docs)

    # --- query ---
    def _load(self, ws: str) -> dict | None:
        raw = self._store().get_bytes(ws, "processing", _INDEX_REL)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return None

    def query(
        self,
        ws: str,
        text: str,
        *,
        top_k: int = 8,
        sources: list[str] | None = None,
        modalities: list[str] | None = None,
        graph_expand: bool = True,
        graph_hops : int=1,
    ) -> list[Hit]:
        index = self._load(ws)
        if not index or not index.get("docs"):
            return []

        # session scope: restrict to selected sources / modalities
        src_set = {s for s in (sources or [])}
        mod_set = {m for m in (modalities or [])}
        docs = [
            d for d in index["docs"]
            if (not src_set or d.get("source") in src_set)
            and (not mod_set or d.get("modality") in mod_set)
        ]
        if not docs:
            return []
        
        #1. base relevance score per doc ( vector cosine or keyword overlap)
        base: dict[str,list] = {} # doc_id -> [score, doc]
        if index.get("model") == "embedding" and (qv := llm.embed([text])):
            for d in docs:
                base[d["id"]] = [self._cosine(qv[0], d.get("vector") or []), d]
        
        else:
            q = Counter(_tokens(text))
            for d in docs:
                toks = Counter(_tokens(f"{d.get('title','')} {d.get('text','')}"))
                overlap = sum(min(c, toks.get(t, 0)) for t, c in q.items())
                base[d["id"]] = [float(overlap), d]

        # 2. graph expansion: boost blocks adjacent to the strongest seeds
        if graph_expand:
            expander = GraphExpander.from_store(self._store(), ws)
            if expander:
                in_scope = set(base)
                seeds = sorted(base.items(), key=lambda kv: kv[1][0], reverse=True)
                bonus: dict[str, float] = {}
                for sid, (sscore, _) in seeds[:top_k]:
                    if sscore <= 0:
                        continue
                    for nid in expander.neighbour(sid, hops=graph_hops):
                        if nid in in_scope:
                            bonus[nid] = max(bonus.get(nid, 0.0), _GRAPH_BOOST * sscore)
                for nid, b in bonus.items():
                    base[nid][0] += b

        # 3. final ranking
        ranked = sorted(base.values(), key=lambda x: x[0], reverse=True)
        return [self._hit(d, s) for s, d in ranked[:top_k] if s > 0]   

        
    def clear(self, ws: str) -> None:
        store = self._store()
        if store.exists(ws, "processing", _INDEX_REL):
            store.delete(ws, "processing", _INDEX_REL)

    # --- helpers ---
    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        import numpy as np
        va, vb = np.asarray(a, dtype="float32"), np.asarray(b, dtype="float32")
        na, nb = np.linalg.norm(va), np.linalg.norm(vb)
        if na == 0 or nb == 0:
            return 0.0
        return float(va.dot(vb) / (na * nb))

    @staticmethod
    def _hit(d: dict, score: float) -> Hit:
        return Hit(
            block_id=d["id"], source=d.get("source", ""), title=d.get("title", ""),
            text=d.get("text", ""), modality=d.get("modality", ""),
            score=score, timestamp=d.get("timestamp"),
        )