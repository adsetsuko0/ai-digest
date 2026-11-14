from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import limiter
from app.core.security import (
    DUMMY_HASH,
    create_access_token,
    hash_password,
    verify_password,
)
from app.db.database import get_db
from app.models.user import User
from app.schemas.user import Token, UserLogin, UserRegister, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=201)
@limiter.limit("10/hour")
async def register(
    request: Request, data: UserRegister, db: AsyncSession = Depends(get_db)
):
    user = User(email=data.email, hashed_password=hash_password(data.password))
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Such email already exists"
        ) from None
    await db.refresh(user)
    return user


@router.post("/login", response_model=Token)
@limiter.limit("10/minute")
async def login(request: Request, data: UserLogin, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    # always run bcrypt so response time does not reveal whether the email exists
    password_ok = verify_password(
        data.password, user.hashed_password if user else DUMMY_HASH
    )
    if user is None or not password_ok or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    return {"access_token": create_access_token(user.id), "token_type": "bearer"}