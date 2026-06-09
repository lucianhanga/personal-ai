"""An HTTP GET tool, gated by the egress allowlist (the canonical side-effect example).

Requires the NETWORK permission (granted at the gateway) AND, per-call, the target host must pass
the injected egress check (wired to the core egress allowlist by the composition root). Redirects
are disabled so a response cannot bounce to a disallowed host. HIGH risk.
"""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlparse

import httpx

from personalai_contracts.ports import ToolCall, ToolResult
from personalai_contracts.schemas.tools import (
    Permission,
    PermissionType,
    Provenance,
    RiskLevel,
    ToolManifest,
)

# Returns True if egress to the given host is permitted (no exception coupling to the core).
EgressAllowed = Callable[[str], bool]

HTTP_FETCH_MANIFEST = ToolManifest(
    name="http_fetch",
    version="1.0.0",
    provenance=Provenance(maintainer="PersonalAI", license="Apache-2.0"),
    description="Fetch the contents of an http(s) URL via GET. Returns status, content_type, body.",
    capabilities=["http.get"],
    permissions=(Permission(type=PermissionType.NETWORK, scope="*"),),
    inputs={
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    },
    outputs={
        "type": "object",
        "properties": {
            "status": {"type": "integer"},
            "content_type": {"type": "string"},
            "body": {"type": "string"},
        },
        "required": ["status", "body"],
    },
    egress=(),  # dynamic host -> enforced per-call by the handler's egress check
    risk=RiskLevel.HIGH,
)


class HttpFetch:
    """Fetch a URL with GET, size/time-limited, host gated by the egress allowlist."""

    name = "http_fetch"

    def __init__(
        self,
        egress_allowed: EgressAllowed,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
        max_chars: int = 20_000,
    ) -> None:
        self._egress_allowed = egress_allowed
        self._client = client
        self._timeout = timeout
        self._max_chars = max_chars

    async def invoke(self, call: ToolCall) -> ToolResult:
        url = str(call.args.get("url", ""))
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return ToolResult(ok=False, error="invalid url (http/https only)")
        if not self._egress_allowed(parsed.hostname):
            return ToolResult(ok=False, error=f"egress not allowed for host: {parsed.hostname}")

        client = self._client or httpx.AsyncClient(timeout=self._timeout, follow_redirects=False)
        try:
            response = await client.get(url)
            return ToolResult(
                ok=True,
                output={
                    "status": response.status_code,
                    "content_type": response.headers.get("content-type", ""),
                    "body": response.text[: self._max_chars],
                },
            )
        except httpx.HTTPError as exc:
            return ToolResult(ok=False, error=f"fetch failed: {exc}")
        finally:
            if self._client is None:
                await client.aclose()
