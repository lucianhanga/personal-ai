"""Central network-egress control (THREAT-MODEL: data exfiltration, local-first).

No component may reach the network unless egress is explicitly enabled in configuration, and
(optionally) the target host is on the allowlist. Outbound-calling code MUST call
:func:`assert_egress_allowed` before making a request; this is the single chokepoint that keeps
the system local-first by default.
"""

from __future__ import annotations

from personalai_core.config import CoreConfig

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class EgressBlockedError(Exception):
    """Raised when an outbound network call is attempted without explicit permission."""


def _is_loopback(host: str) -> bool:
    normalized = host.strip().lower()
    return normalized in _LOOPBACK_HOSTS or normalized.startswith("127.")


def assert_egress_allowed(config: CoreConfig, host: str | None = None) -> None:
    """Raise :class:`EgressBlockedError` unless the call is permitted.

    Local-first: connections to loopback (e.g. a local Ollama server) are always allowed.
    Otherwise egress must be enabled **and** the host must be on the allowlist. An empty allowlist
    is **fail-closed** (denies all non-loopback hosts) unless ``PERSONALAI_EGRESS_ALLOW_ANY=true``
    is explicitly set. An unknown host (``None``) is refused. Host comparison is case-insensitive.
    """
    if host is not None and _is_loopback(host):
        return
    if not config.egress_enabled:
        raise EgressBlockedError(
            f"network egress is disabled (attempted host: {host or 'unknown'}); "
            "enable PERSONALAI_EGRESS_ENABLED to allow outbound calls"
        )
    allowlist = config.allowed_egress_hosts
    if not allowlist:
        # Fail-closed: enabling egress without an allowlist does NOT open everything. The operator
        # must set PERSONALAI_ALLOWED_EGRESS_HOSTS, or explicitly opt into open egress.
        if config.egress_allow_any:
            return
        raise EgressBlockedError(
            f"network egress is enabled but no allowlist is set (host: {host or 'unknown'}); "
            "set PERSONALAI_ALLOWED_EGRESS_HOSTS, or PERSONALAI_EGRESS_ALLOW_ANY=true"
        )
    if host is None:
        raise EgressBlockedError(
            "an egress allowlist is configured but no host was provided; refusing (fail-closed)"
        )
    if host.strip().lower() not in {h.strip().lower() for h in allowlist}:
        raise EgressBlockedError(f"host {host!r} is not in the egress allowlist {tuple(allowlist)}")
