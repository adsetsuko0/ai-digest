from pydantic import BaseModel


class FeedCreate(BaseModel):
    url: str
    tags: list[str] = []


class FeedResponse(BaseModel):
    id: int
    url: str
    title: str | None = None
    is_active: bool
    tags: list[str] = []

    model_config = {"from_attributes": True}
