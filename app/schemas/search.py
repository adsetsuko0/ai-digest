from pydantic import BaseModel, Field

from app.schemas.digest import DigestItem


class SearchItem(DigestItem):
    score: float = Field(description="Cosine similarity, 1 is the closest")


class SearchResults(BaseModel):
    items: list[SearchItem]
