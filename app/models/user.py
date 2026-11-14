import datetime

from sqlalchemy import Boolean, Column, Integer, String, Time

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    digest_time = Column(Time, default=datetime.time(9, 0))
    timezone = Column(String, default="UTC")
    is_active = Column(Boolean, default=True)
