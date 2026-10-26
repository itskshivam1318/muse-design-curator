export PATH := $(HOME)/.local/bin:$(PATH)

.PHONY: install dev test lint e2e seed import index ext smoke

install:
	uv python install 3.12
	cd backend && uv sync --extra embed
	cd frontend && npm install
	cd extension && npm install
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example — add MODEL_API_KEY")

dev:
	cd backend && uv run uvicorn app.main:app --reload --port 8000 & \
	cd frontend && npm run dev -- --port 5173 & \
	wait

test:
	cd backend && uv run pytest

lint:
	cd backend && uv run ruff check . && uv run mypy app scripts
	cd frontend && npm run lint && npx tsc -b
	cd extension && npm run lint

e2e:
	@echo "e2e: not implemented yet (Task 14)"

seed:
	cd backend && uv run python scripts/seed.py --fixtures

import:
	cd backend && uv run python scripts/import_corpus.py --domain $(DOMAIN) --source $(SOURCE) --query "$(QUERY)" --limit $(or $(LIMIT),200)

index:
	cd backend && uv run python scripts/index_corpus.py --domain $(DOMAIN)

ext:
	cd extension && npm run build

smoke:
	cd backend && uv run python scripts/smoke_meta.py
