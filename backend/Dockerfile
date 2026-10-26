# syntax=docker/dockerfile:1
# Design Language Engine API, packaged for a Hugging Face Docker Space (port 7860).
#
# Build from the repository root so the precomputed data/ snapshot can be baked in:
#   docker build -f backend/Dockerfile -t dle-api .
#   docker run --rm -p 7860:7860 --env-file .env dle-api
#
# Secrets (MODEL_API_KEY, ...) are never baked in: pass them as environment variables
# (Space settings -> Variables and secrets). With none set, every provider is the mock.
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

# The `embed` extra (torch + transformers) is needed for EMBEDDER=siglip2, i.e. for live mode with
# a corpus indexed by SigLIP 2. A mock-only image can drop it: --build-arg EXTRAS=""
ARG EXTRAS="--extra embed"
COPY --chown=user backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project $EXTRAS
COPY --chown=user backend/ ./
RUN uv sync --frozen --no-dev $EXTRAS

# Corpus manifests and the precomputed data snapshot (sqlite, embeddings, images, masks). The
# snapshot is copied into DATA_DIR on first start, so DATA_DIR may also be a mounted volume.
COPY --chown=user corpus/ /home/user/app/corpus/
COPY --chown=user data/ /home/user/app/data-baked/

ENV PATH="/home/user/app/backend/.venv/bin:$PATH" \
    PORT=7860 \
    DATA_DIR=/home/user/app/data \
    DATABASE_URL=sqlite:////home/user/app/data/dle.sqlite \
    HF_HOME=/home/user/.cache/huggingface

EXPOSE 7860
CMD ["sh", "docker-entrypoint.sh"]
