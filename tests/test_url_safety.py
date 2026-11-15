import pytest

from app.core.url_safety import validate_feed_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://Example.com/rss", "https://example.com/rss"),
        ("https://example.com", "https://example.com/"),
        ("https://example.com:8443/feed?x=1", "https://example.com:8443/feed?x=1"),
        ("  https://example.com/rss#top  ", "https://example.com/rss"),
        ("http://example.com./x", "http://example.com/x"),
        ("http://[2606:4700:4700::1111]/rss", "http://[2606:4700:4700::1111]/rss"),
    ],
)
def test_valid_urls_are_normalized(url, expected):
    assert validate_feed_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/rss",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "http:///x",
        "http://user:pass@example.com/",
        "http://example.com:abc/",
    ],
)
def test_bad_scheme_or_shape_is_rejected(url):
    with pytest.raises(ValueError):
        validate_feed_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/x",
        "http://localhost./x",
        "http://db/x",
        "http://foo.local/x",
        "http://foo.local./x",
        "http://app.internal/x",
        "http://printer.lan/x",
        "http://127.0.0.1/x",
        "http://127.1/x",
        "http://0x7f.1/x",
        "http://0x7f000001/x",
        "http://0177.0.0.1/x",
        "http://2130706433/x",
        "http://10.0.0.1/x",
        "http://172.16.0.1/x",
        "http://192.168.1.1/x",
        "http://169.254.169.254/latest/meta-data/",
        "http://0.0.0.0/x",
        "http://[::1]/x",
        "http://[::ffff:127.0.0.1]/x",
        "http://[fd00::1]/x",
        "http://224.0.0.1/x",
    ],
)
def test_private_and_local_hosts_are_rejected(url):
    with pytest.raises(ValueError, match="Host is not allowed"):
        validate_feed_url(url)
