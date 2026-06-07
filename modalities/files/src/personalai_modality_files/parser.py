"""Lightweight file parsers + chunking for ingestion (M3-2).

Pure functions over in-memory bytes (no network, no DB). Supports txt/markdown (direct), PDF
(pypdf), and DOCX (python-docx). Treat all input as untrusted: we only extract text — no active
content is executed.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import PurePosixPath

_TEXT_EXTS = {".txt": "text/plain", ".md": "text/markdown", ".markdown": "text/markdown"}


@dataclass(frozen=True)
class ParsedDocument:
    """Extracted text plus the detected MIME type."""

    text: str
    mime: str


class UnsupportedFileTypeError(Exception):
    """Raised when a file extension is not supported."""


def parse_document(content: bytes, filename: str) -> ParsedDocument:
    """Extract text from ``content`` based on ``filename``'s extension."""
    ext = PurePosixPath(filename).suffix.lower()
    if ext in _TEXT_EXTS:
        return ParsedDocument(text=content.decode("utf-8", errors="replace"), mime=_TEXT_EXTS[ext])
    if ext == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
        return ParsedDocument(text=text, mime="application/pdf")
    if ext == ".docx":
        import docx

        document = docx.Document(io.BytesIO(content))
        text = "\n".join(p.text for p in document.paragraphs)
        return ParsedDocument(
            text=text,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    raise UnsupportedFileTypeError(f"unsupported file type: {ext or filename!r}")


def chunk_text(text: str, *, size: int = 1000, overlap: int = 150) -> list[str]:
    """Split ``text`` into overlapping chunks of up to ``size`` characters."""
    if size <= 0:
        raise ValueError("size must be positive")
    if not 0 <= overlap < size:
        raise ValueError("overlap must be >= 0 and < size")
    cleaned = text.strip()
    if not cleaned:
        return []
    step = size - overlap
    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        chunk = cleaned[start : start + size].strip()
        if chunk:
            chunks.append(chunk)
        start += step
    return chunks
