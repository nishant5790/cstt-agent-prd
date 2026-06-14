"""Azure AI Search retriever — one index for all workspaces, filtered by `workspace`.

Hybrid (vector + keyword) when an embedding deployment is configured, keyword-only
otherwise. The index is created on first use. Document keys are namespaced
`{ws}__{block_id}` to stay globally unique while keeping a per-workspace filter.
"""
from __future__ import annotations

import re

from app.core import llm
from app.core.config import settings
from app.core.ckm import ContentBlock
from app.core.logging import get_logger
from .base import Hit
from .graph_expand import GraphExpander

log = get_logger("retrieval")
_KEY_RE = re.compile(r"[^A-Za-z0-9_\-=]")


class AzureSearchRetriever:
    backend = "azure"

    def __init__(self) -> None:
        self.cfg = settings()
        if not self.cfg.search_configured:
            raise RuntimeError(
                "RETRIEVAL_BACKEND=azure but AZURE_SEARCH_ENDPOINT / "
                "AZURE_SEARCH_API_KEY are not set"
            )
        self._ensured = False

    def _cred(self):
        from azure.core.credentials import AzureKeyCredential
        return AzureKeyCredential(self.cfg.search_api_key)

    def _search_client(self):
        from azure.search.documents import SearchClient
        return SearchClient(self.cfg.search_endpoint, self.cfg.search_index, self._cred())

    def _doc_key(self, ws: str, block_id: str) -> str:
        return _KEY_RE.sub("_", f"{ws}__{block_id}")

    # --- index lifecycle ---
    def _ensure_index(self) -> None:
        if self._ensured:
            return
        from azure.search.documents.indexes import SearchIndexClient
        from azure.search.documents.indexes.models import (
            SearchIndex, SimpleField, SearchableField, SearchField,
            SearchFieldDataType, VectorSearch, HnswAlgorithmConfiguration,
            VectorSearchProfile,
        )
        client = SearchIndexClient(self.cfg.search_endpoint, self._cred())
        existing = {i for i in client.list_index_names()}
        if self.cfg.search_index in existing:
            self._ensured = True
            return

        fields = [
            SimpleField(name="id", type=SearchFieldDataType.String, key=True),
            SimpleField(name="workspace", type=SearchFieldDataType.String,
                        filterable=True),
            SimpleField(name="block_id", type=SearchFieldDataType.String),
            SimpleField(name="source", type=SearchFieldDataType.String,
                        filterable=True),
            SimpleField(name="modality", type=SearchFieldDataType.String,
                        filterable=True),
            SimpleField(name="timestamp", type=SearchFieldDataType.Double),
            SearchableField(name="title", type=SearchFieldDataType.String),
            SearchableField(name="text", type=SearchFieldDataType.String),
            SearchField(
                name="vector",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                vector_search_dimensions=self.cfg.search_vector_dim,
                vector_search_profile_name="default-profile",
            ),
        ]
        vector_search = VectorSearch(
            algorithms=[HnswAlgorithmConfiguration(name="default-hnsw")],
            profiles=[VectorSearchProfile(
                name="default-profile", algorithm_configuration_name="default-hnsw")],
        )
        client.create_index(SearchIndex(
            name=self.cfg.search_index, fields=fields, vector_search=vector_search))
        log.info("created Azure Search index %s", self.cfg.search_index)
        self._ensured = True

    # --- build ---
    def index(self, ws: str, blocks: list[ContentBlock]) -> int:
        self._ensure_index()
        self.clear(ws)  # idempotent rebuild

        texts = [f"{b.title}\n{b.text}".strip() for b in blocks]
        vectors = llm.embed(texts) if texts else None

        docs = []
        for i, b in enumerate(blocks):
            doc = {
                "id": self._doc_key(ws, b.id),
                "workspace": ws,
                "block_id": b.id,
                "source": b.source,
                "modality": b.modality,
                "timestamp": float(b.timestamp) if b.timestamp is not None else None,
                "title": b.title,
                "text": b.text,
            }
            if vectors:
                doc["vector"] = vectors[i]
            docs.append(doc)

        if docs:
            with self._search_client() as client:
                for i in range(0, len(docs), 1000):
                    client.upload_documents(docs[i:i + 1000])
        log.info("indexed %d block(s) into Azure Search for ws=%s (%s)",
                 len(docs), ws, "vector" if vectors else "keyword")
        return len(docs)

    # --- query ---
    def query(
        self,
        ws: str,
        text: str,
        *,
        top_k: int = 8,
        sources: list[str] | None = None,
        modalities: list[str] | None = None,
        graph_expand: bool = True,
        graph_hops: int = 1,
    ) -> list[Hit]:
        self._ensure_index()
        clauses = [f"workspace eq '{ws}'"]
        if sources:
            ors = " or ".join(f"source eq '{self._odata(s)}'" for s in sources)
            clauses.append(f"({ors})")
        if modalities:
            ors = " or ".join(f"modality eq '{self._odata(m)}'" for m in modalities)
            clauses.append(f"({ors})")
        flt = " and ".join(clauses)

        hits = self._run_search(text, flt, top_k)

        # graph expansion: fetch neighbours of the strongest seeds, then re-rank
        if graph_expand and hits:
            try:
                from app.storage import get_store
                expander = GraphExpander.from_store(get_store(), ws)
                if expander:
                    seed_scores = {h.block_id: h.score for h in hits}
                    neighbour_ids: set[str] = set()
                    for bid, sc in list(seed_scores.items())[:top_k]:
                        neighbour_ids |= expander.neighbors(bid, hops=graph_hops)
                    neighbour_ids -= set(seed_scores)
                    if neighbour_ids:
                        ids = ",".join(self._odata(b) for b in neighbour_ids)
                        nflt = f"{flt} and search.in(block_id, '{ids}', ',')"
                        best = max(seed_scores.values())
                        extra = self._run_search(text, nflt, top_k)
                        seen = set(seed_scores)
                        for h in extra:
                            if h.block_id not in seen:
                                h.score = 0.5 * best  # neighbour boost
                                hits.append(h)
                                seen.add(h.block_id)
                        hits.sort(key=lambda h: h.score, reverse=True)
                        hits = hits[:top_k]
            except Exception as exc:  # graph expansion is best-effort
                log.warning("graph expansion skipped: %s", exc)
        return hits

    def _run_search(self, text: str, flt: str, top_k: int) -> list[Hit]:
        kwargs: dict = {
            "search_text": text,
            "filter": flt,
            "top": top_k,
            "select": ["block_id", "source", "title", "text", "modality", "timestamp"],
        }
        qv = llm.embed([text]) if text else None
        if qv:
            from azure.search.documents.models import VectorizedQuery
            kwargs["vector_queries"] = [VectorizedQuery(
                vector=qv[0], k_nearest_neighbors=top_k, fields="vector")]

        hits: list[Hit] = []
        with self._search_client() as client:
            for r in client.search(**kwargs):
                hits.append(Hit(
                    block_id=r.get("block_id", ""), source=r.get("source", ""),
                    title=r.get("title", ""), text=r.get("text", ""),
                    modality=r.get("modality", ""),
                    score=float(r.get("@search.score", 0.0)),
                    timestamp=r.get("timestamp"),
                ))
        return hits
    

    @staticmethod
    def _odata(value: str) -> str:
        """Escape single quotes for an OData string literal."""
        return (value or "").replace("'", "''")

    def clear(self, ws: str) -> None:
        self._ensure_index()
        with self._search_client() as client:
            ids = [{"id": r["id"]} for r in client.search(
                search_text="*", filter=f"workspace eq '{ws}'", select=["id"])]
            if ids:
                client.delete_documents(ids)