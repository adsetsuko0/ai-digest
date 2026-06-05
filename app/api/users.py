from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.database import get_db
from app.models.user import User
from app.schemas.user import UserResponse, UserSettingsUpdate
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user

@router.patch('/me/settings', response_model=UserResponse)
async def update_setttings(
    data: UserSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if data.digest_time is not None:
        current_user.digest_time = data.digest_time
    if data.timezone is not None:
        current_user.timezone = data.timezone

    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)
    return current_user