"""Shared building blocks for source tools."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Optional

from app.core.ckm import ContentBlock
from app.core.config import settings

OnBlock = Optional[Callable[[ContentBlock], None]]

_cfg = settings()
# Extracted visuals (pdf figures, video frames) and intermediate artifacts
# default under the configured processing dir; the ExtractionAgent repoints
# these per run.
ASSETS_DIR = Path(_cfg.processing_dir) / "assets"
PROCESSING_DIR = Path(_cfg.processing_dir)


def _emit(blocks: list[ContentBlock], block: ContentBlock, on_block: OnBlock) -> None:
    blocks.append(block)
    if on_block is not None:
        try:
            on_block(block)
        except Exception:
            pass


def _slug(*parts: object) -> str:
    raw = "__".join(str(p) for p in parts)
    return re.sub(r"[^a-zA-Z0-9_]+", "-", raw).strip("-").lower()


def set_assets_dir(path: Path) -> None:
    global ASSETS_DIR
    ASSETS_DIR = Path(path)


def assets_dir() -> Path:
    from . import _base
    _base.ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    return _base.ASSETS_DIR


def set_processing_dir(path: Path) -> None:
    global PROCESSING_DIR
    PROCESSING_DIR = Path(path)


def processing_dir() -> Path:
    from . import _base
    _base.PROCESSING_DIR.mkdir(parents=True, exist_ok=True)
    return _base.PROCESSING_DIR


def transcripts_dir() -> Path:
    d = processing_dir() / "transcripts"
    d.mkdir(parents=True, exist_ok=True)
    return d