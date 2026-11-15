import pytest


@pytest.mark.asyncio
async def test_register(client):
    response = await client.post(
        "/auth/register",
        json={"email": "newuser@example.com", "password": "password123"},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "newuser@example.com"
    assert data["is_active"] is True
    assert "id" in data


@pytest.mark.asyncio
async def test_register_duplicate_email(client):
    await client.post(
        "/auth/register",
        json={"email": "newuser@example.com", "password": "testpassword123"},
    )
    response = await client.post(
        "/auth/register",
        json={"email": "newuser@example.com", "password": "testpassword456"},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_login(client):
    await client.post(
        "/auth/register",
        json={"email": "newuser@example.com", "password": "testpassword123"},
    )
    response = await client.post(
        "/auth/login",
        json={"email": "newuser@example.com", "password": "testpassword123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    await client.post(
        "/auth/register",
        json={"email": "newuser@example.com", "password": "testpassword123"},
    )
    response = await client.post(
        "/auth/login",
        json={"email": "newuser@example.com", "password": "wrongpassword"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_me(client):
    await client.post(
        "/auth/register",
        json={"email": "newuser@example.com", "password": "testpassword123"},
    )
    login = await client.post(
        "/auth/login",
        json={"email": "newuser@example.com", "password": "testpassword123"},
    )
    token = login.json()["access_token"]

    response = await client.get(
        "/users/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["email"] == "newuser@example.com"


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "password": "testpassword123"},
        {"email": "a@example.com", "password": "short"},
        {"email": "a@example.com", "password": "x" * 73},
        {"email": "a@example.com"},
        {},
    ],
    ids=["bad email", "short password", "too long password", "no password", "empty"],
)
@pytest.mark.asyncio
async def test_register_validation(client, payload):
    response = await client.post("/auth/register", json=payload)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_email_is_case_insensitive(client):
    await client.post(
        "/auth/register",
        json={"email": "Mixed@Example.com", "password": "testpassword123"},
    )

    response = await client.post(
        "/auth/login",
        json={"email": "MIXED@example.COM", "password": "testpassword123"},
    )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_login_unknown_user_gives_same_error_as_wrong_password(client):
    await client.post(
        "/auth/register",
        json={"email": "real@example.com", "password": "testpassword123"},
    )
    wrong_password = await client.post(
        "/auth/login", json={"email": "real@example.com", "password": "nope-nope-nope"}
    )
    unknown_user = await client.post(
        "/auth/login", json={"email": "ghost@example.com", "password": "nope-nope-nope"}
    )

    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()


@pytest.mark.asyncio
async def test_inactive_user_cannot_login_or_use_old_token(client, db_session):
    from sqlalchemy import update

    from app.models.user import User

    creds = {"email": "gone@example.com", "password": "testpassword123"}
    await client.post("/auth/register", json=creds)
    token = (await client.post("/auth/login", json=creds)).json()["access_token"]
    await db_session.execute(update(User).values(is_active=False))
    await db_session.commit()

    login = await client.post("/auth/login", json=creds)
    me = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})

    assert login.status_code == 401
    assert me.status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer garbage"},
        {"Authorization": "Basic abc"},
    ],
    ids=["no header", "garbage token", "wrong scheme"],
)
@pytest.mark.asyncio
async def test_protected_endpoint_rejects_bad_credentials(client, headers):
    response = await client.get("/users/me", headers=headers)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_password_is_never_returned(client):
    response = await client.post(
        "/auth/register",
        json={"email": "safe@example.com", "password": "testpassword123"},
    )

    assert "password" not in response.text


@pytest.mark.asyncio
async def test_password_longer_than_72_bytes_is_rejected(client):
    # 40 русских букв это всего 40 символов, но 80 байт: bcrypt принимает не больше 72
    response = await client.post(
        "/auth/register",
        json={"email": "long@example.com", "password": "я" * 40},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_token_with_non_numeric_subject_is_rejected(client):
    from tests.helpers import make_token

    token = make_token(sub="not-a-number")

    response = await client.get(
        "/users/me", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 401
