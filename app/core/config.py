from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str
    DATABASE_SYNC_URL: str = ""
    REDIS_URL: str = "redis://localhost:6379/0"
    SECRET_KEY: str = Field(min_length=32)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_STORAGE_URI: str = "memory://"
    CELERY_BROKER_URL: str = "amqp://guest:guest@localhost:5672//"
    FETCH_INTERVAL_SECONDS: int = Field(default=1800, ge=60)
    FEED_MAX_CONSECUTIVE_ERRORS: int = Field(default=5, ge=1)
    LOG_JSON: bool = False
    LLM_PROVIDER: Literal["fake", "openai"] = "fake"
    LLM_BASE_URL: str = ""
    LLM_API_KEY: SecretStr = SecretStr("")
    LLM_MODEL: str = ""
    LLM_DAILY_TOKEN_BUDGET: int = Field(default=200_000, ge=0)
    EMBEDDING_PROVIDER: Literal["fake", "openai"] = "fake"
    EMBEDDING_MODEL: str = ""
    EMBEDDING_DIM: int = Field(default=384, ge=1, le=2000)


settings = Settings()
