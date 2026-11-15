import ipaddress
from urllib.parse import urlsplit, urlunsplit

BLOCKED_SUFFIXES = (".local", ".localhost", ".internal", ".lan")


def is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return not ip.is_global or ip.is_multicast


def validate_feed_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"}:
        raise ValueError("Only http and https URLs are allowed")
    # "localhost." и "example.com." это те же самые имена, только с точкой на конце
    host = (parts.hostname or "").rstrip(".")
    if not host:
        raise ValueError("URL must contain a host")
    if parts.username or parts.password:
        raise ValueError("Credentials in URL are not allowed")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        last_label = host.rsplit(".", 1)[-1]
        if (
            "." not in host
            or host.endswith(BLOCKED_SUFFIXES)
            or last_label.isdigit()  # сокращённые и восьмеричные IPv4: 127.1, 0177.0.0.1
            or last_label.startswith("0x")  # шестнадцатеричные: 0x7f.1
        ):
            raise ValueError("Host is not allowed") from None
        netloc = host.lower()
    else:
        if is_blocked_ip(ip):
            raise ValueError("Host is not allowed")
        netloc = f"[{host}]" if ":" in host else host
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))
