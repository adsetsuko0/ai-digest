from sqlalchemy.exc import SQLAlchemyError

from app.db.database import get_db
from app.main import app


async def test_health(client):
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ready_when_database_is_available(client):
    response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


async def test_ready_returns_503_when_database_is_down(client):
    class BrokenSession:
        async def execute(self, *args, **kwargs):
            raise SQLAlchemyError("db is down")

    async def broken_db():
        yield BrokenSession()

    app.dependency_overrides[get_db] = broken_db

    response = await client.get("/health/ready")

    assert response.status_code == 503
