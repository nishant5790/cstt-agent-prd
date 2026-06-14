"""Retriever factory — local vector index or Azure AI Search by RETRIEVAL_BACKEND."""
from __future__ import annotations

from functools import lru_cache

from app.core.config import settings
from .base import Hit, Retriever


@lru_cache
def get_retriever() -> Retriever:
    if settings().retrieval_azure:
        from .azure_search import AzureSearchRetriever
        return AzureSearchRetriever()
    from .local_index import LocalRetriever
    return LocalRetriever()


__all__ = ["get_retriever", "Retriever", "Hit"]