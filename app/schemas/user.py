from pydantic import BaseModel, EmailStr
from typing import Optional
import datetime

class UserRegister(BaseModel):
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: int
    email: str
    is_active: bool
    digest_time: Optional[datetime.time] = None
    timezone: Optional[str] = None

    model_config = {'from_attributes': True}

class Token(BaseModel):
    access_token: str
    token_type: str


class UserSettingsUpdate(BaseModel):
    digest_time: Optional[datetime.time] = None
    timezone: Optional[str] = None