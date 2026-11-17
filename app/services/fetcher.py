import ipaddress
import socket
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

from app.core.url_safety import is_blocked_ip, validate_feed_url

USER_AGENT = "AIDigestBot/1.0 (+https://github.com/adsetsuko0/ai-digest)"
ACCEPT = (
    "application/rss+xml, application/atom+xml, "
    "application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5"
)
TIMEOUT = httpx.Timeout(10.0, connect=5.0)
MAX_REDIRECTS = 3
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_SECONDS = 30.0

REDIRECT_STATUSES = {301, 302, 303, 307, 308}
RETRYABLE_CLIENT_STATUSES = {408, 425, 429}

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class FetchError(Exception):
    """Base class for errors while downloading a feed."""

    retryable = False


class UnsafeURLError(FetchError):
    """The URL or the address it resolves to is not allowed (SSRF protection)."""


class ResponseTooLarge(FetchError):
    """The response body is bigger than MAX_RESPONSE_BYTES."""


class TooManyRedirects(FetchError):
    """The redirect chain is longer than MAX_REDIRECTS."""


class ClientHTTPError(FetchError):
    """Permanent HTTP error (4xx): retrying will not help."""


class UpstreamError(FetchError):
    """Temporary problem: 5xx, 429, timeouts, DNS or network errors."""

    retryable = True


@dataclass(frozen=True)
class FetchResult:
    not_modified: bool
    content: bytes
    etag: str | None
    last_modified: str | None


def resolve_host_ips(host: str) -> list[IPAddress]:
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UpstreamError(f"DNS lookup failed for {host}") from exc
    # drop duplicates and the IPv6 zone id ("fe80::1%eth0")
    addresses = dict.fromkeys(str(info[4][0]).split("%")[0] for info in infos)
    return [ipaddress.ip_address(address) for address in addresses]


def _check_url(url: str) -> str:
    """Validate the URL and make sure every address it resolves to is public."""
    try:
        safe_url = validate_feed_url(url)
    except ValueError as exc:
        raise UnsafeURLError(str(exc)) from exc
    host = urlsplit(safe_url).hostname
    if not host:
        raise UnsafeURLError("URL must contain a host")
    for ip in resolve_host_ips(host):
        if is_blocked_ip(ip):
            raise UnsafeURLError("Host resolves to a non-public address")
    return safe_url


def _read_limited(response: httpx.Response) -> bytes:
    declared = response.headers.get("Content-Length")
    if declared and declared.isdigit() and int(declared) > MAX_RESPONSE_BYTES:
        raise ResponseTooLarge(f"Response exceeds {MAX_RESPONSE_BYTES} bytes")
    deadline = time.monotonic() + MAX_TOTAL_SECONDS
    chunks: list[bytes] = []
    total = 0
    # iter_bytes() yields decoded data, so the limit also stops gzip bombs
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            raise ResponseTooLarge(f"Response exceeds {MAX_RESPONSE_BYTES} bytes")
        if time.monotonic() > deadline:
            raise UpstreamError("Response took too long")
        chunks.append(chunk)
    return b"".join(chunks)


def _http_error(status: int) -> FetchError:
    if status >= 500 or status in RETRYABLE_CLIENT_STATUSES:
        return UpstreamError(f"HTTP {status}")
    return ClientHTTPError(f"HTTP {status}")


def _download(
    client: httpx.Client, url: str, etag: str | None, last_modified: str | None
) -> FetchResult:
    headers = {"User-Agent": USER_AGENT, "Accept": ACCEPT}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    current = _check_url(url)
    for attempt in range(MAX_REDIRECTS + 1):
        try:
            with client.stream(
                "GET",
                current,
                headers=headers,
                timeout=TIMEOUT,
                follow_redirects=False,
            ) as response:
                status = response.status_code
                if status == 304:
                    return FetchResult(True, b"", etag, last_modified)
                if 200 <= status < 300:
                    return FetchResult(
                        False,
                        _read_limited(response),
                        response.headers.get("ETag"),
                        response.headers.get("Last-Modified"),
                    )
                if status not in REDIRECT_STATUSES:
                    raise _http_error(status)
                location = response.headers.get("Location")
                if not location:
                    raise ClientHTTPError(f"HTTP {status} without Location header")
        except httpx.DecodingError as exc:
            raise ClientHTTPError("Response body could not be decoded") from exc
        except httpx.HTTPError as exc:
            raise UpstreamError(f"Request failed: {type(exc).__name__}") from exc

        if attempt == MAX_REDIRECTS:
            raise TooManyRedirects(f"More than {MAX_REDIRECTS} redirects")
        # every redirect target goes through the same checks as the first URL
        current = _check_url(urljoin(current, location))
    raise TooManyRedirects(f"More than {MAX_REDIRECTS} redirects")


def fetch_feed_content(
    url: str,
    etag: str | None = None,
    last_modified: str | None = None,
    *,
    client: httpx.Client | None = None,
) -> FetchResult:
    """Download a feed safely.

    Known limitation: the host is resolved twice, once for our check and once
    when httpx connects, so a DNS server that changes its answer between the two
    (DNS rebinding) could still bypass the check. A firewall that blocks
    private ranges for outgoing traffic closes this gap.
    """
    own_client = client is None
    active_client = httpx.Client() if client is None else client
    try:
        return _download(active_client, url, etag, last_modified)
    finally:
        if own_client:
            active_client.close()
