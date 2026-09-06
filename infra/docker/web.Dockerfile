# APIx dashboard: React 18 + Vite + TypeScript, built to static files and served by
# nginx as a non-root user.

# ------------------------------------------------------------------- builder ----
FROM node:22-bookworm-slim AS builder

WORKDIR /build

COPY apps/web/package.json apps/web/package-lock.json* ./
RUN npm ci || npm install

COPY apps/web/ ./
RUN npm run build

# ------------------------------------------------------------------ runtime ----
FROM nginxinc/nginx-unprivileged:1.27-alpine AS runtime

# The unprivileged image already runs as uid 101 and listens on 8080.
COPY --from=builder /build/dist /usr/share/nginx/html
COPY infra/docker/web-nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget --spider -q http://localhost:8080/ || exit 1
