"""Standalone build worker.

In Azure mode this process long-polls the Service Bus queue and runs each build
job to completion, then ACKs the message. Scale it independently of the API
(e.g. KEDA on queue length). In local mode there is no separate worker — builds
run in-process via the API — so this exits with a hint.
"""
from __future__ import annotations

from app.core.config import settings
from app.core.logging import get_logger
from app.jobs import consume
from app.jobs.handlers import handle_job

log = get_logger("worker")


def main() -> None:
    cfg = settings()
    if not cfg.queue_azure:
        log.warning("QUEUE_BACKEND is not 'azure' — builds run in-process via the "
                    "API; no separate worker needed. Exiting.")
        return
    log.info("worker started — queue=%s, waiting for build jobs…", cfg.servicebus_queue)
    consume(handle_job)


if __name__ == "__main__":
    main()