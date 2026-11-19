from fastapi import Depends, FastAPI, HTTPException
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import router as auth_router
from app.api.digest import router as digest_router
from app.api.feeds import router as feeds_router
from app.api.search import router as search_router
from app.api.users import router as users_router
from app.core.rate_limit import limiter
from app.db.database import get_db

app = FastAPI(
    title="AI Digest",
    description="Personal news digest based on RSS and LLM summaries",
    version="0.1.0",
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(feeds_router)
app.include_router(digest_router)
app.include_router(search_router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/ready")
async def ready(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="Database unavailable") from None
    return {"status": "ready"}
