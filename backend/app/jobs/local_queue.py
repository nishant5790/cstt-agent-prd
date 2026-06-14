"""In-process queue — runs each job in a daemon thread (single-process dev)."""
from __future__ import annotations

import threading
from typing import Callable

from app.core.logging import get_logger

log = get_logger("jobs")


class LocalQueue:
    backend = "local"

    def enqueue(self, job: dict) -> None:
        from app.jobs.handlers import handle_job
        log.info("local queue: running %s job in-process", job.get("type"))
        threading.Thread(target=handle_job, args=(job,), daemon=True).start()

    def consume(self, handler: Callable[[dict], None]) -> None:
        raise RuntimeError(
            "Local queue has no separate consumer — jobs run in-process. "
            "Set QUEUE_BACKEND=azure to use a standalone worker."
        )