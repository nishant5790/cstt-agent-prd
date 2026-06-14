"""SharePoint connector — pull documents from a site library via Microsoft Graph.

Downloads supported files to a temp dir and runs the normal extraction tools, so
SharePoint docs become CKM blocks just like local uploads.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import requests

from app import tools
from app.core.ckm import ContentBlock
from app.core.config import settings
from app.core.logging import get_logger

log = get_logger("connectors.sharepoint")

_GRAPH = "https://graph.microsoft.com/v1.0"


def enabled() -> bool:
    return settings().sharepoint_configured


def _token(cfg) -> str:
    import msal

    app = msal.ConfidentialClientApplication(
        client_id=cfg.sp_client_id,
        authority=f"https://login.microsoftonline.com/{cfg.sp_tenant_id}",
        client_credential=cfg.sp_client_secret,
    )
    result = app.acquire_token_for_client(
        scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in result:
        raise RuntimeError(f"Graph auth failed: {result.get('error_description', result)}")
    return result["access_token"]


def _site_id(headers, site_url: str) -> str:
    # site_url like https://contoso.sharepoint.com/sites/Team
    from urllib.parse import urlparse

    parsed = urlparse(site_url)
    host = parsed.netloc
    path = parsed.path.lstrip("/")
    r = requests.get(f"{_GRAPH}/sites/{host}:/{path}", headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()["id"]


def fetch(folder: str | None = None) -> list[ContentBlock]:
    cfg = settings()
    headers = {"Authorization": f"Bearer {_token(cfg)}"}
    site_id = _site_id(headers, cfg.sp_site_url)

    # default drive (document library) root children
    r = requests.get(f"{_GRAPH}/sites/{site_id}/drive/root/children",
                     headers=headers, timeout=30)
    r.raise_for_status()
    items = r.json().get("value", [])
    supported = tools.supported_suffixes()

    blocks: list[ContentBlock] = []
    with tempfile.TemporaryDirectory() as tmp:
        for item in items:
            name = item.get("name", "")
            dl = item.get("@microsoft.graph.downloadUrl")
            if not dl or Path(name).suffix.lower() not in supported:
                continue
            local = Path(tmp) / name
            with requests.get(dl, timeout=120, stream=True) as resp:
                resp.raise_for_status()
                with local.open("wb") as fh:
                    for chunk in resp.iter_content(1024 * 256):
                        fh.write(chunk)
            try:
                got = tools.extract_file(local)
            except Exception as exc:
                log.warning("sharepoint extract failed for %s: %s", name, exc)
                continue
            for b in got:
                b.source = f"sharepoint:{name}"
            blocks.extend(got)
            log.info("sharepoint %s -> %d block(s)", name, len(got))
    return blocks