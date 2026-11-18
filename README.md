# AI Digest

[![CI](https://github.com/adsetsuko0/ai-digest/actions/workflows/ci.yml/badge.svg)](https://github.com/adsetsuko0/ai-digest/actions/workflows/ci.yml)

Backend service for a personal news digest: users register, subscribe to RSS feeds with tags, the service collects new articles in the background and (in progress) will send short LLM summaries of them.

> **Status: work in progress.** Accounts, feeds and background article collection are finished and tested. Summaries and the digest endpoint are planned, see the roadmap below. Collected articles are stored in the database, but there is no API to read them yet.

## Tech stack

**Python 3.12 - FastAPI - Pydantic v2 - SQLAlchemy 2 (async API, sync worker) - Alembic - PostgreSQL 16 (pgvector image) - Redis - Celery + RabbitMQ - httpx - feedparser - structlog - Docker Compose - pytest - respx - ruff - pre-commit - GitHub Actions**

## What works today

- **Auth:** registration and login with JWT access tokens. The token carries the user id, passwords are hashed with bcrypt, and login runs a dummy hash for unknown emails so response time does not reveal which accounts exist.
- **Rate limits:** 10 registrations per hour and 10 logins per minute per IP, stored in Redis under Docker Compose.
- **Feeds:** add, list (limit/offset pagination) and delete RSS feeds with tags. Feed URLs are validated to block private and internal addresses. Duplicate subscriptions are rejected by a database constraint, so there is no race between two requests.
- **Article collection:** Celery Beat runs every 30 minutes. Each active feed that has at least one subscriber gets its own task with a random start delay of up to 60 seconds, so sources are not hit all at once. A task downloads the feed safely, parses RSS and Atom, removes duplicates (by normalized URL and by content hash) and stores new articles. Repeating a task never creates duplicates.
- **Safe feed fetcher:** the host is resolved and every address is checked on each download, redirects are followed manually and re-checked, the response is streamed with a 2 MB limit (which also stops compression bombs), and conditional requests (`ETag`, `Last-Modified`) save traffic.
- **Error handling:** temporary errors (5xx, 429, timeouts, DNS failures) are retried with growing delays. Permanent errors (404, content that is not a feed, blocked addresses, oversized responses) are counted, the reason is saved in `last_error`, and a feed that fails 5 times in a row is disabled automatically.
- **Structured logs:** every collection task logs `feed_id`, `url`, `articles_new`, `duration_ms` and `status`. JSON under Docker Compose, readable output locally.
- **Data isolation:** users cannot see or delete each other's feeds (covered by tests).
- **User settings:** digest time and timezone.
- **Health checks:** `/health` and `/health/ready` (checks the database).
- **Quality:** 200+ tests with an 80% coverage gate (about 97% today), ruff and pre-commit, GitHub Actions CI, containers run as a non-root user.

## Roadmap

Planned, not implemented yet:

- Article summaries through an OpenAI-compatible client, with a fake summarizer so the demo works without an API key.
- `GET /digest` with filters, pagination and a Redis cache.
- An endpoint to re-enable a feed that was disabled automatically.
- Optional semantic search with pgvector.
- Prometheus and Grafana metrics.
- Deployment to AWS EC2 with HTTPS.

## Quick start (Docker)

```bash
cp .env.example .env                  # then fill in SECRET_KEY, POSTGRES_PASSWORD and RABBITMQ_PASSWORD
docker compose up -d --build
docker compose exec app alembic upgrade head
```

Open http://127.0.0.1:8000/docs for the interactive API docs.

Generate a value for each secret with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`docker-compose.override.yml` is applied automatically: it mounts the source code and runs the server with `--reload`. For a production-like run use `docker compose -f docker-compose.yml up -d --build`.

### Collecting articles

Beat starts collection every 30 minutes on its own. To run it by hand:

```bash
docker compose exec worker celery -A app.worker.celery_app call app.worker.tasks.fetch_all_feeds
docker compose logs -f worker
```

Tasks start with a random delay of up to 60 seconds, so wait a minute before looking for results. Check the state of your feeds and the number of stored articles with:

```bash
docker compose exec db psql -U digest_user -d digest_db \
  -c "select id, url, is_active, consecutive_errors, last_error from feeds"
docker compose exec db psql -U digest_user -d digest_db \
  -c "select count(*) from articles"
```

The RabbitMQ management UI is available at http://127.0.0.1:15672 (user and password from `.env`). It is bound to `127.0.0.1` only.

## Configuration

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | yes | JWT signing key, at least 32 characters |
| `POSTGRES_PASSWORD` | yes (Docker) | Password of the database user |
| `RABBITMQ_PASSWORD` | yes (Docker) | Password of the RabbitMQ user |
| `POSTGRES_USER` | no | Database user, default `digest_user` |
| `POSTGRES_DB` | no | Database name, default `digest_db` |
| `RABBITMQ_USER` | no | RabbitMQ user, default `digest` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | no | Token lifetime, default `30` |
| `RATE_LIMIT_ENABLED` | no | Set to `false` to turn rate limits off, default `true` |
| `FETCH_INTERVAL_SECONDS` | no | How often Beat starts collection, default `1800` (minimum `60`) |
| `FEED_MAX_CONSECUTIVE_ERRORS` | no | Permanent errors in a row before a feed is disabled, default `5` |
| `LOG_JSON` | no | `true` for JSON logs, default `false` (Docker Compose sets `true`) |

Database, Redis and RabbitMQ URLs are assembled in `docker-compose.yml` from these values. The API uses `DATABASE_URL` (asyncpg), the worker uses `DATABASE_SYNC_URL` (psycopg2).

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
  -d '{"url":"https://news.ycombinator.com/rss","tags":["news"]}'

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

The tests use an in-memory SQLite database, so neither Docker nor Postgres is needed. Network access is faked with `respx`, and DNS lookups are replaced in the tests, so nothing goes to the internet.

## Project structure

```
app/
  api/        route handlers (auth, users, feeds)
  core/       settings, JWT and bcrypt, rate limiting, URL validation, logging
  db/         async engine for the API, sync session for the worker
  models/     SQLAlchemy models
  schemas/    Pydantic request and response models
  services/   feed fetcher, feed parser, article storage
  worker/     Celery app and tasks
migrations/   Alembic migrations
tests/        pytest suite
```

## Design decisions

- **JWT stores the user id, not the email**, so changing an email does not invalidate the identity in a token.
- **Uniqueness is enforced by the database** (unique constraints), because a "check then insert" in code can be beaten by two simultaneous requests.
- **Two-stage SSRF protection.** The URL format is checked when a feed is added. The host is resolved and every address is checked again on every download, because DNS records can change after the feed was added. Redirects are followed manually so that each target goes through the same checks, and the response is read as a stream with a size limit instead of being loaded whole.
- **Sync worker, async API.** Celery workers are synchronous, so they use a sync SQLAlchemy engine created lazily on first use. The API stays fully asynchronous. This is why there are two database URLs.
- **Idempotent tasks.** With `acks_late` a task can run twice, for example when a worker dies in the middle of it: the broker puts the message back in the queue. Storing articles therefore never creates duplicates: article URLs are unique, a content hash catches the same text under another URL, and if two workers race on the same URL the loser falls back to inserting one by one in savepoints. This works the same in SQLite and Postgres, while `ON CONFLICT` would need separate code for each.
- **Temporary and permanent errors are treated differently.** Retrying a 503 makes sense, retrying a 404 does not. Permanent errors increase a counter and disable the feed after several in a row, so a dead source stops costing resources. A temporary error that survives all retries counts as well.
- **The database connection is not held during the download.** A task reads the feed, closes the transaction, downloads and parses, and only then opens a new transaction to save the result.
- **The pgvector Postgres image is used from the start**, so semantic search does not require changing the database image later.

## Known limitations

- **DNS rebinding.** The host name is resolved once for the safety check and once more when the connection is made. A DNS server that changes its answer in between could slip a private address past the check. The full fix is to connect directly to the verified IP address. Until then, an egress firewall that blocks private ranges for the worker closes the gap.
- **A feed disabled automatically stays disabled.** There is no endpoint to re-enable it yet.
- **Collected articles cannot be read through the API yet.** `GET /digest` is on the roadmap.

## License

MIT, see [LICENSE](LICENSE).