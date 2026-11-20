import datetime

from sqlalchemy import Boolean, String, Time
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String)
    digest_time: Mapped[datetime.time | None] = mapped_column(
        Time, default=datetime.time(9, 0)
    )
    timezone: Mapped[str | None] = mapped_column(String, default="UTC")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
