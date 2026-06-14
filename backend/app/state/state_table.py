"""Azure Table Storage state store (production) — SAS-token auth.

PartitionKey = workspace_id.
RowKey = "workspace" for the workspace record, "session::{sid}" for sessions.
The full dict is serialized into a single `json` column to avoid Table's
per-property size/type limits; a few hot fields are mirrored as columns for
cheap querying/debugging.
"""
from __future__ import annotations

import json
import time
from typing import Any

from app.core.config import settings
from .base import new_workspace_state

_WS_ROW = "workspace"
_SESS_PREFIX = "session::"


class TableStateStore:
    def __init__(self) -> None:
        from azure.core.credentials import AzureSasCredential
        from azure.data.tables import TableServiceClient

        cfg = settings()
        if not cfg.table_sas_token:
            raise RuntimeError("AZURE_TABLE_SAS_TOKEN (or storage SAS) required for azure state backend")
        cred = AzureSasCredential(cfg.table_sas_token.lstrip("?"))
        self.svc = TableServiceClient(endpoint=cfg.table_account_url, credential=cred)
        self.ws_table = self._table(cfg.workspace_table)
        self.sess_table = self._table(cfg.session_table)

    def _table(self, name: str):
        try:
            self.svc.create_table(name)
        except Exception:
            pass
        return self.svc.get_table_client(name)

    # --- workspace ---
    def get_workspace(self, ws: str) -> dict:
        try:
            ent = self.ws_table.get_entity(partition_key=ws, row_key=_WS_ROW)
            return json.loads(ent["json"])
        except Exception:
            state = new_workspace_state()
            self._put_ws(ws, state)
            return state

    def _put_ws(self, ws: str, state: dict) -> None:
        ent = {
            "PartitionKey": ws,
            "RowKey": _WS_ROW,
            "json": json.dumps(state),
            # mirrored hot fields (best-effort, may be truncated for query only)
            "built": bool(state.get("built")),
            "building": bool(state.get("building")),
            "blocks": int(state.get("blocks") or 0),
            "updated": float(state.get("updated") or time.time()),
        }
        self.ws_table.upsert_entity(ent)

    def update_workspace(self, ws: str, **fields: Any) -> dict:
        state = self.get_workspace(ws)
        state.update(fields)
        state["updated"] = time.time()
        self._put_ws(ws, state)
        return state

    def list_workspaces(self) -> list[str]:
        out: set[str] = set()
        for ent in self.ws_table.query_entities(f"RowKey eq '{_WS_ROW}'"):
            out.add(ent["PartitionKey"])
        return sorted(out)

    def delete_workspace(self, ws: str) -> None:
        try:
            self.ws_table.delete_entity(partition_key=ws, row_key=_WS_ROW)
        except Exception:
            pass
        # delete its sessions too
        for ent in self.sess_table.query_entities(f"PartitionKey eq '{ws}'"):
            try:
                self.sess_table.delete_entity(partition_key=ws, row_key=ent["RowKey"])
            except Exception:
                pass

    # --- sessions ---
    def save_session(self, ws: str, sid: str, state: dict) -> None:
        self.sess_table.upsert_entity({
            "PartitionKey": ws,
            "RowKey": f"{_SESS_PREFIX}{sid}",
            "json": json.dumps(state),
            "updated": time.time(),
        })

    def load_session(self, ws: str, sid: str) -> dict | None:
        try:
            ent = self.sess_table.get_entity(partition_key=ws, row_key=f"{_SESS_PREFIX}{sid}")
            return json.loads(ent["json"])
        except Exception:
            return None

    def delete_session(self, ws: str, sid: str) -> None:
        try:
            self.sess_table.delete_entity(partition_key=ws, row_key=f"{_SESS_PREFIX}{sid}")
        except Exception:
            pass