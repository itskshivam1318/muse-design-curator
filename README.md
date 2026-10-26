# Design Language Engine

A live design-reference board (infinite canvas) backed by a FastAPI engine
(Meta Model API: Muse Spark + SAM 3.1), a React/Vite canvas app and a Chrome MV3 extension.

- `backend/` FastAPI engine (Python 3.12, uv)
- `frontend/` Vite React-TS canvas app
- `extension/` Chrome MV3 extension (`make ext` builds to `extension/dist`)

Copy `.env.example` to `.env`, then `make dev`, `make test`, `make lint`, `make smoke`.
