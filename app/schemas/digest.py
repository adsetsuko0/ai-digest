import datetime

from pydantic import BaseModel, Field


class DigestFeed(BaseModel):
    id: int
    title: str | None = None


class DigestItem(BaseModel):
    id: int
    title: str | None = None
    url: str
    summary: str
    feed: DigestFeed
    published_at: datetime.datetime = Field(
        description="Publication date; if the feed gives none, the time we collected the article"
    )
    tags: list[str] = Field(default_factory=list, description="Your tags of this feed")


class DigestPage(BaseModel):
    items: list[DigestItem]
    next_cursor: str | None = Field(
        default=None, description="Pass as ?cursor= to get the next page"
    )
