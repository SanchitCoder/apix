# APIx collector image: Scrapy for static sources, Playwright for rendered ones.
#
# The Playwright browser download is the only heavyweight step here. Only Chromium is
# installed — no other engine is used, and each one costs several hundred megabytes.

# ------------------------------------------------------------------- builder ----
FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.9 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /build

COPY pyproject.toml uv.lock ./
COPY packages/apix_core/pyproject.toml packages/apix_core/
COPY apps/api/pyproject.toml apps/api/
COPY apps/collector/pyproject.toml apps/collector/
COPY apps/scheduler/pyproject.toml apps/scheduler/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package apix-collector

COPY packages/apix_core packages/apix_core
COPY apps/collector apps/collector

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package apix-collector

# ------------------------------------------------------------------ runtime ----
FROM python:3.12-slim-bookworm AS runtime

ENV APIX_CONFIG_DIR=/app/config \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 apix \
    && useradd --system --uid 10001 --gid apix --no-create-home apix

WORKDIR /app

# Only the virtualenv: --no-editable put real wheels in it, so no source is needed.
COPY --from=builder --chown=apix:apix /build/.venv /app/.venv
COPY --chown=apix:apix config /app/config
COPY --chown=apix:apix fixtures /app/fixtures

# Chromium plus its system libraries. Installed as root, then handed to apix.
RUN playwright install --with-deps chromium \
    && chown -R apix:apix /ms-playwright

USER apix

# Idle by default. Collection is triggered by Prefect, never by container start:
# starting a container must not cause traffic to a source website.
CMD ["python", "-c", "import time; time.sleep(2**31)"]
