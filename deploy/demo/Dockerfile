# syntax=docker/dockerfile:1.7
# CiteSure public demo as ONE container (Render, Koyeb, a Hugging Face Docker Space, any Docker host).
# Postgres 16 + pgvector, worker, API and nginx all run inside; nginx serves the app on :7860. The database is
# created, migrated and seeded at build time. Fits the free 512 MB / 0.1 CPU tiers (about 310 MB in use).
# Fake models and the fictional corpus only: no API keys, nothing private, data resets when the container restarts.
#
# The app code is cloned from GitHub at build time, so a host only needs the files in this folder.
#   local test:  docker build -t citesure-demo deploy/demo && docker run --rm -p 7860:7860 citesure-demo
# Pin a release for a reproducible deploy:  --build-arg CITESURE_REF=<commit sha or tag>

ARG CITESURE_REPO=https://github.com/sharadgupta27/CiteSure.git
ARG CITESURE_REF=main

# --- source ----------------------------------------------------------------------------------
FROM python:3.12-slim AS src
ARG CITESURE_REPO
ARG CITESURE_REF
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
# fetch + checkout works for a branch, a tag or a full commit sha
RUN git init -q /src && cd /src && git remote add origin "$CITESURE_REPO" \
    && git fetch -q --depth 1 origin "$CITESURE_REF" && git checkout -q FETCH_HEAD && rm -rf .git

# --- frontend build --------------------------------------------------------------------------
FROM node:22-alpine AS web
WORKDIR /app
COPY --from=src /src/openapi.yaml ./openapi.yaml
COPY --from=src /src/frontend ./frontend
WORKDIR /app/frontend
RUN npm ci --no-audit --no-fund && npm run gen:api && npm run build

# --- runtime: the pgvector image already has Postgres 16 with the extension ------------------
FROM pgvector/pgvector:pg16 AS runtime
RUN apt-get update && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends nginx ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
ENV UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /srv/citesure/backend
# uv installs the Python version named in .python-version (3.12); the image's own Python is not used.
COPY --from=src /src/backend/pyproject.toml /src/backend/uv.lock /src/backend/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project && rm -rf /root/.cache
COPY --from=src /src/backend ./
COPY --from=src /src/corpus/demo /srv/citesure/corpus/demo
COPY --from=web /app/frontend/dist /srv/citesure/web
COPY nginx.conf /etc/nginx/nginx.conf
COPY booting.conf live.conf /etc/nginx/citesure/
COPY starting.html /srv/citesure/boot/starting.html
COPY start.sh /usr/local/bin/start-citesure

# Run as uid 1000 (what Hugging Face Spaces require, fine elsewhere); Postgres needs that user to own its data folder.
RUN chmod 755 /usr/local/bin/start-citesure \
    && useradd -m -u 1000 user \
    && mkdir -p /data/pg /data/uploads /var/lib/nginx /var/log/nginx \
    && chown -R 1000:1000 /data /var/lib/nginx /var/log/nginx

ENV PATH="/srv/citesure/backend/.venv/bin:/usr/lib/postgresql/16/bin:$PATH" \
    ENV=prod \
    LLM_PROVIDER=fake \
    EMBEDDING_PROVIDER=fake \
    RERANKER=lexical \
    PUBLIC_RESEARCH_ENABLED=false \
    UPLOADS_ENABLED=false \
    STORAGE_PATH=/data/uploads \
    SEED_PASSWORD=citesure-demo \
    CORS_ORIGINS=http://localhost:7860 \
    TRUST_PROXY_HEADERS=true \
    PGDATA=/data/pg

USER user
# Build the demo database into the image, so a start on a slow free host only launches processes.
RUN start-citesure prepare
EXPOSE 7860
# bash, not Python: a check every 30 s must not cost an interpreter start on a 0.1-CPU host
HEALTHCHECK --interval=30s --timeout=5s --start-period=300s --retries=5 \
  CMD bash -c 'exec 3<>/dev/tcp/127.0.0.1/7860 && printf "GET /healthz HTTP/1.0\r\n\r\n" >&3 && read -r _ s _ <&3 && [ "$s" = 200 ]'
CMD ["start-citesure"]
