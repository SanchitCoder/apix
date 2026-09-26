# APIx API image. Multi-stage, non-root, no dev dependencies in the final layer.
# Also used by the one-shot `migrate` service — it needs Alembic and the models, which
# is exactly what this image already carries.

# ------------------------------------------------------------------- builder ----
FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.9 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Matches the runtime stage's WORKDIR: uv bakes the venv's absolute path into every
# console-script shebang (e.g. uvicorn) at creation time, so if this stage built the
# venv at a different path, the copied scripts would exec a path that no longer exists.
WORKDIR /app

# Manifests first, so a dependency layer is only rebuilt when a pin changes.
COPY pyproject.toml uv.lock ./
COPY packages/apix_core/pyproject.toml packages/apix_core/
COPY apps/api/pyproject.toml apps/api/
COPY apps/collector/pyproject.toml apps/collector/
COPY apps/scheduler/pyproject.toml apps/scheduler/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package apix-api

COPY packages/apix_core packages/apix_core
COPY apps/api apps/api

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package apix-api

# ------------------------------------------------------------------ runtime ----
FROM python:3.12-slim-bookworm AS runtime

# libpq for psycopg2 (Alembic and the sync path). No compilers in the final image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 apix \
    && useradd --system --uid 10001 --gid apix --no-create-home apix

ENV APIX_CONFIG_DIR=/app/config \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Only the virtualenv: --no-editable put real wheels in it, so no source is needed.
COPY --from=builder --chown=apix:apix /app/.venv /app/.venv

# Runtime inputs: migrations, validated config, reference seeds.
COPY --chown=apix:apix alembic.ini ./
COPY --chown=apix:apix db /app/db
COPY --chown=apix:apix config /app/config

USER apix

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz', timeout=3).status == 200 else 1)"

CMD ["uvicorn", "apix_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
