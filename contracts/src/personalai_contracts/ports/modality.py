"""Port: modality handler.

Normalizes a piece of media into text/structured content for the omni-capability pipeline.
The base port covers parsing/ingestion; specialized handlers (OCR, STT, TTS, render) are
added as adapters from M3/M8 under ``modalities/``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class ModalityKind(StrEnum):
    """The category of a media input."""

    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"


@dataclass(frozen=True)
class MediaRef:
    """A reference to a piece of media to be processed (treated as untrusted input)."""

    kind: ModalityKind
    uri: str
    mime_type: str | None = None


@dataclass(frozen=True)
class ParsedContent:
    """The normalized result of parsing media: text plus extracted metadata."""

    text: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class ModalityHandler(Protocol):
    """Parses media of a given kind into normalized content."""

    kind: ModalityKind

    def can_handle(self, mime_type: str) -> bool:
        """Whether this handler can process ``mime_type``."""
        ...

    async def parse(self, ref: MediaRef) -> ParsedContent:
        """Parse ``ref`` into normalized content. Implementations must sandbox parsing."""
        ...
