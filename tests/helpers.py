from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import settings
from app.core.security import ALGORITHM


def make_token(**overrides):
    now = datetime.now(UTC)
    payload = {"sub": "1", "iat": now, "exp": now + timedelta(minutes=5)}
    payload.update(overrides)
    payload = {k: v for k, v in payload.items() if v is not None}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)
