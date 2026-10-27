# syntax=docker/dockerfile:1
# Design Language Engine: one container serving the API (/api) and the built app (/), made for a
# Hugging Face Docker Space (port 7860). Build from the repository root:
#   docker build -t dle .
#   docker run --rm -p 7860:7860 --env-file .env dle        # http://localhost:7860
#
# Secrets are never baked in; pass them as environment variables (Space settings -> Variables and
# secrets): MODEL_API_KEY, DEMO_PASSCODE, DEMO_SECRET. The provider defaults are LIVE (muse-spark,
# sam-3.1, siglip2); set REASONING_PROVIDER=mock SEGMENTATION_PROVIDER=mock EMBEDDER=mock for an
# offline container.

# ---- 1. the frontend, built same-origin (no VITE_API_URL) ----
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- 2. the API runtime ----
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /uvx /bin/

# Spaces run the container as uid 1000
RUN useradd --create-home --uid 1000 user
USER user
ENV HOME=/home/user \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /home/user/app/backend

# The `embed` extra (torch + transformers) is needed for EMBEDDER=siglip2, i.e. live mode. A
# mock-only image can drop it: --build-arg EXTRAS=""
ARG EXTRAS="--extra embed"
COPY --chown=user backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project $EXTRAS
COPY --chown=user backend/ ./
RUN uv sync --frozen --no-dev $EXTRAS

# Corpus manifests and the pre-built data/ (indexed corpus + seeded demo boards: sqlite,
# embeddings, images, masks). It is baked at the default DATA_DIR; when DATA_DIR points elsewhere
# (a mounted volume), the entrypoint copies it there on first start.
COPY --chown=user corpus/ /home/user/app/corpus/
COPY --chown=user data/ /home/user/app/data/
COPY --from=web --chown=user /web/dist /home/user/app/frontend/dist

ENV PATH="/home/user/app/backend/.venv/bin:$PATH" \
    PORT=7860 \
    DATA_DIR=/home/user/app/data \
    DATABASE_URL=sqlite:////home/user/app/data/dle.sqlite \
    FRONTEND_DIST=/home/user/app/frontend/dist \
    HF_HOME=/home/user/.cache/huggingface

EXPOSE 7860
CMD ["sh", "docker-entrypoint.sh"]
