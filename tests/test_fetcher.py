import gzip
import ipaddress
import socket

import httpx
import pytest
import respx

from app.services import fetcher
from app.services.fetcher import (
    ClientHTTPError,
    ResponseTooLarge,
    TooManyRedirects,
    UnsafeURLError,
    UpstreamError,
    fetch_feed_content,
    resolve_host_ips,
)

PUBLIC_IP = ipaddress.ip_address("93.184.216.34")
FEED_URL = "https://example.com/rss"
LAST_MODIFIED = "Wed, 01 Jan 2026 00:00:00 GMT"


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    """By default every host resolves to a public address (no real DNS in tests)."""
    monkeypatch.setattr(fetcher, "resolve_host_ips", lambda host: [PUBLIC_IP])


@pytest.fixture
def router():
    with respx.mock(assert_all_called=False) as mock:
        yield mock


def test_fetch_returns_body_and_validators(router):
    router.get(FEED_URL).mock(
        return_value=httpx.Response(
            200,
            content=b"<rss/>",
            headers={"ETag": '"abc"', "Last-Modified": LAST_MODIFIED},
        )
    )

    result = fetch_feed_content(FEED_URL)

    assert result.not_modified is False
    assert result.content == b"<rss/>"
    assert result.etag == '"abc"'
    assert result.last_modified == LAST_MODIFIED


def test_conditional_headers_are_sent_and_304_is_reported(router):
    route = router.get(FEED_URL).mock(return_value=httpx.Response(304))

    result = fetch_feed_content(FEED_URL, etag='"abc"', last_modified=LAST_MODIFIED)

    request = route.calls.last.request
    assert request.headers["If-None-Match"] == '"abc"'
    assert request.headers["If-Modified-Since"] == LAST_MODIFIED
    assert result.not_modified is True
    assert result.content == b""
    assert result.etag == '"abc"'


def test_no_conditional_headers_without_validators(router):
    route = router.get(FEED_URL).mock(return_value=httpx.Response(200, content=b"x"))

    fetch_feed_content(FEED_URL)

    request = route.calls.last.request
    assert "If-None-Match" not in request.headers
    assert "If-Modified-Since" not in request.headers


def test_user_agent_identifies_the_bot(router):
    route = router.get(FEED_URL).mock(return_value=httpx.Response(200, content=b"x"))

    fetch_feed_content(FEED_URL)

    assert route.calls.last.request.headers["User-Agent"].startswith("AIDigestBot/")


def test_redirect_is_followed(router):
    router.get("https://example.com/old").mock(
        return_value=httpx.Response(301, headers={"Location": "/new"})
    )
    router.get("https://example.com/new").mock(
        return_value=httpx.Response(200, content=b"moved")
    )

    assert fetch_feed_content("https://example.com/old").content == b"moved"


def test_redirect_loop_stops_after_limit(router):
    route = router.get("https://example.com/loop").mock(
        return_value=httpx.Response(302, headers={"Location": "/loop"})
    )

    with pytest.raises(TooManyRedirects):
        fetch_feed_content("https://example.com/loop")

    assert route.call_count == fetcher.MAX_REDIRECTS + 1


def test_redirect_without_location_is_rejected(router):
    router.get(FEED_URL).mock(return_value=httpx.Response(302))

    with pytest.raises(ClientHTTPError):
        fetch_feed_content(FEED_URL)


def test_redirect_to_private_ip_is_blocked_before_any_request(router):
    router.get(FEED_URL).mock(
        return_value=httpx.Response(302, headers={"Location": "http://127.0.0.1/admin"})
    )
    internal = router.get("http://127.0.0.1/admin").mock(
        return_value=httpx.Response(200, content=b"secret")
    )

    with pytest.raises(UnsafeURLError):
        fetch_feed_content(FEED_URL)

    assert internal.called is False


def test_redirect_to_host_resolving_to_private_address_is_blocked(router, monkeypatch):
    def resolver(host):
        if host == "internal.example.org":
            return [ipaddress.ip_address("10.0.0.5")]
        return [PUBLIC_IP]

    monkeypatch.setattr(fetcher, "resolve_host_ips", resolver)
    router.get(FEED_URL).mock(
        return_value=httpx.Response(
            302, headers={"Location": "https://internal.example.org/rss"}
        )
    )
    target = router.get("https://internal.example.org/rss").mock(
        return_value=httpx.Response(200, content=b"x")
    )

    with pytest.raises(UnsafeURLError):
        fetch_feed_content(FEED_URL)

    assert target.called is False


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.5",
        "192.168.1.10",
        "169.254.169.254",
        "::1",
        "fd00::1",
        "::ffff:127.0.0.1",
    ],
)
def test_host_resolving_to_non_public_address_is_blocked(router, monkeypatch, address):
    monkeypatch.setattr(
        fetcher, "resolve_host_ips", lambda host: [ipaddress.ip_address(address)]
    )
    route = router.get("https://localtest.me/rss").mock(
        return_value=httpx.Response(200, content=b"x")
    )

    with pytest.raises(UnsafeURLError):
        fetch_feed_content("https://localtest.me/rss")

    assert route.called is False


def test_one_private_address_among_public_ones_blocks_the_host(router, monkeypatch):
    monkeypatch.setattr(
        fetcher,
        "resolve_host_ips",
        lambda host: [PUBLIC_IP, ipaddress.ip_address("10.0.0.5")],
    )
    route = router.get(FEED_URL).mock(return_value=httpx.Response(200, content=b"x"))

    with pytest.raises(UnsafeURLError):
        fetch_feed_content(FEED_URL)

    assert route.called is False


def test_non_http_scheme_is_blocked():
    with pytest.raises(UnsafeURLError):
        fetch_feed_content("ftp://example.com/rss")


def test_response_too_large_by_content_length(router):
    router.get(FEED_URL).mock(
        return_value=httpx.Response(
            200, content=b"a" * (fetcher.MAX_RESPONSE_BYTES + 1)
        )
    )

    with pytest.raises(ResponseTooLarge):
        fetch_feed_content(FEED_URL)


def test_streamed_response_without_content_length_is_limited(router):
    def chunks():
        for _ in range(3):
            yield b"a" * (1024 * 1024)

    router.get(FEED_URL).mock(return_value=httpx.Response(200, content=chunks()))

    with pytest.raises(ResponseTooLarge):
        fetch_feed_content(FEED_URL)


def test_gzip_bomb_is_limited_by_decoded_size(router):
    bomb = gzip.compress(b"0" * (fetcher.MAX_RESPONSE_BYTES + 1024))
    assert len(bomb) < 10_000
    router.get(FEED_URL).mock(
        return_value=httpx.Response(
            200, content=bomb, headers={"Content-Encoding": "gzip"}
        )
    )

    with pytest.raises(ResponseTooLarge):
        fetch_feed_content(FEED_URL)


def test_slow_download_hits_total_deadline(router, monkeypatch):
    monkeypatch.setattr(fetcher, "MAX_TOTAL_SECONDS", -1.0)
    router.get(FEED_URL).mock(return_value=httpx.Response(200, content=b"data"))

    with pytest.raises(UpstreamError):
        fetch_feed_content(FEED_URL)


@pytest.mark.parametrize("status", [500, 502, 503, 408, 425, 429])
def test_temporary_http_errors(router, status):
    router.get(FEED_URL).mock(return_value=httpx.Response(status))

    with pytest.raises(UpstreamError):
        fetch_feed_content(FEED_URL)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 410])
def test_permanent_http_errors(router, status):
    router.get(FEED_URL).mock(return_value=httpx.Response(status))

    with pytest.raises(ClientHTTPError):
        fetch_feed_content(FEED_URL)


@pytest.mark.parametrize(
    "error",
    [
        httpx.ReadTimeout("slow"),
        httpx.ConnectError("refused"),
        httpx.RemoteProtocolError("broken"),
    ],
)
def test_network_errors_are_temporary(router, error):
    router.get(FEED_URL).mock(side_effect=error)

    with pytest.raises(UpstreamError):
        fetch_feed_content(FEED_URL)


def test_only_upstream_errors_are_retryable():
    assert UpstreamError.retryable is True
    for error in (UnsafeURLError, ResponseTooLarge, TooManyRedirects, ClientHTTPError):
        assert error.retryable is False


def test_injected_client_is_not_closed(router):
    router.get(FEED_URL).mock(return_value=httpx.Response(200, content=b"x"))

    with httpx.Client() as client:
        fetch_feed_content(FEED_URL, client=client)
        assert client.is_closed is False


def test_resolve_host_ips_removes_duplicates_and_ipv6_zone(monkeypatch):
    infos = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("fe80::1%eth0", 0, 0, 2)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
    ]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: infos)

    assert resolve_host_ips("example.com") == [
        ipaddress.ip_address("93.184.216.34"),
        ipaddress.ip_address("fe80::1"),
    ]


def test_dns_failure_is_a_temporary_error(monkeypatch):
    def fail(*args, **kwargs):
        raise socket.gaierror(-2, "Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", fail)

    with pytest.raises(UpstreamError):
        resolve_host_ips("no-such-host.example")
