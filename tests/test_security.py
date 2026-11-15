from datetime import UTC, datetime, timedelta

import jwt

from app.core.security import (
    ALGORITHM,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from tests.helpers import make_token


def test_password_hash_is_not_plain_and_verifies():
    hashed = hash_password("my-password")

    assert hashed != "my-password"
    assert verify_password("my-password", hashed)
    assert not verify_password("other-password", hashed)


def test_same_password_gets_different_hashes():
    assert hash_password("same") != hash_password("same")


def test_token_roundtrip():
    payload = decode_access_token(create_access_token(42))

    assert payload is not None
    assert payload["sub"] == "42"


def test_expired_token_is_rejected():
    token = make_token(exp=datetime.now(UTC) - timedelta(seconds=1))

    assert decode_access_token(token) is None


def test_token_signed_with_other_key_is_rejected():
    token = jwt.encode(
        {"sub": "1", "exp": datetime.now(UTC) + timedelta(minutes=5)},
        "another-secret-key-another-secret-key",
        algorithm=ALGORITHM,
    )

    assert decode_access_token(token) is None


def test_token_without_required_claims_is_rejected():
    assert decode_access_token(make_token(exp=None)) is None
    assert decode_access_token(make_token(sub=None)) is None


def test_garbage_token_is_rejected():
    assert decode_access_token("not-a-jwt") is None
