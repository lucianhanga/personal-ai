"""SSRF floor (THREAT-MODEL: server-side request forgery).

Controls applied unconditionally for any server-side image fetch:

- Scheme allowlist: only http and https.
- Port allowlist: 80, 443, or None (scheme default). Explicit non-standard ports are
  rejected because they commonly reach internal services (Redis :6379, etcd :2379, etc).
- IP validation: loopback, RFC 1918 private, link-local (including the cloud-metadata
  endpoint 169.254.169.254), unique-local IPv6 (fc00::/7), reserved, multicast, and
  unspecified addresses are all blocked. ``ipaddress.ip_address(ip).is_global`` is the
  primary gate; the explicit attribute checks below add defence-in-depth for addresses
  whose ``is_global`` classification varies across CPython versions.
- DNS pinning: ALL A/AAAA records are validated before the connect; the TCP connection is
  then pinned to the first validated IP so the live DNS record can never change between
  validation and connect (closes the DNS-rebinding window).
- TLS SNI and Host header preservation: even after IP pinning, the original hostname is
  used for TLS SNI and certificate verification so the server certificate is still checked
  against the intended host (see _PinnedIpTransport docstring).
- Redirect blocking: any 3xx response is an immediate block.  We never follow redirects
  because a redirect target could point at an internal address that was not validated.
- Accept-Encoding forced to identity: disables transfer compression so the byte-count
  ceiling applies to actual (decoded) payload bytes, not compressed wire bytes.
- Size cap: streaming is aborted once cumulative decoded bytes exceed max_bytes (5 MiB).
- Magic-byte image validation: only PNG, JPEG, GIF 87a/89a, and WEBP are accepted.
  Content-Type is NOT trusted because it is attacker-controlled; the magic bytes are
  authoritative.  SVG and all other formats are rejected.

This floor NEVER special-cases loopback as allowed.  Private/loopback are always blocked
regardless of any egress consent grant.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import urllib.parse
from typing import Final

import httpx

# ---------------------------------------------------------------------------
# Error class
# ---------------------------------------------------------------------------


class SsrfBlockedError(Exception):
    """Raised when an outbound fetch violates the SSRF floor."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_MAX_BYTES: Final[int] = 5 * 1024 * 1024  # 5 MiB
_ALLOWED_PORTS: Final[frozenset[int | None]] = frozenset({80, 443, None})
_ALLOWED_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https"})
# A descriptive User-Agent: many image hosts (e.g. Wikimedia) reject the default httpx UA with 403.
# Identifies the local image proxy honestly rather than spoofing a browser.
_USER_AGENT: Final[str] = "PersonalAI/1.0 (+https://github.com/lucianhanga/personal-ai)"

# Magic byte signatures for accepted raster image formats.
# SVG is explicitly excluded: it is text/XML and can contain scripts.
_MAGIC_JPEG: Final[bytes] = b"\xff\xd8\xff"
_MAGIC_PNG: Final[bytes] = b"\x89PNG"
_MAGIC_GIF87: Final[bytes] = b"GIF87a"
_MAGIC_GIF89: Final[bytes] = b"GIF89a"
_MAGIC_RIFF: Final[bytes] = b"RIFF"
_MAGIC_WEBP: Final[bytes] = b"WEBP"


# ---------------------------------------------------------------------------
# IP validation
# ---------------------------------------------------------------------------


def assert_public_ip(ip: str) -> None:
    """Raise :class:`SsrfBlockedError` unless *ip* is a routable public address.

    ``ipaddress.ip_address(ip).is_global`` is the primary gate.  The explicit
    attribute checks below provide defence-in-depth by rejecting addresses whose
    ``is_global`` value is unreliable in some CPython versions (e.g. 169.254.169.254
    has returned ``True`` in older Python 3.11.x builds):

    - loopback (127.0.0.0/8, ::1)
    - private RFC 1918 (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
    - link-local (169.254.0.0/16 — includes the IMDS cloud-metadata endpoint, fe80::/10)
    - unique-local IPv6 (fc00::/7)
    - reserved
    - multicast
    - unspecified (0.0.0.0 / ::)
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError as exc:
        raise SsrfBlockedError("non-public IP address blocked") from exc

    # Defence-in-depth explicit rejections (order does not affect correctness).
    if (
        addr.is_loopback
        or addr.is_private
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    ):
        raise SsrfBlockedError("non-public IP address blocked")

    # Canonical is_global gate — the definitive check.
    if not addr.is_global:
        raise SsrfBlockedError("non-public IP address blocked")


def resolve_and_validate(host: str) -> list[str]:
    """Resolve ALL A/AAAA records for *host* and validate every address.

    Raises :class:`SsrfBlockedError` if:

    - the hostname does not resolve (DNS failure or no records returned);
    - ANY resolved address fails :func:`assert_public_ip`.

    Returns the list of validated IP strings (may contain both IPv4 and IPv6
    addresses when the host has dual-stack records).
    """
    try:
        addrinfo = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SsrfBlockedError("hostname did not resolve") from exc

    if not addrinfo:
        raise SsrfBlockedError("hostname did not resolve")

    ips: list[str] = []
    for _family, _type, _proto, _canonname, sockaddr in addrinfo:
        ip = str(sockaddr[0])
        assert_public_ip(ip)  # raises SsrfBlockedError for any non-public address
        ips.append(ip)

    return ips


# ---------------------------------------------------------------------------
# IP-pinning transport (closes DNS-rebinding window)
# ---------------------------------------------------------------------------


class _PinnedIpTransport(httpx.AsyncBaseTransport):
    """httpx async transport that connects to a pre-resolved IP while preserving
    TLS SNI and the Host header for the original hostname.

    CISO NOTE — DNS pinning design
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    The IP is resolved exactly once, validated against the SSRF floor, and then
    hard-wired into every TCP connection by rewriting the request URL's host
    component to the pinned IP.  This closes the DNS-rebinding window: even if
    the DNS record changes between resolution and connect, the actual socket always
    dials the validated IP.

    TLS certificate verification uses the ORIGINAL hostname:

    * ``extensions["sni_hostname"]`` carries the original hostname as bytes for the
      TLS ClientHello SNI extension.  httpcore's SSL layer passes this value as
      ``server_hostname`` to ``SSLContext.wrap_socket``, which governs both the SNI
      extension sent to the server AND the certificate CN/SAN matching.
    * The ``Host`` header is preserved from ``request.headers`` unchanged.  httpx
      sets ``Host: original-hostname`` before it calls the transport, so copying the
      headers verbatim into the pinned request keeps the correct Host value even
      though the URL's host component has been replaced with the IP.

    Redirects are disabled on the outer ``httpx.AsyncClient`` (``follow_redirects=
    False``); 3xx responses are surfaced as ``SsrfBlockedError`` by the caller.

    The inner ``httpx.AsyncHTTPTransport(verify=True)`` uses certifi's CA bundle so
    HTTPS certificates are validated against the system-trusted root set with the
    original hostname as the expected name (via the sni_hostname extension above).
    """

    def __init__(self, pinned_ip: str, hostname: str) -> None:
        self._inner = httpx.AsyncHTTPTransport(verify=True)
        self._pinned_ip = pinned_ip
        self._hostname = hostname

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        # Rewrite URL host to the validated IP so the TCP socket dials the IP directly.
        pinned_url = request.url.copy_with(host=self._pinned_ip)

        extensions = dict(request.extensions)
        if request.url.scheme == "https":
            # Instruct httpcore to use the original hostname for TLS SNI and certificate
            # validation even though the socket connects to the pinned IP.
            extensions["sni_hostname"] = self._hostname.encode("ascii")

        # Preserve the original request headers (which carry Host: original-hostname),
        # replace only the URL host so the TCP dial goes to the IP.
        pinned_request = httpx.Request(
            method=request.method,
            url=pinned_url,
            headers=request.headers,
            content=request.content,
            extensions=extensions,
        )
        return await self._inner.handle_async_request(pinned_request)

    async def aclose(self) -> None:
        await self._inner.aclose()


# ---------------------------------------------------------------------------
# Magic-byte image detection
# ---------------------------------------------------------------------------


def _detect_mime(data: bytes) -> str | None:
    """Return the MIME type string based on magic bytes, or *None* for unrecognised types.

    Checks JPEG, PNG, GIF (87a and 89a), and WEBP.  All other formats — including
    SVG — return *None* and will be rejected by the caller.
    """
    if len(data) >= 3 and data[:3] == _MAGIC_JPEG:
        return "image/jpeg"
    if len(data) >= 4 and data[:4] == _MAGIC_PNG:
        return "image/png"
    if len(data) >= 6 and data[:6] in (_MAGIC_GIF87, _MAGIC_GIF89):
        return "image/gif"
    # WEBP: bytes 0-3 == "RIFF", bytes 8-11 == "WEBP"
    if len(data) >= 12 and data[:4] == _MAGIC_RIFF and data[8:12] == _MAGIC_WEBP:
        return "image/webp"
    return None


# ---------------------------------------------------------------------------
# Hardened server-side image fetch
# ---------------------------------------------------------------------------


async def _fetch_image_inner(
    url: str,
    max_bytes: int,
    timeout: float,
) -> tuple[str, bytes]:
    """Implementation detail — see :func:`fetch_image` for the public contract."""
    parsed = urllib.parse.urlparse(url)

    # --- Scheme check --------------------------------------------------------
    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise SsrfBlockedError("scheme not allowed")

    # --- Port check ----------------------------------------------------------
    port: int | None = parsed.port  # None means "scheme default" (80 or 443)
    if port not in _ALLOWED_PORTS:
        raise SsrfBlockedError("port not allowed")

    # --- Hostname extraction -------------------------------------------------
    hostname = parsed.hostname
    if not hostname:
        raise SsrfBlockedError("no hostname in URL")

    # --- DNS resolution + SSRF IP floor -------------------------------------
    # resolve_and_validate calls assert_public_ip on EVERY returned record;
    # raises SsrfBlockedError if any is non-public or the host does not resolve.
    ips = await asyncio.to_thread(resolve_and_validate, hostname)
    pinned_ip = ips[0]

    # --- Build the pinned-IP transport and fetch ----------------------------
    transport = _PinnedIpTransport(pinned_ip=pinned_ip, hostname=hostname)
    timeout_cfg = httpx.Timeout(timeout)

    async with (
        httpx.AsyncClient(
            transport=transport,
            follow_redirects=False,
            timeout=timeout_cfg,
        ) as client,
        client.stream(
            "GET",
            url,
            headers={"Accept-Encoding": "identity", "User-Agent": _USER_AGENT},
        ) as response,
    ):
        # --- Redirect block (3xx = block, not follow) -----------------------
        if response.is_redirect:
            raise SsrfBlockedError("redirect not followed")

        # --- Streaming body with size cap -----------------------------------
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes(chunk_size=8192):
            total += len(chunk)
            if total > max_bytes:
                raise SsrfBlockedError("response exceeds size cap")
            chunks.append(chunk)

    body = b"".join(chunks)

    # --- Magic-byte verification (NOT Content-Type — attacker-controlled) ---
    mime = _detect_mime(body)
    if mime is None:
        raise SsrfBlockedError("not a recognised raster image format")

    return mime, body


async def fetch_image(
    url: str,
    *,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    timeout: float = 10.0,
) -> tuple[str, bytes]:
    """Fetch a remote image server-side with the full SSRF floor applied.

    Security controls enforced (a uniform error is raised on any violation so
    internal topology is not leaked to callers):

    - scheme restricted to {http, https};
    - port restricted to {80, 443, or scheme default};
    - all resolved DNS addresses validated via :func:`resolve_and_validate`
      (rejects loopback, private, link-local, reserved, multicast, unspecified);
    - TCP connection pinned to the first validated IP (closes DNS-rebinding);
    - redirects disabled — any 3xx response is a block;
    - request header ``Accept-Encoding: identity`` (plain bytes, no compression);
    - streaming body aborted if cumulative decoded bytes exceed *max_bytes*;
    - magic-byte verification: PNG, JPEG, GIF (87a/89a), WEBP only; SVG rejected.

    Args:
        url: The remote image URL to fetch.
        max_bytes: Maximum total decoded response bytes (default 5 MiB).
        timeout: Total request timeout in seconds (default 10 s).

    Returns:
        A ``(mime_type, raw_bytes)`` tuple where *mime_type* is derived from magic
        bytes (e.g. ``"image/png"``).

    Raises:
        :class:`SsrfBlockedError`: for any security violation.  The exception
        message is always the same uniform string so internal check details are
        not leaked to callers.
    """
    _UNIFORM_MSG = "image could not be fetched"
    try:
        return await _fetch_image_inner(url, max_bytes, timeout)
    except SsrfBlockedError:
        # Re-raise with the uniform message — swallows the internal detail so
        # callers (and HTTP responses) never reveal which check failed.
        raise SsrfBlockedError(_UNIFORM_MSG) from None
    except Exception as exc:  # noqa: BLE001 — network errors, SSL, timeouts, etc.
        raise SsrfBlockedError(_UNIFORM_MSG) from exc
