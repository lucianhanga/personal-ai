"""Agent message envelope (ADR-0003).

The typed envelope that flows between agents, the backend, and the UI. Agents never pass
free-form text to each other; ``payload`` is itself a schema-validated structure (free text,
when present, is one field inside it). The wire shape is ``{from, to, type, payload,
schema_version}``; ``from`` is exposed via an alias since it is a Python keyword.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import Field

from personalai_contracts.schemas.base import VersionedModel


class AgentMessage(VersionedModel):
    """A single typed message in an agent conversation/workflow."""

    SCHEMA_ID: ClassVar[str] = "personalai.agent.message"
    SCHEMA_VERSION: ClassVar[str] = "1.0.0"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    from_: str = Field(alias="from", description="Sender agent/component id.")
    to: str = Field(description="Recipient agent/component id.")
    type: str = Field(description="Message type discriminator (e.g. 'plan', 'tool_call').")
    payload: Mapping[str, Any] = Field(
        default_factory=dict, description="Schema-validated structured body."
    )
    schema_version: str = Field(default=SCHEMA_VERSION)
