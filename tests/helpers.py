from datetime import UTC, datetime, timedelta

import jwt
from prometheus_client import REGISTRY

from app.core.config import settings
from app.core.security import ALGORITHM


def make_token(**overrides):
    now = datetime.now(UTC)
    payload = {"sub": "1", "iat": now, "exp": now + timedelta(minutes=5)}
    payload.update(overrides)
    payload = {k: v for k, v in payload.items() if v is not None}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def metric_value(name: str, **labels: str) -> float:
    """Current value of a Prometheus sample (0 when the series does not exist yet)."""
    return REGISTRY.get_sample_value(name, labels or None) or 0.0
