"""SSRF floor unit tests.

Tests the public surface of personalai_core.security.ssrf:

- assert_public_ip: blocks loopback, RFC-1918 private, link-local (including
  169.254.169.254), IPv6 unique-local and loopback; allows a real public IP.
- resolve_and_validate: raises when ANY resolved address is non-public.
- fetch_image: blocks redirects, rejects SVG and magic-byte mismatches, enforces
  the size cap, and rejects invalid schemes and ports.

All network I/O (DNS + HTTP) is replaced with fakes so no real internet access
is needed.  The async ``fetch_image`` function is exercised via ``asyncio.run``,
mirroring the pattern used elsewhere in this test suite.
"""

from __future__ import annotations

import asyncio
import socket

import httpx
import pytest

from personalai_core.security.ssrf import (
    SsrfBlockedError,
    assert_public_ip,
    fetch_image,
    resolve_and_validate,
)

# ---------------------------------------------------------------------------
# assert_public_ip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",          # loopback
        "127.0.0.5",          # loopback range
        "::1",                 # IPv6 loopback
        "10.0.0.1",           # RFC-1918 class A
        "10.255.255.255",     # RFC-1918 class A (boundary)
        "172.16.0.1",         # RFC-1918 class B
        "172.31.255.255",     # RFC-1918 class B (boundary)
        "192.168.1.100",      # RFC-1918 class C
        "192.168.255.255",    # RFC-1918 class C (boundary)
        "169.254.169.254",    # AWS/GCP/Azure IMDS metadata endpoint
        "169.254.0.1",        # link-local range
        "0.0.0.0",            # unspecified
        "::",                  # IPv6 unspecified
        "fc00::1",             # IPv6 unique-local (fc00::/7)
        "fd00::1",             # IPv6 unique-local (fd00::/8 subset)
        "fe80::1",             # IPv6 link-local
        "224.0.0.1",          # multicast
        "255.255.255.255",    # limited broadcast / reserved
    ],
)
def test_assert_public_ip_blocks_non_public(ip: str) -> None:
    with pytest.raises(SsrfBlockedError):
        assert_public_ip(ip)


def test_assert_public_ip_allows_public() -> None:
    # 1.1.1.1 is Cloudflare's public resolver — globally routable by any definition.
    assert_public_ip("1.1.1.1")  # must not raise


def test_assert_public_ip_allows_another_public() -> None:
    assert_public_ip("8.8.8.8")  # Google DNS — also public


def test_assert_public_ip_rejects_invalid_string() -> None:
    with pytest.raises(SsrfBlockedError):
        assert_public_ip("not-an-ip")


# ---------------------------------------------------------------------------
# resolve_and_validate (DNS mocked via monkeypatch)
# ---------------------------------------------------------------------------


def _fake_getaddrinfo_public(
    host: str, port: object, **kwargs: object
) -> list[tuple[object, object, object, str, tuple[str, int]]]:
    """Return a single A record pointing to a public IP."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("1.1.1.1", 0))]


def _fake_getaddrinfo_private(
    host: str, port: object, **kwargs: object
) -> list[tuple[object, object, object, str, tuple[str, int]]]:
    """Return a record pointing to a private IP (RFC 1918)."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.1", 0))]


def _fake_getaddrinfo_mixed(
    host: str, port: object, **kwargs: object
) -> list[tuple[object, object, object, str, tuple[str, int]]]:
    """Return one public and one private record — ANY private must cause a block."""
    return [
        (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("1.1.1.1", 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.168.1.1", 0)),
    ]


def _fake_getaddrinfo_metadata(
    host: str, port: object, **kwargs: object
) -> list[tuple[object, object, object, str, tuple[str, int]]]:
    """Return the cloud-metadata IP 169.254.169.254."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("169.254.169.254", 0))]


def test_resolve_and_validate_passes_on_public_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "personalai_core.security.ssrf.socket.getaddrinfo", _fake_getaddrinfo_public
    )
    ips = resolve_and_validate("example.com")
    assert "1.1.1.1" in ips


def test_resolve_and_validate_blocks_private_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "personalai_core.security.ssrf.socket.getaddrinfo", _fake_getaddrinfo_private
    )
    with pytest.raises(SsrfBlockedError):
        resolve_and_validate("internal.corp")


def test_resolve_and_validate_blocks_any_private_in_mixed(monkeypatch: pytest.MonkeyPatch) -> None:
    # Even if some records are public, one private address must cause an immediate block.
    monkeypatch.setattr("personalai_core.security.ssrf.socket.getaddrinfo", _fake_getaddrinfo_mixed)
    with pytest.raises(SsrfBlockedError):
        resolve_and_validate("split-horizon.example.com")


def test_resolve_and_validate_blocks_cloud_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "personalai_core.security.ssrf.socket.getaddrinfo", _fake_getaddrinfo_metadata
    )
    with pytest.raises(SsrfBlockedError):
        resolve_and_validate("metadata.internal")


def test_resolve_and_validate_raises_on_dns_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail(*args: object, **kwargs: object) -> list[object]:
        raise socket.gaierror("NXDOMAIN")

    monkeypatch.setattr("personalai_core.security.ssrf.socket.getaddrinfo", _fail)
    with pytest.raises(SsrfBlockedError, match="hostname did not resolve"):
        resolve_and_validate("nxdomain.example.com")


# ---------------------------------------------------------------------------
# fetch_image (DNS + HTTP both mocked)
# ---------------------------------------------------------------------------

# Minimal valid magic-byte prefixes for each allowed image format.
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
_JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 100
_GIF_BYTES = b"GIF89a" + b"\x00" * 100
_WEBP_BYTES = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 100
_SVG_BYTES = b"<svg xmlns" + b"\x00" * 100
_UNKNOWN_BYTES = b"\x00\x01\x02\x03" + b"\x00" * 100


class _MockTransport(httpx.AsyncBaseTransport):
    """Fake transport that returns a canned response without touching the network."""

    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        # Use the same stream each call — copy content into a fresh Response so the
        # async iterator is not exhausted on a second call.
        return httpx.Response(
            status_code=self._response.status_code,
            headers=dict(self._response.headers),
            content=self._response.content,
        )

    async def aclose(self) -> None:
        pass


def _patch_fetch(
    monkeypatch: pytest.MonkeyPatch,
    *,
    response: httpx.Response,
    resolved_ip: str = "1.1.1.1",
) -> None:
    """Patch DNS resolution and the inner HTTP transport for fetch_image tests."""
    # Patch resolve_and_validate at the module level so asyncio.to_thread picks it up.
    monkeypatch.setattr(
        "personalai_core.security.ssrf.resolve_and_validate",
        lambda host: [resolved_ip],
    )
    # Replace httpx.AsyncHTTPTransport with our mock so _PinnedIpTransport._inner
    # is our fake transport — no real sockets opened.
    monkeypatch.setattr(
        "personalai_core.security.ssrf.httpx.AsyncHTTPTransport",
        lambda **kwargs: _MockTransport(response),
    )


def test_fetch_image_returns_png(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fetch(monkeypatch, response=httpx.Response(200, content=_PNG_BYTES))
    mime, data = asyncio.run(fetch_image("https://cdn.example.com/img.png"))
    assert mime == "image/png"
    assert data == _PNG_BYTES


def test_fetch_image_returns_jpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fetch(monkeypatch, response=httpx.Response(200, content=_JPEG_BYTES))
    mime, data = asyncio.run(fetch_image("https://cdn.example.com/img.jpg"))
    assert mime == "image/jpeg"
    assert data == _JPEG_BYTES


def test_fetch_image_returns_gif(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fetch(monkeypatch, response=httpx.Response(200, content=_GIF_BYTES))
    mime, data = asyncio.run(fetch_image("https://cdn.example.com/img.gif"))
    assert mime == "image/gif"


def test_fetch_image_returns_webp(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fetch(monkeypatch, response=httpx.Response(200, content=_WEBP_BYTES))
    mime, data = asyncio.run(fetch_image("https://cdn.example.com/img.webp"))
    assert mime == "image/webp"


def test_fetch_image_blocks_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    # 301 with a Location header — fetch_image must not follow it.
    redirect = httpx.Response(
        301,
        headers={"Location": "http://evil.internal/steal"},
        content=b"",
    )
    _patch_fetch(monkeypatch, response=redirect)
    with pytest.raises(SsrfBlockedError):
        asyncio.run(fetch_image("https://cdn.example.com/img.png"))


def test_fetch_image_rejects_svg(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fetch(monkeypatch, response=httpx.Response(200, content=_SVG_BYTES))
    with pytest.raises(SsrfBlockedError):
        asyncio.run(fetch_image("https://cdn.example.com/img.svg"))


def test_fetch_image_rejects_magic_byte_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    # Content-type says PNG but the bytes don't start with the PNG magic bytes.
    fake_response = httpx.Response(
        200,
        headers={"Content-Type": "image/png"},
        content=_UNKNOWN_BYTES,
    )
    _patch_fetch(monkeypatch, response=fake_response)
    with pytest.raises(SsrfBlockedError):
        asyncio.run(fetch_image("https://cdn.example.com/spoofed.png"))


def test_fetch_image_enforces_size_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    # Body just over the cap (1 byte over 128-byte limit).
    _patch_fetch(monkeypatch, response=httpx.Response(200, content=_PNG_BYTES[:8] + b"\x00" * 200))
    with pytest.raises(SsrfBlockedError):
        asyncio.run(fetch_image("https://cdn.example.com/big.png", max_bytes=128))


def test_fetch_image_blocks_non_http_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    # file:// and ftp:// must be blocked before any DNS resolution.
    monkeypatch.setattr(
        "personalai_core.security.ssrf.resolve_and_validate",
        lambda host: ["1.1.1.1"],
    )
    with pytest.raises(SsrfBlockedError):
        asyncio.run(fetch_image("file:///etc/passwd"))
    with pytest.raises(SsrfBlockedError):
        asyncio.run(fetch_image("ftp://cdn.example.com/img.png"))


def test_fetch_image_blocks_non_standard_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "personalai_core.security.ssrf.resolve_and_validate",
        lambda host: ["1.1.1.1"],
    )
    with pytest.raises(SsrfBlockedError):
        asyncio.run(fetch_image("https://cdn.example.com:8080/img.png"))


def test_fetch_image_uniform_error_message(monkeypatch: pytest.MonkeyPatch) -> None:
    # All violations surface the same uniform message regardless of which check triggered.
    _patch_fetch(monkeypatch, response=httpx.Response(200, content=_SVG_BYTES))
    with pytest.raises(SsrfBlockedError, match="image could not be fetched"):
        asyncio.run(fetch_image("https://cdn.example.com/img.png"))


class _CapturingTransport(httpx.AsyncBaseTransport):
    """Records the request the pinned transport hands to its inner transport."""

    def __init__(self) -> None:
        self.captured: httpx.Request | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.captured = request
        return httpx.Response(200, content=_PNG_BYTES)

    async def aclose(self) -> None:
        pass


def test_pinned_transport_dials_ip_and_pins_sni_to_hostname() -> None:
    """MF-1 guard (CISO #517): the pinned transport MUST dial the validated IP while binding TLS
    SNI + cert verification to the ORIGINAL hostname via the `sni_hostname` extension. This locks
    OUR side of the contract; the `httpx<0.29` cap locks httpcore's side (it consumes the
    extension). If either regresses, DNS-rebinding protection or cert verification silently breaks.
    """
    from personalai_core.security.ssrf import _PinnedIpTransport

    transport = _PinnedIpTransport(pinned_ip="93.184.216.34", hostname="example.com")
    capture = _CapturingTransport()
    transport._inner = capture  # type: ignore[assignment]

    request = httpx.Request("GET", "https://example.com/portrait.png")
    asyncio.run(transport.handle_async_request(request))

    assert capture.captured is not None
    # The socket dials the validated IP, not the DNS-live hostname.
    assert capture.captured.url.host == "93.184.216.34"
    # TLS SNI + certificate validation stay bound to the original hostname.
    assert capture.captured.extensions.get("sni_hostname") == b"example.com"
    # The Host header still names the original host (so the server routes correctly).
    assert capture.captured.headers["host"] == "example.com"
