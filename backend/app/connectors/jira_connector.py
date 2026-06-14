"""Jira connector — pull issues via JQL into ContentBlocks (one per issue)."""
from __future__ import annotations

import re

from app.core.ckm import ContentBlock
from app.core.config import settings
from app.core.logging import get_logger

log = get_logger("connectors.jira")

def _slug(*parts: object) -> str:
    raw = "__".join(str(p) for p in parts)
    return re.sub(r"[^a-zA-Z0-9_]+", "-", raw).strip("-").lower()


def enabled() -> bool:
    return settings().jira_configured


def fetch(jql: str | None = None, *, max_results: int = 100) -> list[ContentBlock]:
    from jira import JIRA

    cfg = settings()
    query = (jql or cfg.jira_jql or "ORDER BY updated DESC").strip()
    client = JIRA(server=cfg.jira_server_url,
                  basic_auth=(cfg.jira_username, cfg.jira_api_token))
    issues = client.search_issues(query, maxResults=max_results)
    log.info("jira JQL %r -> %d issue(s)", query, len(issues))

    blocks: list[ContentBlock] = []
    for issue in issues:
        f = issue.fields
        summary = (f.summary or "").strip()
        desc = (f.description or "").strip()
        status = getattr(getattr(f, "status", None), "name", "")
        issuetype = getattr(getattr(f, "issuetype", None), "name", "")
        text = (f"{issuetype} {issue.key} [{status}]: {summary}\n\n{desc}").strip()
        blocks.append(ContentBlock(
            id=_slug("jira", issue.key),
            source=f"jira:{issue.key}",
            modality="text",
            title=f"{issue.key} — {summary}"[:80],
            text=text,
            metadata={"key": issue.key, "status": status, "type": issuetype,
                      "url": f"{cfg.jira_server_url}/browse/{issue.key}"},
        ))
    return blocks