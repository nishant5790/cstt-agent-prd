"""Async job queue — decouples /api/build from build execution.

local mode  : jobs run in a daemon thread inside the API process (dev default).
azure mode  : jobs are sent to an Azure Service Bus queue and executed by one or
              more standalone `worker.py` containers (scale on queue length).
"""
from __future__ import annotations

from functools import lru_cache
from typing import Callable

from app.core.config import settings


@lru_cache
def _backend():
    if settings().queue_azure:
        from app.jobs.servicebus_queue import ServiceBusQueue
        return ServiceBusQueue()
    from app.jobs.local_queue import LocalQueue
    return LocalQueue()


def enqueue_build(ws: str, jira_jql: str | None = None,
                  sp_folder: str | None = None) -> None:
    _backend().enqueue({
        "type": "build",
        "ws": ws,
        "jira_jql": jira_jql,
        "sp_folder": sp_folder,
    })


def consume(handler: Callable[[dict], None]) -> None:
    """Block and process jobs forever (Azure worker only)."""
    _backend().consume(handler)