import dataclasses
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.article import Article
from app.models.feed import Feed
from app.services.parser import ParsedEntry


def normalize_url(url: str) -> str:
    """Drop utm_* parameters and the #fragment, lowercase scheme and host."""
    parts = urlsplit(url.strip())
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")
        ]
    )
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path, query, "")
    )


def _dedupe_batch(entries: list[ParsedEntry]) -> list[ParsedEntry]:
    """Remove repeats inside one batch (by normalized URL and by content hash)."""
    seen_urls: set[str] = set()
    seen_hashes: set[str] = set()
    unique: list[ParsedEntry] = []
    for entry in entries:
        entry = dataclasses.replace(entry, url=normalize_url(entry.url))
        if entry.url in seen_urls or entry.content_hash in seen_hashes:
            continue
        seen_urls.add(entry.url)
        seen_hashes.add(entry.content_hash)
        unique.append(entry)
    return unique


def _drop_existing(
    session: Session, feed: Feed, entries: list[ParsedEntry]
) -> list[ParsedEntry]:
    """Remove entries that are already in the database."""
    urls = [e.url for e in entries]
    hashes = [e.content_hash for e in entries]
    known_urls = set(session.scalars(select(Article.url).where(Article.url.in_(urls))))
    known_hashes = set(
        session.scalars(
            select(Article.content_hash).where(
                Article.feed_id == feed.id,
                Article.content_hash.in_(hashes),
            )
        )
    )
    return [
        e
        for e in entries
        if e.url not in known_urls and e.content_hash not in known_hashes
    ]


def _to_article(feed: Feed, entry: ParsedEntry) -> Article:
    return Article(
        feed_id=feed.id,
        url=entry.url,
        title=entry.title,
        content=entry.content,
        published_at=entry.published_at,
        content_hash=entry.content_hash,
    )


def store_entries(session: Session, feed: Feed, entries: list[ParsedEntry]) -> int:
    """Save new articles and return how many were inserted.

    Idempotent: running it twice with the same entries inserts nothing the
    second time. Does not commit, the caller owns the transaction.
    """
    candidates = _drop_existing(session, feed, _dedupe_batch(entries))
    if not candidates:
        return 0

    # fast path: the whole batch in one savepoint
    try:
        with session.begin_nested():
            session.add_all(_to_article(feed, e) for e in candidates)
            session.flush()
        return len(candidates)
    except IntegrityError:
        pass  # another worker inserted one of the URLs between our check and insert

    # slow path: one by one, so a single duplicate does not drop the whole batch
    inserted = 0
    for entry in candidates:
        try:
            with session.begin_nested():
                session.add(_to_article(feed, entry))
                session.flush()
            inserted += 1
        except IntegrityError:
            continue
    return inserted
