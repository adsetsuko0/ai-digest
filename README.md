# AI Digest

[![CI](https://github.com/adsetsuko0/ai-digest/actions/workflows/ci.yml/badge.svg)](https://github.com/adsetsuko0/ai-digest/actions/workflows/ci.yml)

Backend service for a personal news digest: users register, subscribe to RSS feeds with tags and (in progress) receive short LLM summaries of new articles.

> **Status: work in progress.** Accounts and feeds are finished and tested. Article collection and LLM summaries are planned, see the roadmap below.

## Tech stack

**Python 3.12 - FastAPI - Pydantic v2 - SQLAlchemy 2 (async) with asyncpg - Alembic - PostgreSQL 16 (pgvector image) - Redis - Docker Compose - pytest - respx - ruff - pre-commit - GitHub Actions**


## What works today

- **Auth:** registration and login with JWT access tokens. The token carries the user id, passwords are hashed with bcrypt, and login runs a dummy hash for unknown emails so response time does not reveal which accounts exist.
- **Rate limits:** 10 registrations per hour and 10 logins per minute per IP, stored in Redis under Docker Compose.
- **Feeds:** add, list (limit/offset pagination) and delete RSS feeds with tags. Feed URLs are validated to block private and internal addresses (first line of SSRF protection). Duplicate subscriptions are rejected by a database constraint, so there is no race between two requests.
- **Data isolation:** users cannot see or delete each other's feeds (covered by tests).
- **User settings:** digest time and timezone.
- **Health checks:** `/health` and `/health/ready` (checks the database).
- **Quality:** 50+ tests with an 80% coverage gate, ruff and pre-commit, GitHub Actions CI, container runs as a non-root user.

## Roadmap

Planned, not implemented yet:

- Celery + Celery Beat with RabbitMQ: scheduled feed collection with a safe fetcher (DNS-level SSRF check, size and time limits, ETag support).
- Article summaries through an OpenAI-compatible client, with a fake summarizer so the demo works without an API key.
- `GET /digest` with filters, pagination and a Redis cache.
- Optional semantic search with pgvector.
- Prometheus and Grafana metrics.
- Deployment to AWS EC2 with HTTPS.



## Quick start (Docker)

```bash
cp .env.example .env                  # then fill in SECRET_KEY and POSTGRES_PASSWORD
docker compose up -d --build
docker compose exec app alembic upgrade head
```

Open http://127.0.0.1:8000/docs for the interactive API docs.

Generate a value for each secret with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`docker-compose.override.yml` is applied automatically: it mounts the source code and runs the server with `--reload`. For a production-like run use `docker compose -f docker-compose.yml up -d --build`.

## Configuration

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | yes | JWT signing key, at least 32 characters |
| `POSTGRES_PASSWORD` | yes (Docker) | Password of the database user |
| `POSTGRES_USER` | no | Database user, default `digest_user` |
| `POSTGRES_DB` | no | Database name, default `digest_db` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | no | Token lifetime, default `30` |
| `RATE_LIMIT_ENABLED` | no | Set to `false` to turn rate limits off, default `true` |

Database and Redis URLs are assembled in `docker-compose.yml` from these values.

## API overview

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/auth/register` | no | Create an account |
| POST | `/auth/login` | no | Get an access token |
| GET | `/users/me` | yes | Current user |
| PATCH | `/users/me/settings` | yes | Digest time and timezone |
| POST | `/feeds` | yes | Add a feed with tags |
| GET | `/feeds?limit=&offset=` | yes | List your feeds |
| DELETE | `/feeds/{id}` | yes | Remove a feed |
| GET | `/health`, `/health/ready` | no | Liveness and readiness |

Example:

```bash
curl -s -X POST http://127.0.0.1:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"me@example.com","password":"correct-horse-1"}'

TOKEN=$(curl -s -X POST http://127.0.0.1:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"me@example.com","password":"correct-horse-1"}' \
  | python -c "import sys, json; print(json.load(sys.stdin)['access_token'])")

curl -s -X POST http://127.0.0.1:8000/feeds \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/rss","tags":["news"]}'

curl -s "http://127.0.0.1:8000/feeds?limit=10&offset=0" \
  -H "Authorization: Bearer $TOKEN"
```

## Running the tests

```bash
python -m venv .venv
source .venv/bin/activate             # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest --cov=app
```

The tests use an in-memory SQLite database, so neither Docker nor Postgres is needed.

## Project structure

```
app/
  api/        route handlers (auth, users, feeds)
  core/       settings, JWT and bcrypt, rate limiting, URL validation
  db/         engine, session, declarative base
  models/     SQLAlchemy models
  schemas/    Pydantic request and response models
migrations/   Alembic migrations
tests/        pytest suite
```

## Design decisions

- **JWT stores the user id, not the email**, so changing an email does not invalidate the identity in a token.
- **Uniqueness is enforced by the database** (unique constraints), because a "check then insert" in code can be beaten by two simultaneous requests.
- **Feed URLs are validated before they are stored.** Fetching them safely (resolving DNS and re-checking the address) belongs to the collection step on the roadmap.
- **The pgvector Postgres image is used from the start**, so semantic search does not require changing the database image later.

## License

MIT, see [LICENSE](LICENSE).