#!/usr/bin/env bash
# Brings up the full local backend (Postgres, Redis, migrations, reference data,
# synthetic fare dataset, index computation, API) so that `npm run dev` in apps/web
# always has real, freshly-computed data to show. Idempotent: safe to run every time
# the frontend starts, on top of an already-running stack.
#
# This machine has no Docker/system Homebrew, so Postgres/Redis/the API run as plain
# local processes rather than containers — see the user-local Homebrew at
# ~/homebrew set up for this project.
#
# Deliberately does NOT touch config/sources.yaml or run the Scrapy/Playwright
# collector: every source in this repo is PolicyEngine-gated and most are
# NOT_REVIEWED/disabled by design (CLAUDE.md principle 3). "Fresh data" here means
# the labelled synthetic dataset (fixtures/synthetic — never live scraping), same as
# `make collect-once`/`make seed-synthetic`.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$REPO_ROOT/.dev-logs"
mkdir -p "$LOG_DIR"

export PATH="$HOME/homebrew/bin:$PATH"

log() { printf '[dev-backend] %s\n' "$*"; }

# ---------------------------------------------------------------- postgres ----
PGDATA="$HOME/homebrew/var/postgresql@16"
if pg_isready -h localhost -p 5432 >/dev/null 2>&1; then
  log "postgres already running"
else
  log "starting postgres..."
  pg_ctl -D "$PGDATA" -l "$LOG_DIR/postgres.log" start
  for _ in $(seq 1 30); do
    pg_isready -h localhost -p 5432 >/dev/null 2>&1 && break
    sleep 1
  done
fi

if ! psql -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='apix'" | grep -q 1; then
  log "creating apix role..."
  createuser -s apix
  psql -d postgres -c "ALTER USER apix WITH PASSWORD 'apix';" >/dev/null
fi
if ! psql -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='apix'" | grep -q 1; then
  log "creating apix database..."
  createdb -O apix apix
fi

# ------------------------------------------------------------------- redis ----
if redis-cli ping >/dev/null 2>&1; then
  log "redis already running"
else
  log "starting redis..."
  redis-server "$HOME/homebrew/etc/redis.conf" --daemonize yes --logfile "$LOG_DIR/redis.log"
  for _ in $(seq 1 15); do
    redis-cli ping >/dev/null 2>&1 && break
    sleep 1
  done
fi

# ------------------------------------------------------------- env + deps ----
cd "$REPO_ROOT"
if [ ! -f .env ]; then
  log ".env missing — see .env.example; refusing to guess secrets" >&2
  exit 1
fi
set -a
# shellcheck disable=SC1091
source .env
set +a

log "syncing python workspace..."
uv sync --all-packages >"$LOG_DIR/uv-sync.log" 2>&1

# ------------------------------------------------------------- data + index ----
log "running migrations..."
uv run alembic upgrade head >"$LOG_DIR/migrate.log" 2>&1

log "seeding reference data..."
uv run python -m apix_scheduler.seed_reference >"$LOG_DIR/seed-reference.log" 2>&1

log "refreshing synthetic fare dataset (this is fixture data, never a live scrape)..."
uv run python -m apix_core.testing.seed --days 90 >"$LOG_DIR/seed-synthetic.log" 2>&1

# apix_core.testing.seed's rolling window ends yesterday, not today — a real
# collector wouldn't have finished "collecting" today's fares while today is still
# in progress, and seed_synthetic mirrors that. Compute the index as of the last day
# that actually has data, not literally today, or every cell would be skipped for
# having no observation at the window's own newest date.
AS_OF="$(date -v-1d +%Y-%m-%d 2>/dev/null || date -d 'yesterday' +%Y-%m-%d)"
log "computing the index as of $AS_OF..."
uv run python -m apix_scheduler.index_run --date "$AS_OF" --days 21 >"$LOG_DIR/index-run.log" 2>&1

# ----------------------------------------------------------- dev api key ----
# apps/web/.env carries a local-dev-only API key so the frontend can reach
# authenticated endpoints (method preview, provenance, quotes, exports). It only
# works if a matching api_key row exists — ensure it does, without ever printing or
# logging the key value itself.
WEB_ENV="$REPO_ROOT/apps/web/.env"
if [ -f "$WEB_ENV" ]; then
  DEV_API_KEY="$(grep -m1 '^VITE_APIX_API_KEY=' "$WEB_ENV" | cut -d= -f2-)"
  if [ -n "$DEV_API_KEY" ]; then
    log "ensuring local-dev api key is registered..."
    APIX_DEV_API_KEY="$DEV_API_KEY" uv run python -c "
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from apix_core.provenance.hashing import sha256_hex
from apix_core.models import ApiKey, Role
from apix_core.settings import get_settings

key = os.environ['APIX_DEV_API_KEY']
settings = get_settings()
engine = create_engine(settings.database_sync_url)
with Session(engine) as session:
    existing = session.query(ApiKey).filter_by(key_hash=sha256_hex(key.encode())).one_or_none()
    if existing is None:
        session.add(ApiKey(key_hash=sha256_hex(key.encode()), role=Role.OFFICIAL, label='local-dev-frontend'))
        session.commit()
" >"$LOG_DIR/dev-api-key.log" 2>&1
  fi
fi

# --------------------------------------------------------------------- api ----
if curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/healthz 2>/dev/null | grep -q 200; then
  log "api already running"
else
  log "starting api..."
  nohup uv run uvicorn apix_api.main:app --host 0.0.0.0 --port 8000 \
    >"$LOG_DIR/api.log" 2>&1 &
  echo $! >"$LOG_DIR/api.pid"
  for _ in $(seq 1 30); do
    curl -s -o /dev/null http://localhost:8000/healthz 2>/dev/null && break
    sleep 1
  done
fi

log "backend ready: http://localhost:8000/docs"
