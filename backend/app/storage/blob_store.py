"""Azure Blob Storage backend (production) — SAS-token authentication.

The SAS token (account- or container-scoped) is the only credential the backend
holds; no account key is stored. Because new SAS cannot be minted without the
account key, `download_url` simply appends the held SAS to the blob URL, so the
SAS must include at least read (`r`) permission.
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger
from .base import Category

log = get_logger("storage.blob")

class BlobStorage:
    def __init__(self) -> None:
        from azure.storage.blob import BlobServiceClient

        cfg = settings()
        self.cfg = cfg
        self.container = cfg.blob_container
        if not cfg.azure_storage_sas_token:
            raise RuntimeError("AZURE_STORAGE_SAS_TOKEN is required for azure storage backend")
        # token may be stored with or without a leading '?'
        self._sas = cfg.azure_storage_sas_token.lstrip("?")
        self._account_url = cfg.blob_account_url
        self.svc = BlobServiceClient(account_url=self._account_url, credential=self._sas)
        # ensure container exists (SAS must allow create/list at container scope;
        # if it doesn't, pre-create the container in the portal and ignore this).
        try:
            self.svc.create_container(self.container)
        except Exception:
            pass

    def _name(self, ws: str, category: Category, rel: str) -> str:
        return f"{ws}/{category}/{rel}".replace("\\", "/")

    def _client(self, blob_name: str):
        return self.svc.get_blob_client(container=self.container, blob=blob_name)
 # --- single files ---
    def put_bytes(self, ws: str, category: Category, rel: str, data: bytes) -> str:
        name = self._name(ws, category, rel)
        self._client(name).upload_blob(data, overwrite=True)
        return name

    def put_file(self, ws: str, category: Category, rel: str, src: Path) -> str:
        with Path(src).open("rb") as fh:
            return self.put_bytes(ws, category, rel, fh.read())

    def get_bytes(self, ws: str, category: Category, rel: str) -> bytes | None:
        name = self._name(ws, category, rel)
        try:
            return self._client(name).download_blob().readall()
        except Exception:
            return None

    def exists(self, ws: str, category: Category, rel: str) -> bool:
        return self._client(self._name(ws, category, rel)).exists()

    def delete(self, ws: str, category: Category, rel: str) -> None:
        try:
            self._client(self._name(ws, category, rel)).delete_blob()
        except Exception:
            pass

    def list(self, ws: str, category: Category) -> list[dict]:
        prefix = f"{ws}/{category}/"
        cc = self.svc.get_container_client(self.container)
        out: list[dict] = []
        for b in cc.list_blobs(name_starts_with=prefix):
            out.append({"name": b.name[len(prefix):], "size": b.size or 0})
        return out

    # --- bulk sync ---
    def download_category(self, ws: str, category: Category, dest: Path) -> Path:
        dest.mkdir(parents=True, exist_ok=True)
        prefix = f"{ws}/{category}/"
        cc = self.svc.get_container_client(self.container)
        for b in cc.list_blobs(name_starts_with=prefix):
            rel = b.name[len(prefix):]
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as fh:
                fh.write(cc.get_blob_client(b.name).download_blob().readall())
        return dest

    def upload_category(self, ws: str, category: Category, src: Path) -> None:
        if not Path(src).exists():
            return
        src = Path(src)
        for f in src.rglob("*"):
            if f.is_file():
                rel = f.relative_to(src).as_posix()
                self.put_file(ws, category, rel, f)

    # --- serving ---
    def download_url(self, ws: str, category: Category, rel: str) -> str:
        """Return a directly-downloadable URL by appending the held SAS token.
        The configured SAS must grant read on this container/blob."""
        name = self._name(ws, category, rel)
        return f"{self._account_url}/{self.container}/{name}?{self._sas}"