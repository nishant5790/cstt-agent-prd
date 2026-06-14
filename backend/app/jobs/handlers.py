"""Job dispatch — maps a queued job to its handler (lazy imports avoid cycles)."""
from __future__ import annotations

from app.core.logging import get_logger

log = get_logger("jobs")


def handle_job(job: dict) -> None:
    jtype = job.get("type")
    if jtype == "build":
        from app.api.knowledge import _build_worker
        _build_worker(job["ws"], job.get("jira_jql"), job.get("sp_folder"))
    else:
        log.warning("unknown job type: %r — ignored", jtype)