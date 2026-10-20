# syntax=docker/dockerfile:1.7
# Build from the repository root:  docker build -f backend/Dockerfile .
# One image runs the API, the worker, the migrations and the seed script (only the command differs).

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
WORKDIR /srv/citesure/backend

# --- dependencies: cached until pyproject.toml / uv.lock change ------------------------------
FROM base AS deps
# WITH_ML=true adds fastembed (local ONNX embeddings + cross-encoder reranker) and bakes the models into the image,
# so nothing is downloaded at runtime. The default image uses the offline fake providers (no model files).
ARG WITH_ML=false
# WITH_S3=true adds boto3 so STORAGE_BACKEND=s3 works (uploads in an S3 bucket instead of a volume).
ARG WITH_S3=false
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    EXTRA=""; \
    if [ "$WITH_ML" = "true" ]; then EXTRA="$EXTRA --extra ml"; fi; \
    if [ "$WITH_S3" = "true" ]; then EXTRA="$EXTRA --extra s3"; fi; \
    uv sync --frozen --no-dev --no-install-project $EXTRA
ENV FASTEMBED_CACHE_PATH=/opt/models
RUN if [ "$WITH_ML" = "true" ]; then \
      .venv/bin/python -c "from fastembed import TextEmbedding; from fastembed.rerank.cross_encoder import TextCrossEncoder; \
TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/opt/models'); TextCrossEncoder('Xenova/ms-marco-MiniLM-L-6-v2', cache_dir='/opt/models')"; \
    else mkdir -p /opt/models; fi

# --- runtime: no compilers, no uv cache, non-root user --------------------------------------
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/srv/citesure/backend/.venv/bin:$PATH" \
    FASTEMBED_CACHE_PATH=/opt/models \
    STORAGE_PATH=/data/uploads
RUN useradd --create-home --uid 10001 app && mkdir -p /data/uploads && chown -R app /data
WORKDIR /srv/citesure/backend
COPY --from=deps /srv/citesure/backend/.venv ./.venv
COPY --from=deps /opt/models /opt/models
COPY backend/ ./
# The demo corpus and golden set let `python -m app.seed` and `python -m app.evals.run` work inside the container.
COPY corpus/demo /srv/citesure/corpus/demo
COPY backend/evals /srv/citesure/backend/evals
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"
CMD ["uvicorn", "app.main:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000"]
