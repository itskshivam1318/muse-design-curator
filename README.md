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
                    # (set the three providers to mock first, or it calls the live API)
make dev            # API on http://localhost:8000, app on http://localhost:5173
```

`make seed` runs extraction with whatever providers `.env` selects: with live providers it calls the
Meta API (and spends credit). The committed fixture corpus is 37 small synthetic images, enough to
exercise every feature but not to look good; see [Importing real photos](#importing-real-photos).

## Live vs mock

Every model sits behind a provider switch in `.env`:

| Variable | Default (live) | Mock (tests, offline) |
|---|---|---|
| `REASONING_PROVIDER` | `muse-spark` | `mock`; alternatives `muse-spark-open` (Baseten) |
| `SEGMENTATION_PROVIDER` | `sam-3.1` | `mock` |
| `EMBEDDER` | `siglip2` (`google/siglip2-base-patch16-256`, local; or `pe-core`) | `mock` (64-d colour histogram) |

Live is the default. Without `MODEL_API_KEY` the app still starts, model actions fail with
`PROVIDER_MISCONFIGURED`, and `GET /api/health` returns `{"ok": true, "live": false, "reason":
"MODEL_API_KEY not set"}`. For offline work force mocks:
`REASONING_PROVIDER=mock SEGMENTATION_PROVIDER=mock EMBEDDER=mock` (unit tests and `make e2e` always do).

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

## Explore → Visualize

Select an item, press `V` (or the toolbar's Explore button), and pick an attribute of the board's lens.
Explore asks the reasoning model for a handful of options for that attribute ("in the dimension"),
listed in the drawer and pinned beside the item as notes. More, Further, a steer line and Branch widen
or deepen the set; Dismiss removes one. **Visualize** edits the source photo into the option with the
image provider, adds the result as a new item captioned `generated · <model>`, and checks it: did the
target change, and which other attributes stayed (the verdict, also shown under "Generated from" in
Inspect). "Find real examples" starts a Vary run for options that map to a known value.

| Variable | Default | Meaning |
|---|---|---|
| `IMAGE_PROVIDER` | `muse-image` | Image-edit provider; `mock` is offline and deterministic (model id `mock-image`). |
| `IMAGE_MODEL` | `muse-image-1.0` | Model id sent to the image provider. |
| `EXPLORE_ENABLED` | `1` | Set `0` to hide Explore; `V` then opens the older Vary panel. |

Muse Image is restricted from India under Meta's Geographic Use Policy §2.2. It is used here for
development only; set IMAGE_PROVIDER to another provider for the demo.

## Plugins

Plugins are tools you place on the board as nodes: connect items, set params, Run, and the result
lands beside the node (images, notes) or on the inputs (attributes). Built-ins: Image, Palette and
Critique. Your own go in `data/plugins/<id>/` (python or llm), reloaded with
`POST /api/plugins/reload`; they run on your machine with your permissions (not a sandbox) and are
never loaded in demo mode. See [docs/plugins.md](docs/plugins.md) for the manifest, the I/O
contract and two examples. `PLUGINS_ENABLED=0` turns the feature off.

## Keys

| Key | Needed for | Notes |
|---|---|---|
| `MODEL_API_KEY` | live mode (required) | Meta Model API key (`LLM_…`), one key covers Muse Spark 1.3 and SAM 3.1. Never use `*-contributor` models: they grant Meta training rights over images we do not own. |
| `CONTACT_EMAIL` | Wikimedia Commons import, link unfurling | Sent in the User-Agent; Wikimedia blocks generic agents and rate-limits anonymous ones. |
| `OPENVERSE_CLIENT_ID` / `_SECRET` | optional | Anonymous Openverse works (20 results per page, 200 requests a day); a registered app gets 50 per page. The keys appear only in the registration response, so save it. |
| `SMITHSONIAN_API_KEY` | optional | Free api.data.gov key. With it, the Smithsonian is searched live through its API; without it, live search skips the Smithsonian and the importer reads the public S3 bulk files. |
| `EUROPEANA_API_KEY` | optional | Free key from pro.europeana.eu/page/get-api. Live search skips Europeana without it. |
| `BASETEN_API_KEY` | optional | Only for `REASONING_PROVIDER=muse-spark-open` (Baseten, `meta-models/muse-spark-open`). |
| `PEXELS_API_KEY` / `PEXELS_ENABLED` | off by design | Pexels' terms forbid systematic copying and automated collection "for machine learning purposes" without permission. The adapter stays off (`PEXELS_ENABLED=0`) and is capped at 300 items until written permission exists. |

Keys live only in `.env` (git-ignored) and are read server-side; the frontend and extension never see them.

## Corpus sources and licences

Every corpus item carries provenance (`source`, `source_id`, `landing_url`, `creator_name`,
`license_code`, `license_url`, `attribution_text`, `fetched_at`) and its credit is shown on every
candidate and, on the canvas, under every licensed image you hover or select (and in its Inspect
panel). Items whose licence is not on the allow-list are never downloaded or sent to a model.

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

## Real demo corpus (`make demo-data`)

`make demo-data` builds the real-photo demo from official APIs and bulk files (licence filters as
described above; `CONTACT_EMAIL` goes in the User-Agent), indexes it with the LIVE providers from
`.env`, and seeds the four demo boards. It is idempotent: manifests de-duplicate by id, indexed items
are skipped, and every model call is cached, so a re-run costs nothing. Hard caps (checked and printed
before any model call): at most 1,200 corpus items, 2,400 Muse Spark calls, 6,000 SAM calls. The plan
(`backend/scripts/demo_data.py`) imports per domain: watch (Commons "wristwatch dial", "chronograph
watch", "dive watch"; AIC "watch"), fashion (Smithsonian CHNDM, AIC "dress", Commons "streetwear"),
interior (Met "chair", Rijksmuseum "stoel", Commons "living room interior") and ui (Commons
"screenshot user interface", "dashboard screenshot"; each file keeps its own Commons licence, ND/NC
dropped). A source that fails (rate limit, outage, refusal) is skipped and the rest continue. Live
indexing takes about 40 s per item, so the demo indexes an evenly spaced subset of each manifest
(`INDEX_LIMIT` in the script; `make index DOMAIN=watch` indexes a whole manifest). The manifests in
`corpus/manifests/` are provenance only; images live in the gitignored `data/`.

State of the committed demo (2026-10-27): the Commons queries ran (watch 378, fashion 58, interior
79, ui 140 manifest lines), Smithsonian, AIC (HTTP 403), Met and Rijksmuseum failed from the build
machine and were skipped, and live indexing was stopped early: watch 80, fashion 40, ui 24 and
interior 2 items are indexed. The interior board therefore holds just those 2 items; its indexed
pool is empty, so its Vary runs rely on live search (below) until `make index DOMAIN=interior`
supplies more.
`backend/scripts/seed.py --no-index` seeds from what is already indexed.

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
3. **Kinds**: colours are *measured* from SAM part masks (Lab palettes, ΔE2000), as are numbers the
   lens computes from masks or palettes (`measure: mask_ratio | palette_count`); everything else,
   including model-read numbers (`measure: model`, e.g. a watch's case diameter), is *read* by Spark
   with confidence and evidence. A value below the reliable confidence
   counts as unknown, and unknown never matches.
4. **Board profile**: per-attribute distributions → signals (≥3 known, ≥60 % agree), tensions (two
   values ≥30 % each) and counter-signals from "not this" items; updates stream over SSE.
5. **Live search**: while the pool loads, one Spark call writes a few short queries and the engine
   searches the licensed sources (Commons, Openverse and the open-access museums) for up to
   `LIVE_TIMEOUT_S`; allow-listed results are downloaded through the same SSRF guard as links and
   *quick-indexed* (embedding and palette, no attributes) into the corpus, so they compete with
   indexed items. A source that refuses or times out cools down; the corpus alone still answers.
6. **Retrieval**: pool from the domain's indexed corpus, excluding source, invalid provenance,
   unusable, duplicates (dHash), items already on the board, and anything breaking the request; ranked
   by `rank-2026.10-c` (target .35, preservation .35, relevance .20, diversity .10; `validated: false`).
7. **Validation**: each shortlisted candidate is checked (provenance, duplicate, the target change,
   every protected attribute) by per-kind comparators; uncertain checks go to one batched Spark
   verify. A candidate is *validated* only if every check passes with evidence; ≤6 are returned.
8. **Feedback**: Keep places the candidate on the canvas with a lineage link to its source; Reject
   records a reason and can add it as a "not this" counter-example.

## Testing

```sh
make test           # backend: pytest
make lint           # ruff + mypy; oxlint + tsc (frontend, extension)
cd frontend && npm test     # frontend unit tests (vitest)
cd extension && npm test    # extension unit tests (vitest)
make e2e            # Playwright: builds the extension, runs the full demo flow and the extension flow
```

Current counts (2026-10-27): backend **558 passed**, frontend **109 passed**, extension **14 passed**,
e2e **2 passed** (`demo-flow.spec.ts`, `extension.spec.ts`).

`make e2e` is fully offline and ignores the providers in `.env`: Playwright starts a mock-provider
backend on ports 8765 (data in `data/e2e/`, wiped and re-seeded from the fixture corpus each run), a
static fixture site on 8766 (a page with `og:image`, an image page, and a 3 s MP4 generated with
PyAV) and the app on 5174, so it can run next to `make dev`. Run `npx playwright install chromium`
in `frontend/` once.

## Known limitations

- **No accounts.** Without `DEMO_MODE` the API has no authentication at all, and the extension
  pairing endpoints (`/api/extension/pair-code`, `/pair`) are open: any process that can reach the API
  can mint a code and pair. Run it locally, single-user. The [demo guard](#public-demo-guard) is a
  shared passcode, not accounts, and its rate-limit counters live in memory (a restart resets them).
- **Mock-verified vs live-verified.** Every feature is covered by tests on mock providers, and the
  Meta request/response shapes are verified live (`make smoke`) and replayed in tests. The whole
  pipeline on live models (extraction quality, verify calls, SigLIP 2 embeddings at corpus scale) has
  not been evaluated by an automated suite.
- **Thresholds are uncalibrated.** Ranking weights (`validated: false`), signal/tension cut-offs and
  colour/shape tolerances are first guesses, not tuned against labelled data.
- **`shape` kind is experimental** and off by default (`SHAPE_KIND_ENABLED=0`).
- **In-process jobs.** Parsing and variation runs run on a thread pool inside the API process: a
  restart drops in-flight work (retry from the UI), and the API must run as a single process.
- **Auto domain needs a clear vote.** An Auto board (no domain set) gets the curated lens by itself
  once at least 3 items are embedded, the vote is not mixed (runner-up under 40%) and the winning
  domain has a curated lens; the context bar then reads "Watch" instead of "Auto: watch". A domain you
  set is never changed. A mixed board stays without a lens and the engine proposes one for review.
- Choosing a video's key frame needs a mouse (the frame strip appears on hover).
- With `REASONING_PROVIDER=muse-spark-open`, the Muse Model License requires a "Built with Muse Spark
  Open" notice, which the UI does not show yet.

## Public demo guard

For a public instance, set `DEMO_MODE=1`. Visitors can then look but not add:

- **Open to everyone:** every read (boards, items, images, profile, live updates, runs, lenses),
  moving items, **Vary** (rate-limited, below) and Keep / Reject on candidates.
- **Needs the passcode:** creating or editing boards, uploads, links and extension captures,
  removing items, Not this, choosing a video frame, re-parsing, lens propose / confirm / edit,
  attribute edits and extension pairing. Locked requests get `403 DEMO_LOCKED`, and the app shows a
  "Demo — read-only" chip with an **Unlock** button. A correct passcode sets an HttpOnly, SameSite=Lax
  cookie (Secure over https), signed with `DEMO_SECRET` and valid 12 hours. Five wrong tries from one
  address in 10 minutes lock that address out for the rest of the window (`429`).
- **Vary limits:** `DEMO_RUNS_PER_IP_PER_HOUR` (default 10) per client address and
  `DEMO_RUNS_PER_DAY` (default 150) across everyone, as sliding windows: `429 DEMO_RATE_LIMITED` says
  when to retry. Repeating an identical request on the same board and source within 24 hours returns
  the finished run instead of starting a new one, with no new model calls and no count against the limits.

| Variable | Set as | Value |
|---|---|---|
| `DEMO_MODE` | variable | `1` |
| `DEMO_PASSCODE` | secret | the passcode you hand out |
| `DEMO_SECRET` | secret | random, e.g. `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `DEMO_TRUST_PROXY` | variable | `1` on a Space: the client address comes from `X-Forwarded-For`; leave `0` when nothing proxies the app (the connection address is used and the header ignored) |
| `DEMO_PROXY_HOPS` | variable | `1` on a Space: how many entries from the right of `X-Forwarded-For` the client address is (those are appended by trusted proxies; leftmost entries are client-supplied and never used) |
| `DEMO_DEEPEN` | variable | `0` (default): runs never queue background deepening of live items; `1` allows it (paid Spark and SAM calls, see Cost) |

The API refuses to start with `DEMO_MODE=1` and no `DEMO_PASSCODE` or `DEMO_SECRET`.

**Cost.** In live mode these calls are billed to the Meta key behind `MODEL_API_KEY` (embeddings
run locally and cost nothing):

- every unlocked upload or link: one Spark extraction plus one SAM call per lens part;
- every Vary run that is not a replay:
  - **query writing**: one small Spark call that turns the request into live searches (only when
    live search is on);
  - **SAM localisation**: one call per lens part the checks need, for the source and each
    shortlisted candidate (at most 16), unless that mask is already cached. Live items found at run
    time are quick-indexed (embedding and palette only), so their parts are always new;
  - **verify batches**: one Spark verify call per up to 8 shortlisted candidates (at most 2);
  - **deepen** (off in `DEMO_MODE` unless `DEMO_DEEPEN=1`): up to 16 shortlisted live items per run
    are fully indexed in the background, each one Spark extraction plus one SAM call per part.

Uploads are limited to people with the passcode, and the Vary limits above bound how many runs
anonymous visitors can start; with `DEMO_DEEPEN` left off, a run's spend ends when the run does. Meta
applies no spending cap of its own, so usage beyond the hackathon credit is charged to the card on file.

## Deploy

Nothing is deployed by this repository; these are the commands to run yourself. One Hugging Face
Docker Space serves the API (`/api`) and the built app (`/`) from the root `Dockerfile` on port 7860.
The app calls the API on its own origin. `VITE_API_URL` exists only for hosting the frontend elsewhere.

**1. Snapshot the existing `data/`.** The Space serves the real-photo corpus and demo boards in
`data/`, indexed with the providers the Space will use (embeddings from different embedders cannot
be mixed). Do not delete it: it took hours and real API spend to build. If you have no `data/` yet,
build it once with `make demo-data` (live providers, capped; see above). Then stop `make dev` so
SQLite's WAL is folded into `data/dle.sqlite`, and check it:

```sh
sqlite3 data/dle.sqlite "PRAGMA wal_checkpoint(TRUNCATE);"
# must print 0: only seeded corpus images and kept licensed candidates may be on the boards
sqlite3 data/dle.sqlite "SELECT count(*) FROM board_items WHERE origin NOT IN ('seed', 'candidate');"
```

> **`data/` becomes public.** Everything pushed to a public Space repo can be downloaded by anyone:
> the SQLite database (boards, decisions, the model-response cache), `embeddings.npy`, masks,
> thumbnails and every file in `data/uploads/`. Push only the licensed corpus and the demo boards.
> Never push a `data/` that has held your own uploads, links or extension captures (their files
> share `data/uploads/` with corpus images); rebuild it from `make demo-data` instead.

**2. Optional: check the image locally** (needs Docker):

```sh
docker build -t dle .
docker run --rm -p 7860:7860 --env-file .env -e DEMO_MODE=1 -e DEMO_PASSCODE=try-me \
  -e DEMO_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))") dle
# open http://localhost:7860
```

`--build-arg EXTRAS=""` builds a mock-only image without torch (much smaller).

**3. Create the Space and push** (Docker SDK). Binary files (SQLite, embeddings, images) must go
through Git LFS:

```sh
pip install -U "huggingface_hub[cli]"
huggingface-cli login
huggingface-cli repo create dle --type space --space_sdk docker     # or create it at huggingface.co/new-space
git clone https://huggingface.co/spaces/<you>/dle ../dle-space
cd ../dle-space
git lfs install
git lfs track "*.sqlite*" "*.npy" "*.jpg" "*.jpeg" "*.png" "*.webp" "*.gif" "*.mp4"
SRC=../muse-design-curator
rsync -a --exclude node_modules --exclude dist --exclude test-results --exclude playwright-report \
  --exclude '.env*' "$SRC/frontend" .
rsync -a --exclude .venv --exclude tests --exclude __pycache__ --exclude '.*_cache' --exclude '.env*' \
  "$SRC/backend" "$SRC/corpus" .
rsync -a --exclude e2e --exclude "*.sqlite-wal" --exclude "*.sqlite-shm" "$SRC/data" .
cp "$SRC/Dockerfile" "$SRC/.dockerignore" .
printf -- '---\ntitle: Design Language Engine\nsdk: docker\napp_port: 7860\n---\n' > README.md
git add -A && git commit -m "Deploy Design Language Engine" && git push
```

(With newer `huggingface_hub` releases the same commands are `hf auth login` and `hf repo create`.)

**4. Configure the Space** in *Settings → Variables and secrets*. Never put keys in files:

| Name | Kind | Value |
|---|---|---|
| `MODEL_API_KEY` | secret | your Meta key (`LLM_…`) |
| `DEMO_PASSCODE`, `DEMO_SECRET` | secret | see [Public demo guard](#public-demo-guard) |
| `DEMO_MODE`, `DEMO_TRUST_PROXY`, `DEMO_PROXY_HOPS` | variable | `1`, `1`, `1` |
| `REASONING_PROVIDER`, `SEGMENTATION_PROVIDER`, `EMBEDDER` | variable | `muse-spark`, `sam-3.1`, `siglip2` |
| `CONTACT_EMAIL` | variable | your email (link-unfurl User-Agent) |

The Space restarts with the new settings, and the app is at `https://<you>-dle.hf.space`. The
Space's disk is ephemeral: changes made after unlock are lost on restart unless you attach
persistent storage and set `DATA_DIR=/data` and `DATABASE_URL=sqlite:////data/dle.sqlite`. The baked
snapshot is copied there on first start. The Chrome extension is a local tool: its host permission
covers `localhost:8000` only, and pairing needs the passcode on a demo.

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
2026-10-27 docs: README with quick start, live vs mock, keys, corpus licences, extension, architecture, tests, limitations, deploy
2026-10-27 test(e2e): wait for the nudge run itself, not the previous run's status
2026-10-27 feat(demo): DEMO_MODE guard - read-only until unlocked, capped Vary runs
2026-10-27 feat(api): serve the built frontend with an SPA fallback when FRONTEND_DIST is set
2026-10-27 feat(frontend): demo badge, passcode unlock, read-only controls while locked
2026-10-27 style(frontend): show the + button as disabled in a locked demo
2026-10-27 build(deploy): one Space serves API and app; root multi-stage Dockerfile
```
