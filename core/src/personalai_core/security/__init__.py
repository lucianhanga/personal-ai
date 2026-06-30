"""Security primitives: secret redaction, egress control, and an append-only audit log.

These are the central enforcement/observability points referenced by the threat model. They are
provided here in M0-10; components (providers, the Tool/MCP gateway) call them as they are built.
"""

from personalai_core.security.audit import (
    AuditEvent,
    AuditLog,
    SecurityContextError,
    current_conversation,
    current_security,
    require_security,
)
from personalai_core.security.egress import (
    EgressBlockedError,
    assert_egress_allowed,
    current_egress,
    effective_egress_config,
)
from personalai_core.security.redaction import REDACTED, redact
from personalai_core.security.ssrf import SsrfBlockedError, fetch_image

__all__ = [
    "REDACTED",
    "AuditEvent",
    "AuditLog",
    "EgressBlockedError",
    "SecurityContextError",
    "SsrfBlockedError",
    "assert_egress_allowed",
    "current_conversation",
    "current_egress",
    "current_security",
    "effective_egress_config",
    "fetch_image",
    "redact",
    "require_security",
]
