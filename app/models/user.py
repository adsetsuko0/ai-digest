from sqlalchemy import Column, Integer, String, Boolean, Time
from sqlalchemy.dialects.postgresql import ARRAY
from app.db.database import Base
import datetime

class User(Base):
    __tablename__= 'users'

    id=Column(Integer, primary_key=True, index=True)
    email=Column(String, unique=True, index=True, nullable=False)
    hashed_password=Column(String, nullable=False)
    digest_time=Column(Time, default=datetime.time(9, 0))
    timezone=Column(String, default='UTC')
    is_active=Column(Boolean, default=True)

    