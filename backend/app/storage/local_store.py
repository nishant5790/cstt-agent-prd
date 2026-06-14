"""Local filesystem storage backend (development default)."""
from __future__ import annotations

import shutil
from pathlib import Path

from app.core.config import settings
from .base import Category

class LocalStorage:
    def __init__(self) -> None:
        self.root = Path(settings().local_data_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, ws: str, category: Category) -> Path:
        d = self.root / ws / category
        d.mkdir(parents=True, exist_ok=True)
        return d
    
    def _path(self, ws: str, category: Category, rel: str) -> Path:
        # rel may contain subdirs (transcripts/x.json, assets/y.jpg)
        p = self._dir(ws, category) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    # --- single files ---
    def put_bytes(self, ws: str, category: Category, rel: str, data: bytes) -> str:
        p = self._path(ws, category, rel)
        p.write_bytes(data)
        return str(p)

    def put_file(self, ws: str, category: Category, rel: str, src: Path) -> str:
        p = self._path(ws, category, rel)
        shutil.copy2(src, p)
        return str(p)
    
    def get_bytes(self, ws: str, category: Category, rel: str) -> bytes | None:
        p = self._path(ws, category, rel)
        return p.read_bytes() if p.exists() else None

    def exists(self, ws: str, category: Category, rel: str) -> bool:
        return self._path(ws, category, rel).exists()

    def delete(self, ws: str, category: Category, rel: str) -> None:
        p = self._path(ws, category, rel)
        if p.exists():
            p.unlink()
    def list(self, ws: str, category: Category) -> list[dict]:
        d = self._dir(ws, category)
        out: list[dict] = []
        for f in sorted(d.rglob("*")):
            if f.is_file():
                out.append({"name": f.relative_to(d).as_posix(), "size": f.stat().st_size})
        return out

    # --- bulk sync ---
    def download_category(self, ws: str, category: Category, dest: Path) -> Path:
        dest.mkdir(parents=True, exist_ok=True)
        src = self._dir(ws, category)
        for f in src.rglob("*"):
            if f.is_file():
                target = dest / f.relative_to(src)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, target)
        return dest
    
    def upload_category(self, ws: str, category: Category, src: Path) -> None:
            if not src.exists():
                return
            d = self._dir(ws, category)
            for f in src.rglob("*"):
                if f.is_file():
                    target = d / f.relative_to(src)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, target)

    # --- serving ---
    def download_url(self, ws: str, category: Category, rel: str) -> str:
        # served by the backend's own download route in local mode
        return f"/api/workspaces/{ws}/download/{category}/{rel}"