# Design Language Engine

A design-reference board that learns what a set of references has in common and lets you explore
one dimension of an item at a time. You drop images, videos, links and notes onto an infinite
canvas; Muse Spark (Meta Model API) reads each item through a domain *lens* (watch, fashion,
interior, UI, or a lens it proposes for anything else), SAM 3.1 locates the parts the lens names,
and the board shows its consistent signals, tensions and "not this" counter-signals. Select an
item to see its callouts, click a dimension to grow a flower of options, and render one (see
"Explore → Visualize" below). The earlier Vary flow (retrieve licensed alternatives that change one
thing) is retired.

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

## The calm board

The board is a quiet canvas: a rail on the left (Library, Plugins, and the other panels), a small
floating toolbar at the bottom, and nothing else until you ask. **Select an item** and its parts
appear as callouts around it (a mask for a photo's parts, a box for a screen's, a passage for a
note's), each with its dimensions, plus a "Whole item" card; hover a callout to see its region.
**Click a dimension** and a flower grows beside the item: its options as note petals around a hub,
nothing generated. Open a petal to render it with the renderer it names (Muse Image inside the
part's mask or box, or Muse Spark rewriting only that passage); the result is checked, and **Keep**
puts it on the board as an ordinary item with its own callouts, so the loop starts again from
there. **Extract** cuts a part out as a linked item. **Notes**: press `N` and click to write on the
board. **Plugins** are nodes you add from the rail and place from the toolbar's Nodes menu; see
[Plugins](#plugins) and [docs/plugins.md](plugins.md).

**Put one picture into another.** Select a picture and drag from the dot on its right edge onto
another: the parts you aim at light up (every part of the same kind, or just the spot under the
line), let go, add a few words if you like, and **Put in**. A "Putting in…" box holds the place
until a new picture of the target arrives with the source put in; both originals stay as they
were, and the result keeps a line back to each.

**The board floats.** Items, flowers, petals and callouts drift gently and nudge aside as you drag
or add things; a new item grows in and its neighbours make room. The positions you save are *homes*:
what the board drifts around. Drift and pushes are never saved; only a release (a drag, a hub drag)
or a keep writes a position. With the system's reduce-motion setting on, nothing drifts or
overshoots, though things still glide out of the way.

## Explore → Visualize

Select an item and its **callouts** show what Muse read: one card per part with its physical
dimensions, and a "Whole item" card with the abstract ones. **Click a dimension** to explore it:
the reasoning model proposes a handful of options and a **flower** grows beside the item, the
options as **note petals** around a hub; nothing is generated yet. More like this widens the set
and Dismiss trims it; the hub collapses the flower to a badge on its callout. Open a petal
and its card has one **render** button named by the renderer that will run: "Generate image · Muse
Image inside the part's mask or box" (or the whole image for an abstract dimension), "Rewrite
passage · Muse Spark" for a note, a board plugin, or "Connect a renderer" when nothing renders the
item. The result is checked (did the target change, which other dimensions stayed) and shown on the
card; **Keep** puts it on the board as an ordinary item with its own callouts, so the loop starts
again from there. **Extract** on a part cuts it out as a new, linked item; **Re-analyse** on the
item toolbar reads an item again. Each board has a daily allowance: analyses (uploads, Re-analyse,
explore, extract) and renders (petals, note Visualize) are counted separately and refused with
"Daily limit reached for this board, try tomorrow." once used up.

| Variable | Default | Meaning |
|---|---|---|
| `IMAGE_PROVIDER` | `muse-image` | Image-edit provider; `mock` is offline and deterministic (model id `mock-image`). |
| `IMAGE_MODEL` | `muse-image-1.0` | Model id sent to the image provider. |
| `ANALYSE_PER_BOARD_PER_DAY` | `300` | Analyses one board may run per day. |
| `RENDER_PER_BOARD_PER_DAY` | `60` | Renders one board may run per day. |
| `EXPLORE_ENABLED` | `1` | Set `0` to turn exploring off: callouts still show, a dimension opens no flower. |

Muse Image is restricted from India under Meta's Geographic Use Policy §2.2. It is used here for
development only; set IMAGE_PROVIDER to another provider for the demo.

## Plugins

Plugins are tools you place on the board as nodes: connect items, set params, Run, and the result
lands beside the node (images, notes) or on the inputs (attributes). Built-ins: Image, Palette and
Critique. Your own go in `data/plugins/<id>/` (python or llm), reloaded with
`POST /api/plugins/reload`; they run on your machine with your permissions (not a sandbox) and are
never loaded in demo mode. See [docs/plugins.md](plugins.md) for the manifest, the I/O
contract and two examples. `PLUGINS_ENABLED=0` turns the feature off.

## Working a board from Claude Code (MCP)

Muse serves its board tools over MCP (streamable HTTP) at `/mcp`: create or open a board, set a
goal with its deliverables, add notes and references, analyse, explore, visualize, wait for
results, lay out an output sheet and finish. The endpoint is off by default (`/mcp` answers 404).

1. Set `MCP_ENABLED=1` in `.env` (or in the environment) and run `make dev`.
2. Connect Claude Code to it:

   ```bash
   claude mcp add --transport http muse http://localhost:8000/mcp
   ```

3. Open the app at http://localhost:5173, then give Claude Code a first prompt such as:

   > Create a board called EV coupe, set a goal "a two-door electric coupe" with these
   > deliverables: front three-quarter view, side profile, interior, colour option. Add a note for
   > each, visualize them, wait for each image, lay out the output sheet and finish. Narrate each
   > step with `say`.

4. Open the board it creates (it is listed on the home page). Notes and images land on the canvas
   as each call completes; the agent card in the corner shows the goal, ticks off each deliverable
   once the output sheet covers it, and lists every step with its `say` sentence and the call it
   made. Click a step to jump to its item; star one to highlight it. When `finish` accepts the
   sheet the card shows **done**; if a result check fails it refuses, says why, and after three
   refusals the run waits for you (**needs input**).

Each MCP session keeps its own open board and run. Two clients on different boards do not step
on each other; on the same board they share its one open run (the second `set_goal` joins it,
or pauses it and starts a new one with `replace: true`). **Stop run** in the agent card pauses an
open run.

- `render_view` draws a picture again from another viewpoint ("from the rear") as a new picture
  beside it; `wait(kind="job")` picks it up if it is slow.
- `put_into` puts one picture's subject into another at part keys or points; it waits the same way.
- Muse Code, like any other MCP client that speaks streamable HTTP, connects to the same URL.
- An MCP session expires after about 30 minutes without a call. The client then gets a new
  session with no board open: call `open_board` again (the board's open run is picked up).
- Under mock providers (no model key) the result check on each generated image is a made-up
  answer, so `finish` may refuse an output by chance (an item "failed its result check"):
  visualize that item again, or swap it for another.
- `upload_reference` reads image files from the machine Muse runs on, so `/mcp` only accepts
  requests addressed to `localhost`/`127.0.0.1` (or the host of `PUBLIC_APP_URL`) and from pages
  on those origins; anything else is refused.
- With `DEMO_MODE` on and locked, write tools are refused.

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
corpus item and, on the canvas, under every licensed image you hover or select (and in its Inspect
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
pool is nearly empty until `make index DOMAIN=interior` supplies more.
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
5. **Explore and render**: a clicked dimension gets options from the reasoning model; a petal
   renders one (image edit, note rewrite or a plugin), the result is checked against the target and
   the other dimensions, and Keep puts it on the board as an ordinary item.
6. **Retired Vary** (retrieval from the licensed corpus, evidence checks, Maybe strip): its
   `/runs` and decision routes answer `410 VARY_RETIRED`; its tables and orchestrator stay for history.

## Testing

```sh
make test           # backend: pytest
make lint           # ruff + mypy; oxlint + tsc (frontend, extension)
cd frontend && npm test     # frontend unit tests (vitest)
cd extension && npm test    # extension unit tests (vitest)
make e2e            # Playwright: builds the extension, runs the full demo flow and the extension flow
```

Current counts (2026-11-04): backend **1261 passed**, frontend **638 passed**, extension **14 passed**.

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
- **In-process jobs.** Parsing, analysis and render jobs run on a thread pool inside the API process: a
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

- **Open to everyone:** every read (boards, items, images, profile, live updates, lenses) and
  moving items.
- **Needs the passcode:** creating or editing boards, uploads, links and extension captures,
  removing items, Not this, choosing a video frame, re-parsing, attribute edits and extension pairing. Locked requests get `403 DEMO_LOCKED`, and the app shows a
  "Demo — read-only" chip with an **Unlock** button. A correct passcode sets an HttpOnly, SameSite=Lax
  cookie (Secure over https), signed with `DEMO_SECRET` and valid 12 hours. Five wrong tries from one
  address in 10 minutes lock that address out for the rest of the window (`429`).
- **Limits:** the per-IP Vary run limits no longer exist. Analyses and renders are bounded per board
  per day (`ANALYSE_PER_BOARD_PER_DAY`, `RENDER_PER_BOARD_PER_DAY`, see Explore → Visualize).

| Variable | Set as | Value |
|---|---|---|
| `DEMO_MODE` | variable | `1` |
| `DEMO_PASSCODE` | secret | the passcode you hand out |
| `DEMO_SECRET` | secret | random, e.g. `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `DEMO_TRUST_PROXY` | variable | `1` on a Space: the client address comes from `X-Forwarded-For`; leave `0` when nothing proxies the app (the connection address is used and the header ignored) |
| `DEMO_PROXY_HOPS` | variable | `1` on a Space: how many entries from the right of `X-Forwarded-For` the client address is (those are appended by trusted proxies; leftmost entries are client-supplied and never used) |

The API refuses to start with `DEMO_MODE=1` and no `DEMO_PASSCODE` or `DEMO_SECRET`.

**Cost.** In live mode these calls are billed to the Meta key behind `MODEL_API_KEY` (embeddings
run locally and cost nothing):

- every unlocked upload or link: one Spark extraction plus one SAM call per lens part;
- every analysis (Re-analyse, explore, extract): one Spark call, plus SAM calls for parts;
- every render (a petal, note Visualize): one Muse Image or Spark call plus its check.

Uploads are limited to people with the passcode, and the per-board daily allowances bound analyses
and renders. Meta applies no spending cap of its own, so usage beyond the hackathon credit is charged to the card on file.

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

Every commit from 2026-10-26 to 2026-11-04 is listed, oldest first, in [BUILD_LOG.md](BUILD_LOG.md).
Each feature has a design spec and an implementation plan in [superpowers/](superpowers/).
