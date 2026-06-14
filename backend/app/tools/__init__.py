"""Source extraction tools.

Each tool turns one source into a list of `ContentBlock`. Tools register against
file extensions in `SOURCE_TOOLS`; `extract_file` dispatches a path to the right
tool. Heavy/optional deps are imported lazily inside each tool, so a missing
dependency only breaks its own format.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from app.core.ckm import ContentBlock

from ._base import (
    OnBlock,
    _emit,
    _slug,
    assets_dir,
    processing_dir,
    set_assets_dir,
    set_processing_dir,
    transcripts_dir,
)

SOURCE_TOOLS: dict[str, Callable[..., list[ContentBlock]]] = {}


def register(extensions: list[str], fn: Callable[..., list[ContentBlock]]) -> None:
    for ext in extensions:
        SOURCE_TOOLS[ext.lower()] = fn


def supported_suffixes() -> set[str]:
    return set(SOURCE_TOOLS)


def extract_file(path: Path, on_block: OnBlock = None) -> list[ContentBlock]:
    fn = SOURCE_TOOLS.get(path.suffix.lower())
    if not fn:
        return []
    return fn(path, on_block)


# ---- wire up the document tools (media + connectors added in later phases) ----
from .text_tool import extract_text 
from .xlsx_tool import extract_xlsx 
from .pdf_tool import extract_pdf    
from .docx_tool import extract_docx
from .audio_tool import extract_audio
from .video_tool import extract_video

register([".txt", ".md"], extract_text)
register([".xlsx", ".xls"], extract_xlsx)
register([".pdf"], extract_pdf)
register([".docx"], extract_docx)
register([".wav", ".m4a", ".mp3"], extract_audio)
register([".mp4", ".mov", ".mkv", ".avi", ".m4v"], extract_video)

__all__ = [
    "OnBlock", "SOURCE_TOOLS", "_emit", "_slug",
    "assets_dir", "set_assets_dir", "processing_dir", "set_processing_dir",
    "transcripts_dir", "extract_file", "register", "supported_suffixes",
    "extract_text", "extract_xlsx", "extract_pdf", "extract_docx",
]