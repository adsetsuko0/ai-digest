from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.database import get_db
from app.models.user import User

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise credentials_exception
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise credentials_exception
    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError):
        raise credentials_exception from None
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise credentials_exception
    return user
