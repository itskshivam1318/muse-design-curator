export PATH := $(HOME)/.local/bin:$(PATH)

.PHONY: install dev test lint e2e seed import index demo-data ext smoke demo-record board-export board-import

install:
	uv python install 3.12
	cd backend && uv sync --extra embed
	cd frontend && npm install
	cd extension && npm install
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example — add MODEL_API_KEY")

# Backgrounded jobs ignore SIGINT, so without the trap Ctrl-C orphans uvicorn on :8000.
dev:
	@trap 'trap - INT TERM EXIT; kill 0' INT TERM EXIT; \
	(cd backend && uv run uvicorn app.main:app --reload --port 8000) & \
	(cd frontend && npm run dev -- --port 5173) & \
	wait

test:
	cd backend && uv run pytest

lint:
	cd backend && uv run ruff check . && uv run mypy app scripts
	cd frontend && npm run lint && npx tsc -b
	cd extension && npm run lint

# Offline: Playwright starts a MOCK-provider backend on a fresh data/e2e, a fixture site and the
# frontend (see frontend/playwright.config.ts), then tears them down. Never touches .env providers.
e2e:
	cd extension && npm run build
	cd frontend && npx playwright test

seed:
	cd backend && uv run python scripts/seed.py --fixtures

import:
	cd backend && uv run python scripts/import_corpus.py --domain $(DOMAIN) --source $(SOURCE) --query "$(QUERY)" --limit $(or $(LIMIT),200)

index:
	cd backend && uv run python scripts/index_corpus.py --domain $(DOMAIN)

# Real-photo demo corpus (network + LIVE models from .env; capped, cached, idempotent): import -> index -> seed.
demo-data:
	cd backend && uv run python scripts/demo_data.py --yes

ext:
	cd extension && npm run build

smoke:
	cd backend && uv run python scripts/smoke_meta.py

# Film a board while Claude Code works it (docs/demo/boards.md): make demo-record BOARD=<id> SLUG=<slug>
demo-record:
	@test -n "$(BOARD)" -a -n "$(SLUG)" || (echo "usage: make demo-record BOARD=<id> SLUG=<car|ui|room|outerwear>"; exit 2)
	node frontend/scripts/record-board.mjs --board "$(BOARD)" --slug "$(SLUG)" $(if $(APP),--app $(APP)) $(if $(API),--api $(API)) $(if $(MAX_MIN),--max-min $(MAX_MIN))

# Move a finished board between machines (docs/demo/board-bundles.md).
# make board-export BOARD=<id> OUT=<path.zip>
board-export:
	@test -n "$(BOARD)" -a -n "$(OUT)" || (echo "usage: make board-export BOARD=<id> OUT=<path.zip>"; exit 2)
	cd backend && uv run python -m app.bundle export "$(BOARD)" "$(abspath $(OUT))"

# make board-import FILE=<path.zip> [REPLACE=1]
board-import:
	@test -n "$(FILE)" || (echo "usage: make board-import FILE=<path.zip> [REPLACE=1]"; exit 2)
	cd backend && uv run python -m app.bundle import "$(abspath $(FILE))" $(if $(REPLACE),--replace)
