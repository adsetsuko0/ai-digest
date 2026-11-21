#!/usr/bin/env bash
# Roll out a published image version on the server.
# Usage: bash deploy/deploy.sh 1.0.0
set -euo pipefail

VERSION="${1:?Usage: bash deploy/deploy.sh <version>, for example 1.0.0}"
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ ! -f .env ]; then
  echo "Missing .env (copy deploy/env.prod.example and fill it in)" >&2
  exit 1
fi

compose() { docker compose -f docker-compose.prod.yml "$@"; }

# remember the version so that a later plain `docker compose up` does not go back
if grep -q '^AI_DIGEST_VERSION=' .env; then
  sed -i "s/^AI_DIGEST_VERSION=.*/AI_DIGEST_VERSION=${VERSION}/" .env
else
  echo "AI_DIGEST_VERSION=${VERSION}" >> .env
fi

echo "==> Pulling the application images"
compose pull app worker beat
echo "==> Applying database migrations"
compose run --rm app alembic upgrade head
echo "==> Starting the stack"
compose up -d --remove-orphans

echo "==> Waiting for /health"
for _ in $(seq 1 30); do
  if compose exec -T app python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" >/dev/null 2>&1; then
    echo "OK: version ${VERSION} is running"
    compose ps
    docker image prune -f >/dev/null
    exit 0
  fi
  sleep 2
done

echo "The app did not become healthy; the last log lines:" >&2
compose logs --tail 50 app >&2
exit 1