"""Central network-egress control (THREAT-MODEL: data exfiltration, local-first).

No component may reach the network unless egress is explicitly enabled in configuration, and
(optionally) the target host is on the allowlist. Outbound-calling code MUST call
:func:`assert_egress_allowed` before making a request; this is the single chokepoint that keeps
the system local-first by default.
"""

from __future__ import annotations

from personalai_core.config import CoreConfig


class EgressBlockedError(Exception):
    """Raised when an outbound network call is attempted without explicit permission."""


def assert_egress_allowed(config: CoreConfig, host: str | None = None) -> None:
    """Raise :class:`EgressBlockedError` unless egress is enabled (and host allow-listed)."""
    if not config.egress_enabled:
        raise EgressBlockedError(
            f"network egress is disabled (attempted host: {host or 'unknown'}); "
            "enable PERSONALAI_EGRESS_ENABLED to allow outbound calls"
        )
    if host is not None and config.allowed_egress_hosts and host not in config.allowed_egress_hosts:
        raise EgressBlockedError(
            f"host {host!r} is not in the egress allowlist {tuple(config.allowed_egress_hosts)}"
        )
