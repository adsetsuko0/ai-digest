import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.rate_limit import limiter
from app.db.database import get_db
from app.models.user import User
from app.schemas.search import SearchResults
from app.services.embedder import get_embedder
from app.services.search import search_articles
from app.services.summarizer import LLMError

router = APIRouter(tags=["search"])
logger = structlog.get_logger(__name__)


@router.get("/search", response_model=SearchResults)
@limiter.limit("30/minute")  # every query may cost an embedding call
async def search(
    request: Request,
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = q.strip()
    if not query:
        raise HTTPException(status_code=422, detail="Query must not be blank")

    embedder = get_embedder()
    try:
        # the embedder is synchronous (it may call an HTTP API): keep it off the event loop
        vector = await run_in_threadpool(embedder.embed, query)
    except LLMError as exc:
        logger.warning("search_embedding_failed", error=str(exc)[:200])
        raise HTTPException(
            status_code=503, detail="Search is temporarily unavailable"
        ) from None

    items = await search_articles(
        db, user_id=current_user.id, vector=vector, limit=limit
    )
    return SearchResults(items=items)
