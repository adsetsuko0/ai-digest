from pydantic import BaseModel
from typing import List, Optional


class FeedCreate(BaseModel):
    url: str
    tags: List[str] = []


class FeedResponse(BaseModel):
    id: int
    url: str
    title: Optional[str] = None
    is_active: bool
    tags: List[str] = []

    model_config = {"from_attributes": True}