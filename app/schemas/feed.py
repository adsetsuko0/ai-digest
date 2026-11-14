from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator

from app.core.url_safety import validate_feed_url

Tag = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, to_lower=True, min_length=1, max_length=32
    ),
]


class FeedCreate(BaseModel):
    url: str = Field(max_length=2048)
    tags: list[Tag] = Field(default_factory=list, max_length=10)

    @field_validator("url")
    @classmethod
    def url_is_safe(cls, value: str) -> str:
        return validate_feed_url(value)

    @field_validator("tags")
    @classmethod
    def unique_tags(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class FeedResponse(BaseModel):
    id: int
    url: str
    title: str | None = None
    is_active: bool
    tags: list[str] = []

    model_config = {"from_attributes": True}
