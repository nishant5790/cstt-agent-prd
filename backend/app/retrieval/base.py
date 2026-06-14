"""Retriever protocol shared by all backends.

A retriever turns the workspace's CKM blocks into a searchable index and answers
similarity queries for the planning / RAG phases. Both backends fall back to
keyword scoring when no embedding deployment is configured, so search always
works offline.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.core.ckm import ContentBlock


@dataclass
class Hit:
    block_id: str
    source: str
    title: str
    text: str
    modality: str
    score: float
    timestamp: float | None = None

    def to_dict(self) -> dict:
        return {
            "block_id": self.block_id,
            "source": self.source,
            "title": self.title,
            "text": self.text,
            "modality": self.modality,
            "score": round(self.score, 4),
            "timestamp": self.timestamp,
        }


@runtime_checkable
class Retriever(Protocol):
    def index(self, ws: str, blocks: list[ContentBlock]) -> int: ...
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
    ) -> list[Hit]: ...
    def clear(self, ws: str) -> None: ...