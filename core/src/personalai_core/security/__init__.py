"""Security primitives: secret redaction, egress control, and an append-only audit log.

These are the central enforcement/observability points referenced by the threat model. They are
provided here in M0-10; components (providers, the Tool/MCP gateway) call them as they are built.
"""

from personalai_core.security.audit import AuditEvent, AuditLog, current_conversation
from personalai_core.security.egress import EgressBlockedError, assert_egress_allowed
from personalai_core.security.redaction import REDACTED, redact

__all__ = [
    "REDACTED",
    "AuditEvent",
    "AuditLog",
    "EgressBlockedError",
    "assert_egress_allowed",
    "current_conversation",
    "redact",
]
