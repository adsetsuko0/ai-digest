import bcrypt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.database import get_db
from app.main import app

# База живёт только в памяти: на диске ничего не остаётся, тесты быстрые.
# StaticPool нужен, чтобы все соединения видели одну и ту же in-memory базу.
engine = create_async_engine(
    "sqlite+aiosqlite://",
    poolclass=StaticPool,
    connect_args={"check_same_thread": False},
)
TestSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def override_get_db():
    async with TestSessionLocal() as session:
        yield session


@pytest.fixture(scope="session", autouse=True)
def fast_bcrypt():
    """В тестах хеширование паролей дешёвое (4 раунда вместо 12): тесты идут быстрее."""
    original = bcrypt.gensalt
    bcrypt.gensalt = lambda rounds=4, prefix=b"2b": original(
        rounds=rounds, prefix=prefix
    )
    yield
    bcrypt.gensalt = original


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def db_session():
    """Сессия для проверок прямо в базе (что именно лежит в таблицах)."""
    async with TestSessionLocal() as session:
        yield session


async def register_and_login(client, email, password="testpassword123"):
    """Регистрирует пользователя и возвращает заголовки с его токеном."""
    await client.post("/auth/register", json={"email": email, "password": password})
    login = await client.post(
        "/auth/login", json={"email": email, "password": password}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest_asyncio.fixture
async def alice(client):
    return await register_and_login(client, "alice@example.com")


@pytest_asyncio.fixture
async def bob(client):
    return await register_and_login(client, "bob@example.com")
