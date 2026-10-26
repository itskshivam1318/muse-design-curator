# Design Language Engine

A design-reference board that learns what a set of references has in common and finds licensed
alternatives that change exactly one thing. You drop images, videos and links onto an infinite
canvas; Muse Spark (Meta Model API) reads each item through a domain *lens* (watch, fashion,
interior, UI, or a lens it proposes for anything else), SAM 3.1 locates the parts the lens names,
and the board shows its consistent signals, tensions and "not this" counter-signals. Select an
item, say what to vary ("dial colour, anything different", "legibility: one step more") and what to
keep, and the engine retrieves candidates from an open-licence corpus, checks every one against
the request with evidence, and streams the ones that pass into a Maybe strip with their credits.
It never generates or edits images.

- `backend/` FastAPI engine (Python 3.12, uv, SQLite + NumPy, no vector database)
- `frontend/` Vite + React + react-konva canvas app
- `extension/` Chrome MV3 extension (right-click → Add to board)

## Quick start

```sh
make install        # Python 3.12 + backend deps (incl. the `embed` extra), npm deps; creates .env from .env.example
# edit .env: MODEL_API_KEY=LLM_... and CONTACT_EMAIL=you@example.com for live mode (see below)
make seed           # index the committed fixture corpus and create the four demo boards
make dev            # API on http://localhost:8000, app on http://localhost:5173
```

`make seed` runs extraction with whatever providers `.env` selects: with live providers it calls the
Meta API (and spends credit). The committed fixture corpus is 37 small synthetic images, enough to
exercise every feature but not to look good; see [Importing real photos](#importing-real-photos).

## Live vs mock

Every model sits behind a provider switch in `.env`:

| Variable | Mock (default) | Live |
|---|---|---|
| `REASONING_PROVIDER` | `mock` | `muse-spark` (Meta, `muse-spark-1.3`) or `muse-spark-open` (Baseten) |
| `SEGMENTATION_PROVIDER` | `mock` | `sam-3.1` |
| `EMBEDDER` | `mock` (64-d colour histogram) | `siglip2` (`google/siglip2-base-patch16-256`, local) or `pe-core` |

Meta has no embeddings endpoint (`/v1/embeddings` returns 404), so the live embedder runs locally
and needs the `embed` extra (`make install` includes it). Embeddings from different embedders are
not comparable: after changing `EMBEDDER`, delete `data/` and run `make seed` (or `make index`) again.

Mock providers are deterministic (a hash of image, prompt and schema) and offline; their values are
arbitrary, so signals and validation results under mock show the plumbing, not judgement. There is no
global live/mock badge: the Inspect panel says "Values were read by the mock provider, not a real
model." on items whose values came from the mock, and `GET /api/items/{id}/attributes` reports the
provider (`provider.id`, `provider.is_mock`) with every item's values.

`make smoke` runs live checks against the Meta API (and Baseten if keyed) and saves the raw replies
to `backend/tests/fixtures/meta/live/`. Last run 2026-10-27 from India, all PASS: Spark text 5.2 s,
schema-constrained JSON 8.4 s, SAM image 2.2 s, SAM video 2.7 s, `/embeddings` 404 (expected).

## Keys

| Key | Needed for | Notes |
|---|---|---|
| `MODEL_API_KEY` | live mode (required) | Meta Model API key (`LLM_…`), one key covers Muse Spark 1.3 and SAM 3.1. Never use `*-contributor` models: they grant Meta training rights over images we do not own. |
| `CONTACT_EMAIL` | Wikimedia Commons import, link unfurling | Sent in the User-Agent; Wikimedia blocks generic agents and rate-limits anonymous ones. |
| `OPENVERSE_CLIENT_ID` / `_SECRET` | optional | Anonymous Openverse works (20 results per page); registered access raises the page size to 500. |
| `SMITHSONIAN_API_KEY` | optional, currently unused | The Smithsonian importer reads the public S3 bulk files, which need no key. |
| `BASETEN_API_KEY` | optional | Only for `REASONING_PROVIDER=muse-spark-open` (Baseten, `meta-models/muse-spark-open`). |
| `PEXELS_API_KEY` / `PEXELS_ENABLED` | off by design | Pexels' terms forbid systematic copying and automated collection "for machine learning purposes" without permission. The adapter stays off (`PEXELS_ENABLED=0`) and is capped at 300 items until written permission exists. |

Keys live only in `.env` (git-ignored) and are read server-side; the frontend and extension never see them.

## Corpus sources and licences

Every corpus item carries provenance (`source`, `source_id`, `landing_url`, `creator_name`,
`license_code`, `license_url`, `attribution_text`, `fetched_at`) and its credit is shown on every
candidate. Items whose licence is not on the allow-list are never downloaded or sent to a model.

| Source | Licence | Used for |
|---|---|---|
| Wikimedia Commons | per file: CC0, PD, CC BY, CC BY-SA (NC and ND excluded) | the main watch source; streetwear and interiors |
| Openverse | CC0, public domain mark, CC BY, CC BY-SA only | second watch source (Flickr CC) |
| The Met Open Access | CC0 (`isPublicDomain` checked per object) | fashion, interiors, heritage timepieces |
| Smithsonian / Cooper Hewitt | CC0 (`usage.access == "CC0"`), S3 bulk files | textiles, costume, prints |
| Art Institute of Chicago | public domain (`is_public_domain`) | fashion, furniture |
| Rijksmuseum | PD / CC0, CC BY with credit | heritage objects |
| Self-captured | per entry, SPDX (MIT, Apache-2.0, …) | UI screens: screenshots of permissively licensed open-source apps (no licensed UI corpus exists) |

Excluded, and why: **Unsplash** (API mandates hotlinking and routes ML use to a separate programme),
**V&A** (non-commercial only, no local copies beyond four weeks), **Pixabay** (ML-use clause, 24 h
cache), **Pexels** (ML-use clause; off unless permission is granted), and any **NC/ND** licence.
Sources are fetched through official APIs or bulk files, never by scraping HTML.

## Importing real photos

Import appends licensed items to `corpus/manifests/<domain>.jsonl`; index downloads, segments,
tags and embeds them with the providers in `.env` (live providers spend API credit):

```sh
make import DOMAIN=watch SOURCE=commons QUERY="wristwatch dial" LIMIT=200
make import DOMAIN=watch SOURCE=openverse QUERY="wristwatch"
make import DOMAIN=fashion SOURCE=met QUERY="dress"
make index DOMAIN=watch
cd backend && uv run python scripts/seed.py      # demo boards from the real manifests (no --fixtures)
```

Sources: `commons`, `openverse`, `met`, `smithsonian`, `aic`, `rijks`, `pexels` (gated),
`self_capture` (a hand-written manifest:
`uv run python scripts/import_corpus.py --domain ui --source self_capture --input my_ui.jsonl`).
Your own photos need no import: drop them on a board (they are stored unmodified and marked
`user_supplied`; they are never added to the corpus).

## Chrome extension

```sh
make ext            # builds extension/dist
```

1. Open `chrome://extensions`, turn on Developer mode, **Load unpacked**, choose `extension/dist`.
2. In the app, press **+** → **Get the Chrome extension**: it shows a 6-digit code (valid 10 minutes).
3. Click the extension's toolbar icon, enter the code, **Pair**, then choose a board.
4. Right-click any image → **Add to board** (or a video → **Add this video to board**), or use
   **Add this page** in the popup to add the page's preview image.

The extension talks to `http://localhost:8000` only (its host permission); it is a local tool.

## Architecture in brief

1. **Ingest**: uploads, drops, pastes, links (og:image unfurl, SSRF-guarded) and extension captures
   become board items; originals are stored unmodified, videos yield key frames.
2. **Lens**: a domain's curated lens (≤8 parts, ≤20 attributes of seven kinds: enum, ordinal, number,
   boolean, color, text, shape) or, for an unknown domain, a lens Spark proposes from ≤20 diverse items for you to review.
3. **Kinds**: colours and numbers are *measured* from SAM part masks (Lab palettes, ΔE2000); the rest
   is *read* by Spark with confidence and evidence. Unknown stays unknown.
4. **Board profile**: per-attribute distributions → signals (≥3 known, ≥60 % agree), tensions (two
   values ≥30 % each) and counter-signals from "not this" items; updates stream over SSE.
5. **Retrieval**: pool from the domain's indexed corpus, excluding source, invalid provenance,
   unusable, duplicates (dHash), items already on the board, and anything breaking the request; ranked
   by `rank-2026.10-c` (target .35, preservation .35, relevance .20, diversity .10; `validated: false`).
6. **Validation**: each shortlisted candidate is checked (provenance, duplicate, the target change,
   every protected attribute) by per-kind comparators; uncertain checks go to one batched Spark
   verify. A candidate is *validated* only if every check passes with evidence; ≤6 are returned.
7. **Feedback**: Keep places the candidate on the canvas with a lineage link to its source; Reject
   records a reason and can add it as a "not this" counter-example.

## Testing

```sh
make test           # backend: pytest
make lint           # ruff + mypy; oxlint + tsc (frontend, extension)
cd frontend && npm test     # frontend unit tests (vitest)
cd extension && npm test    # extension unit tests (vitest)
make e2e            # Playwright: builds the extension, runs the full demo flow and the extension flow
```

Current counts (2026-10-27): backend **414 passed**, frontend **76 passed**, extension **13 passed**,
e2e **2 passed** (`demo-flow.spec.ts`, `extension.spec.ts`).

`make e2e` is fully offline and ignores the providers in `.env`: Playwright starts a mock-provider
backend on ports 8765 (data in `data/e2e/`, wiped and re-seeded from the fixture corpus each run), a
static fixture site on 8766 (a page with `og:image`, an image page, and a 3 s MP4 generated with
PyAV) and the app on 5174, so it can run next to `make dev`. Run `npx playwright install chromium`
in `frontend/` once.

## Known limitations

- **No authentication.** The API has no accounts, and the extension pairing endpoints
  (`/api/extension/pair-code`, `/pair`) are unauthenticated: any process that can reach the API can mint
  a code and pair. This is a local, single-user tool. Before exposing an instance publicly, add real
  auth and rate-limit pairing.
- **Mock-verified vs live-verified.** Every feature is covered by tests on mock providers, and the
  Meta request/response shapes are verified live (`make smoke`) and replayed in tests. The whole
  pipeline on live models (extraction quality, verify calls, SigLIP 2 embeddings at corpus scale) has
  not been evaluated by an automated suite.
- **Thresholds are uncalibrated.** Ranking weights (`validated: false`), signal/tension cut-offs and
  colour/shape tolerances are first guesses, not tuned against labelled data.
- **`shape` kind is experimental** and off by default (`SHAPE_KIND_ENABLED=0`).
- **In-process jobs.** Parsing and variation runs run on a thread pool inside the API process: a
  restart drops in-flight work (retry from the UI), and the API must run as a single process.
- **Domain is inferred, not auto-applied.** The board shows the domain its items vote for ("Auto:
  watch"); the curated lens attaches when you pick that domain. Without a choice, the engine proposes
  a lens for review instead.
- Choosing a video's key frame needs a mouse (the frame strip appears on hover).
- With `REASONING_PROVIDER=muse-spark-open`, the Muse Model License requires a "Built with Muse Spark
  Open" notice, which the UI does not show yet.

## Deploy

Nothing is deployed by this repository; these are the commands to run yourself. The API goes to a
Hugging Face Docker Space, the app to Vercel.

**1. Build the data snapshot** (live providers, real corpus; see above), then stop `make dev` so
SQLite's WAL is checkpointed into `data/dle.sqlite`.

**2. Optional: check the image locally** (needs Docker):

```sh
docker build -f backend/Dockerfile -t dle-api .
docker run --rm -p 7860:7860 --env-file .env dle-api      # http://localhost:7860/api/health
```

Add `--build-arg EXTRAS=""` for a mock-only image without torch (much smaller).

**3. API → Hugging Face Space.** Create a Space at <https://huggingface.co/new-space> (SDK: Docker,
blank template), say `<you>/dle-api`. Then stage and upload:

```sh
STAGE=$(mktemp -d)
rsync -a --exclude .venv --exclude tests --exclude __pycache__ --exclude '.*_cache' backend corpus "$STAGE"/
rsync -a --exclude e2e data "$STAGE"/
cp backend/Dockerfile .dockerignore "$STAGE"/
printf -- '---\ntitle: Design Language Engine API\nsdk: docker\napp_port: 7860\n---\n' > "$STAGE/README.md"
uvx --from huggingface_hub hf auth login
uvx --from huggingface_hub hf upload <you>/dle-api "$STAGE" . --repo-type space
```

In the Space's **Settings → Variables and secrets** add the secret `MODEL_API_KEY` and the variables
`REASONING_PROVIDER=muse-spark`, `SEGMENTATION_PROVIDER=sam-3.1`, `EMBEDDER=siglip2`,
`CONTACT_EMAIL=…` and `PUBLIC_APP_URL=https://<your-app>.vercel.app` (the CORS origin). The
snapshot baked into the image is copied into `DATA_DIR` on first start; the Space's disk is
ephemeral, so for persistence attach storage and set `DATA_DIR=/data` and
`DATABASE_URL=sqlite:////data/dle.sqlite`. The API is then at `https://<you>-dle-api.hf.space`.
Remember there is no authentication (see above).

**4. App → Vercel** (`frontend/vercel.json` adds the SPA rewrites):

```sh
cd frontend
npx vercel link
npx vercel env add VITE_API_URL production      # https://<you>-dle-api.hf.space
npx vercel deploy --prod
```

`VITE_API_URL` is read at build time; without it the app expects the API on its own origin under
`/api` (as with the dev proxy).

## Built during the hackathon

Generated with `git log --reverse --format='%ad %s' --date=short`:

```
2026-10-26 docs: spec, plan and research for Design Language Engine
2026-10-26 docs: make plan tasks self-contained; add item embedding columns
2026-10-26 chore: scaffold backend, frontend, extension; meta smoke script
2026-10-26 fix: load .env from repo root regardless of cwd
2026-10-26 feat(domain): seven attribute kinds, lens schema, four curated lenses
2026-10-26 feat(db): boards, items, lineage, profiles, runs schema and repos
2026-10-26 fix(db): monotonic ids for ordering; unique curated lens versions
2026-10-26 feat(ingest): images, video keyframes, link unfurl
2026-10-26 fix(ingest): bounded video sampling, duration cap, pinned SSRF connections
2026-10-26 feat(providers): Meta client, SAM decode, embedders, reliability, cache, mocks
2026-10-26 fix(providers): accept documented hyphenated selector values
2026-10-26 feat(measure): palette, shape and crop measurement
2026-10-26 fix(measure): typing
2026-10-26 feat(lens): board-driven lens selection and proposal
2026-10-26 fix(lens): defer events and jobs until after commit
2026-10-26 feat(parsing): lens-driven item parsing with edit-preserving merge
2026-10-26 fix(parsing): measure whole-image parts and release write lock before model call
2026-10-26 feat(board): live board profile and SSE
2026-10-26 test(board): cover attribute edit route recompute
2026-10-26 feat(corpus): licensed importers, provenance, indexer, seed
2026-10-26 fix(corpus): keep invalid items pending, drop index-time dedupe
2026-10-26 fix(corpus): failed rows that turn invalid become pending
2026-10-26 feat(variation): request invariants incl. nudge
2026-10-26 feat(retrieval): domain pool, comparators, exclusions
2026-10-26 feat(retrieval): scores and diversity selection
2026-10-26 fix(retrieval): clamp pair similarity so diversity stays in 0..1
2026-10-26 feat(validation): per-kind validator with batched verify
2026-10-26 fix(validation): unreliable number cannot pass a nudge
2026-10-26 feat(runs): orchestration, summary, API
2026-10-26 feat(feedback): decisions, keep onto board, not-this
2026-10-26 fix(feedback): neutralise spreadsheet formulas in decisions CSV
2026-10-26 feat(retrieval): exclude candidates already on the board
2026-10-26 feat(extension): one-click capture to board
2026-10-26 fix(extension): limit pair-code attempts and validate code format
2026-10-26 feat(api): serve item images and video frames by id; board lens lookup
2026-10-27 feat(ui): typed API client, SSE cache sync, upload validation
2026-10-27 feat(ui): infinite board canvas, add flow, context and board signals
2026-10-27 fix(api): board lens lookup returns {lens: null} instead of 404
2026-10-27 fix(ui): end marquee on any mouseup, guard stray file drops, keep Space for focused buttons
2026-10-27 fix(ui): no third-party favicon fetch; abort uploads on unmount and on Cancel
2026-10-27 feat(ui): typed attribute/run/decision client and pure vary logic
2026-10-27 feat(ui): Inspect and Vary drawer panels
2026-10-27 feat(ui): Maybe strip, candidate popover and keep/reject decisions
2026-10-27 feat(ui): Compare, toolbar and board wiring for inspect/vary/strip
2026-10-27 fix(ui): Inspect skips a PATCH when the value is unchanged; toolbar tests
2026-10-27 chore: make install target; keep live Meta recordings separate from test fixtures
2026-10-27 fix(ui): only http(s) source links; modal, focus-trapped candidate and shortfall dialogs
2026-10-27 test(providers): replay live Meta recordings
2026-10-27 fix(providers): mock lens proposal is a valid lens
2026-10-27 fix(seed): leave candidates in the pool
2026-10-27 fix(feedback): place kept items without overlap
2026-10-27 fix(boards): choosing a curated domain attaches its lens
2026-10-27 feat(ingest): test-only LINK_ALLOW_PRIVATE_HOSTS exemption
2026-10-27 feat(frontend): VITE_API_URL for a cross-origin API; DLE_API_PROXY for dev
2026-10-27 test(e2e): offline Playwright demo flow and extension suite
2026-10-27 build(deploy): HF Docker Space image for the API, Vercel config for the app
```
