"""pdf source tool: one ContentBlock per page (text)."""
from __future__ import annotations

from pathlib import Path

from app.core.ckm import ContentBlock

from ._base import OnBlock, _emit, _slug


def extract_pdf(path: Path, on_block: OnBlock = None) -> list[ContentBlock]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    blocks: list[ContentBlock] = []
    for i, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if not text:
            continue
        first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
        _emit(blocks, ContentBlock(
            id=_slug(path.stem, "p", i),
            source=path.name,
            modality="text",
            title=(first_line[:80] or f"Page {i}"),
            text=text,
            metadata={"page": i},
        ), on_block)
    return blocks