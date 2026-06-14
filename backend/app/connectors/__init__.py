"""External source connectors (Jira, SharePoint) — fetched live at build time.

Each connector exposes `enabled()` and `fetch(...) -> list[ContentBlock]`. They
are invoked by the build worker after file extraction and their blocks are
appended to the CKM.
"""

from __future__ import annotations

from app.core.ckm import ContentBlock
from app.core.logging import get_logger
from . import jira_connector, sharepoint_connector

log = get_logger("connectors")

def fetch_all(*, jira_jql: str | None = None, sp_folder: str | None = None) -> list[ContentBlock]:
    """Run every configured connector and return their combined blocks."""
    blocks: list[ContentBlock] = []
    if jira_connector.enabled():
        try:
            got = jira_connector.fetch(jira_jql)
            log.info("jira: %d block(s)", len(got))
            blocks.extend(got)
        except Exception as exc:
            log.warning("jira connector failed: %s", exc)
    if sharepoint_connector.enabled():
        try:
            got = sharepoint_connector.fetch(sp_folder)
            log.info("sharepoint: %d block(s)", len(got))
            blocks.extend(got)
        except Exception as exc:
            log.warning("sharepoint connector failed: %s", exc)
    return blocks


__all__ = ["fetch_all", "jira_connector", "sharepoint_connector"]