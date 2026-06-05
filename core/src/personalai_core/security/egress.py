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
    """Raise :class:`EgressBlockedError` unless egress is enabled (and host allow-listed).

    Fail-closed: if an allowlist is configured, a request with an unknown host (``None``) is
    refused, and host comparison is case-insensitive (DNS is case-insensitive).
    """
    if not config.egress_enabled:
        raise EgressBlockedError(
            f"network egress is disabled (attempted host: {host or 'unknown'}); "
            "enable PERSONALAI_EGRESS_ENABLED to allow outbound calls"
        )
    allowlist = config.allowed_egress_hosts
    if not allowlist:
        return  # egress enabled, no host restriction
    if host is None:
        raise EgressBlockedError(
            "an egress allowlist is configured but no host was provided; refusing (fail-closed)"
        )
    if host.strip().lower() not in {h.strip().lower() for h in allowlist}:
        raise EgressBlockedError(f"host {host!r} is not in the egress allowlist {tuple(allowlist)}")
