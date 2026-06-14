"""Storage protocol shared by all backends.

Categories scope a workspace's files. Tools need real OS paths (ffmpeg,
openpyxl, python-pptx), so a build always runs against a local working dir:
`download_category` pulls a workspace's files into it, `upload_category` pushes
results back. Locally these are no-ops over the real folder.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

Category = Literal["inputs", "processing", "outputs"]

@runtime_checkable
class Storage(Protocol):
    # --- single files ---
    def put_bytes(self, ws: str, category: Category, rel: str, data: bytes) -> str: ...
    def put_file(self, ws: str, category: Category, rel: str, src: Path) -> str: ...
    def get_bytes(self, ws: str, category: Category, rel: str) -> bytes | None: ...
    def exists(self, ws: str, category: Category, rel: str) -> bool: ...
    def delete(self, ws: str, category: Category, rel: str) -> None: ...
    def list(self, ws: str, category: Category) -> list[dict]: ...

    # --- bulk sync between the store and a local working dir ---
    def download_category(self, ws: str, category: Category, dest: Path) -> Path: ...
    def upload_category(self, ws: str, category: Category, src: Path) -> None: ...

    # --- serving ---
    def download_url(self, ws: str, category: Category, rel: str) -> str: ...

    