# Final whole-branch review: feat/design-language-engine (511f061..c4f3bc0)

Reviewer: Opus 5.5 (read-only; no tree mutation). Scope: 95 commits, ~32.9k lines excluding manifests and lockfiles.
Method: five passes (security and deploy surface, data integrity and concurrency, core-promise correctness, frontend, tests/README/migrations), reading code at HEAD. I ran one read-only Python check against the comparator. The `data/` snapshot was inspected with `sqlite3 ?immutable=1`.

## Strengths

- **Demo guard is default-deny and well shaped.** `main.py` middleware blocks every non-GET write outside a short allow-list (`demo.py:_OPEN_WRITES`). PATCH /items is narrowed again to position fields in the route (`items.py:165`). The cookie is HMAC-signed and compared as bytes, so a crafted non-ASCII cookie cannot raise a TypeError. The unlock lockout and per-IP and global Vary windows work. The API refuses to start without a passcode and secret. The XFF handling (right-most N hops, `--proxy-headers` removed) is correct.
- **SSRF guard on link unfurl is solid.** Scheme check, every resolved address vetted, the connection pinned to the vetted IP (closes DNS rebinding), manual redirects re-checked on each hop, `trust_env=False`, and a body cap (`ingest/links.py`).
- **File serving is safe.** Media is looked up by id only (`api/media.py`). The SPA fallback resolves and `is_relative_to`-checks paths and refuses `/api/*` (`spa.py`).
- **Secrets stay out of the build.** `.dockerignore` is an allow-list that excludes `**/.env*`. No keys appear in tracked files or live fixtures. Extension tokens are stored as SHA-256 hashes. The Docker image runs as uid 1000 and pulls CPU-only torch on Linux.
- **The validator honours the hard rules.** A segmentation mask can only lead to `uncertain`, never `pass`. A comparator `fail` is skipped by the localisation and fallback paths (`validator.py:836`). Unknown or missing values become `uncertain`. Verify answers below the reliable confidence are ignored. A broken verify batch degrades only its own checks to `uncertain`. `_overall` is fail > uncertain > validated. Decisions are append-only (`repos/decisions.py`, no update or delete paths), and the CSV export blocks formula injection.
- **Concurrency was handled with care.** `after_commit` for side effects, WAL plus `busy_timeout`, short write transactions, `EMBEDDINGS_LOCK` around row allocation → flush → commit with atomic `.npy` replace, and a bounded background queue.
- **Canvas rule is met.** Images render with no stroke, radius, padding or shadow. Outline and handles are drawn outside the bounds (`nodeProps.hoverOutlineRect`). External hrefs pass through `safeExternalUrl`.
- **Strong test base.** 531 backend, 103 frontend and 2 e2e tests, with replay of live Meta payloads.

## Issues

### Critical (Must Fix)

1. **The number comparator ignores confidence, so unreliable values can pass or exclude** — `backend/app/validation/comparators.py:65-72`.
   - **What's wrong:** `compare()` checks reliability for enum, boolean and ordinal values but not for `number`. The watch lens's `case_diameter_mm` is `measure: "model"`. Verified: `compare(case_diameter_mm, AttrValue(40.0, 0.1, "uncertain"), AttrValue(40.5, 0.1, "uncertain"))` returns `"same"`, and 36 vs 44 at confidence 0.1 returns `"different"`.
   - **Why it matters:** A protected number check passes, and an explore target "changes", on a low-confidence model guess. `filters.py` also applies `hard_constraint` and `no_target_change` exclusions on unreliable evidence. This breaks the spec rules "a candidate with unknown protected attributes must not pass a strict preservation check" and "apply hard constraints … when evidence is reliable", and the global "unknown never matches". The README claim "validated only if every check passes with evidence" is false for numbers. The nudge path was fixed in Task 13, but the general comparator was not.
   - **How to fix:** In the number branch, `if not (a.reliable(cfg) and b.reliable(cfg)): return "unknown"`. Measured numbers carry confidence 1.0 (`extraction/service.py:164`), so they are unaffected. Add a unit test for low-confidence numbers next to `test_number_within_tol…`.

### Important (Should Fix)

2. **Kept candidates can never be varied and are invisible to the board's embedding signals** — `backend/app/feedback/service.py:_create_item` (≈L153-163) with `runs/orchestrator.py:138`.
   - **What's wrong:** Keep creates a board item with `parse_status="completed"` but never sets `embedding_json`, and no parse job is queued. `create_run` then rejects it with `409 SOURCE_NOT_READY "has not been analysed yet"`. The completed status means the UI offers no retry, and in DEMO_MODE re-parse is locked anyway. Kept items are also left out of the board centroid (relevance), lens sampling and domain votes. Kept quick-depth live items additionally get zero attributes.
   - **Why it matters:** "Keep, then vary the kept one" is the natural next step in the core loop. It fails with a misleading message, on the public demo too.
   - **How to fix:** At keep time, copy the corpus item's embedding row (`load_matrix()[cx.embedding_row]`, same embedder) into `item.embedding_json`. For quick items with no attributes, either enqueue `parse_item` or mark the item `pending`.

3. **SSE connections tie up the shared threadpool; about 40 open tabs freeze the API** — `backend/app/board/events.py:45` (`await run_in_threadpool(sub.get, 0.5)` in a loop).
   - **What's wrong:** Each EventSource client almost continuously holds one token of anyio's default limiter (40). That limiter also runs every sync `def` route. Opening the board events stream is an open, unlimited GET.
   - **Why it matters:** On a public Space, about 40 concurrent viewers, or one person opening 40 EventSources, stalls every sync API request for everyone.
   - **How to fix:** Make `Subscription` async. `publish` can push with `loop.call_soon_threadsafe` into an `asyncio.Queue` (or an anyio memory stream), then `await asyncio.wait_for(q.get(), 0.5)`. Or give SSE its own `CapacityLimiter`. Also cap SSE connections per client IP in DEMO_MODE.

4. **Runs are marked stale from `created_at`, so queued runs fail as "interrupted"** — `backend/app/runs/orchestrator.py:439-450` with `jobs.py` (2 workers shared with `parse_item`).
   - **What's wrong:** A live run takes about 50 s. Runs and parse jobs share 2 workers, so a burst of about 12 runs, or one unlocked 50-file upload, puts later runs more than 5 minutes past `created_at`. The next `GET /api/runs/{id}` poll marks them `RUN_INTERRUPTED` while they are still queued (`execute_run` then skips them), and the attempt still counts against the visitor's demo limit. A run marked stale mid-flight is later overwritten to `completed` (the deferred T14 race).
   - **How to fix:** Store `started_at` / `heartbeat_at`, written by `_report`. Mark stale only on a stale heartbeat, never while `queued`, unless the process restarted (for example, record a boot id). Make the worker's final write conditional on the status not being `failed`. Consider a separate queue for runs.

5. **Corpus images on the public canvas show no credit or licence** — `backend/app/api/schemas.py:item_to_dict`, `frontend/src/panels/InspectPanel.tsx`, `ItemToolbar.tsx`.
   - **What's wrong:** Seeded and kept items are CC BY / BY-SA Commons photos (and others). The item payload carries no licence or attribution. Credit is shown only on candidate cards. The canvas, Inspect panel and toolbar show only "Open source". This is the deferred T20 item "credit lines only in candidate provenance".
   - **Why it matters:** Publicly displaying CC BY / BY-SA works without attribution (creator, licence, link) breaches their licence terms on the moment of deploy. The spec also says "preserve … provenance".
   - **How to fix:** Join `corpus_items` (`attribution_text`, `license_code`, `license_url`, `creator_name`) into `item_to_dict` when `corpus_item_id` is set. Render a credit line in Inspect and in the toolbar or hover.

6. **Live downloads follow redirects with no address check, and anonymous visitors can trigger them** — `backend/app/live/quick_index.py:136-138` (`follow_redirects=True`, no `check_url`); same pattern in `corpus/sources/base.py:90` and `corpus/indexer.py:171`.
   - **What's wrong:** In DEMO_MODE any visitor can start a Vary run. The run downloads `image_url`s returned by Openverse (third-party hosts) and other sources, following redirects anywhere, including private and link-local addresses inside the Space.
   - **Why it matters:** Exploitation needs a poisoned source record, so the likelihood is low. But this is the one outbound fetch reachable without the passcode, and the guard already exists.
   - **How to fix:** Reuse `ingest.links.check_url` (pinned transport, manual redirects) in `_download`, or at least validate each hop with an httpx `event_hooks` request hook.

7. **Anonymous spend is under-documented and partly uncapped** — `runs/orchestrator.py:410-411` (`MAX_DEEPEN_PER_RUN = 16`), README "Cost".
   - **What's wrong:** Each non-replayed anonymous run can queue up to 16 `deepen_item` jobs. Each runs full indexing (one Spark extraction plus a SAM call per part). On top of that come the query-writing Spark call and per-candidate SAM calls. The README says the Vary limits "cap what anonymous visitors can spend" and lists only verify calls. The deepen work is limited only by the single background worker's throughput (about 2,000 items/day at about 40 s each).
   - **How to fix:** In DEMO_MODE, either disable deepening or put it behind a daily cap. Rewrite the Cost paragraph to list every call a run makes.

8. **README deploy instructions contradict the real-corpus demo and contain a destructive step** — `README.md:250-256`, `:112-114`, `:179`, `:150-165`; `Dockerfile:9`.
   - **What's wrong:**
     - Step 1 says `rm -rf data && make seed` (the fixture corpus). That deletes the real-photo corpus the user decided to ship (Task 20), which took hours and real API spend to index.
     - "until live search (a later task)" is stale.
     - The test counts (432/83) are stale; the current counts are 531/103.
     - "Architecture in brief" omits live licensed-source search, a core Vary feature.
     - "colours and numbers are measured from SAM masks" is wrong: `case_diameter_mm` is read by the model.
     - The Dockerfile says "With no provider variables set, every provider is the mock", but the defaults are now live.
     - The deploy section does not warn that `data/` (sqlite including any developer uploads, decisions and model cache) becomes public files in a public Space repo.
   - **How to fix:** Rewrite step 1 as "snapshot the existing `data/` (stop `make dev`, checkpoint WAL)". Fix the stale lines. Add the public-data warning.

### Minor (Nice to Have)

9. **SigLIP 2 is reloaded from disk on every call** — `backend/app/providers/__init__.py:66`. `get_embedder()` constructs `SigLIP2Embedder()` (`from_pretrained`) on every parse, live run and index batch. That is seconds of latency and about 1.5 GB per concurrent copy on a CPU Space. Cache one instance behind a lock, and warm it at startup in live mode so the first visitor's run does not pay the HF download.
10. **The `quick_index` httpx client is never closed** — `backend/app/live/quick_index.py:136`. One leaked connection pool per run. Use `with`, or close it in `finally` when the client was created locally.
11. **Duplicate verify rows: the last one wins** — `backend/app/validation/validator.py:645-669`. The loop does not skip checks already answered (`c.ask` is False), so a conflicting later row can flip a verify `fail` to `pass`. NaN confidence passes `conf < reliable`. Fix with `if not c.ask: continue` and `math.isfinite(conf)`.
12. **A text check that the comparator failed is still sent to verify** — `validator.py:829` (`ask = … or aspec.kind == "text"`). This cannot happen today because `compare(text)` always returns `unknown`. Add `and verdict != "fail"` so "fail stays fail" holds by construction.
13. **Run limits are check-then-record and not atomic** — `api/runs.py:45-50`. Two simultaneous requests can both pass at the limit boundary. Low impact.
14. **`DEMO_TRUST_PROXY` hop count on HF is unverified.** If the right-most XFF entry is an internal HF proxy, every visitor shares one 10/hour bucket and one 5-try unlock lockout, so one person can lock everyone out of unlocking for 10 minutes. Log `client_ip` once after deploy and adjust `DEMO_PROXY_HOPS`.
15. **`DEMO_SECRET` has no minimum length check** — `demo.check_settings`. Enforce at least 32 characters.
16. **`.env.example` has no `DEMO_*` entries** (they are documented only in the README). `frontend/README.md` is still the Vite template.
17. **Kept items accumulate on shared demo boards** (a user decision allows it). Every kept item is excluded from later runs as `on_board`, so the demo boards slowly run out of candidates. Consider a nightly reset from the baked snapshot.

## Deferred-minor triage

- T0 (smoke PASS lines, BLE001, mypy ignores, make dev trap, Vite demo content, Settings tests): can wait.
- T0 (default-path .env load, repo .env leak into tests, ENV_FILE layout): can wait. The conftest isolation is in place.
- T1 (bbox ValidationError, snake_case, LensSpec.id vs domain, curated key pinning, assert in handler, TDD order): can wait.
- T2 (name-based append-only check, decisions without FKs, no downgrade/drift test, enum CHECKs; ordering test, per-process monotonic ids, 0001 amended): can wait. Single-process deploy.
- T3 (uploads read before size check, per-read timeout, IDNA → 500, sync DB on loop, storage OSError, weak tests, ftyp brand, Capture.kind): can wait. All are behind unlock in DEMO_MODE.
- T3 (private httpx internals, 8192 px frame, first A record only): can wait. Versions are pinned by uv.lock.
- T4 (httpx2 undeclared, pe-core extra, with_timeout thread leak, check_model_id on mock, box-without-mask, untested mocks, hand-written fixtures; no-op replace, id underscores): can wait.
- T5 (shape thresholds fitted to synthetic shapes, etc.): can wait. Shape is off by default.
- T6 (sample_diverse duplicates, prune_parts on whole_image parts, confirm_lens domain, TOKEN_RE; savepoint test, no sweeper for stuck pending): can wait.
- T7 (PATCH bool → 500, stuck processing, disable-without-row, private calls, stale-frame merge, test, publish outside after_commit): can wait. Stuck `processing` after a Space restart needs unlock to retry anyway.
- T8 (no first SSE event, version race, debounce race, raw counts, layering, AppError → None, sync DB in SSE, missing tests): can wait. The SSE threadpool problem is new and listed as Important #3.
- T9 (combined excluded count, exception message; near-duplicate seed items twice, seed materialises domain, stale report): can wait.
- T10 (ordinal nudge direction untested, scale.index ValueError, error keys, check order, type: ignore, RED evidence): can wait.
- T11 (fallback AttrValues lack Lab; colour avoid and duplicate-of-excluded untested; invalid_unindexed domain None; reformat): can wait. The orchestrator always passes source attrs.
- T12 (number-nudge/ordinal-less untested, number nudge reliability, centroid blend test, avoid-empty → 1, cfg default; format churn): can wait. The nudge reliability was fixed in T13, but see Critical #1 for `compare()`.
- T13 (seg downgrade overwrote fail): fixed in T24.
- T13 (NaN confidence passes; duplicate answer rows): can wait, but cheap. See Minor #11.
- T13 (private `_part_mask`, mislabelled fallback crop, missing tests): can wait.
- T14 (stale-mark race): **fix-before-deploy** (Important #4).
- T14 (idempotency key → missing run, vacuous test, no 404 test, failed-summary per GET, suite time): can wait.
- T15 (vacuous dedupe test, image files before row, `_publish_updated` order, test helper): can wait. `_check_args` now uses `is not None`.
- T15b (missing skip tests, conditional assertion, grammar): can wait.
- T16 (fetchImageB64, apiBase vs host_permissions, last_used_at): can wait.
- T16 (re-mint resets guess budget): can wait for the Space, because pair-code needs unlock in DEMO_MODE. It must be fixed before any non-demo exposure.
- T16 (format test, reflows): can wait.
- T17 (LinkCard stroke on a text card, parse_status-only patch, shortcuts in dialogs, 589 kB bundle, lens review unseen live; test spies, empty-branch guard, fontStyle): can wait.
- T18 (TextEditor debounce, Compare relative to first, strip divider, hex from reason text, toolbar after Remove, 6 s polling; dialog pointer focus, popover Tab test): can wait.
- T18b (first-keep placement, overlap test scope, mock junk lens with truth map): can wait.
- T19 (`_Windows` never prunes, in-memory reset): can wait.
- T19 (`is_https` first hop): can wait.
- T19 (Docker image never built): **fix-before-deploy**. Build and run it once, including the SigLIP download and a live Vary.
- T19 (hf-cli flags unverified): verify while deploying.
- T20 (`--yes` flag doc, Commons logos/banners): can wait. Quality only.
- T20 (credit lines not on the canvas): **fix-before-deploy** (Important #5, licence compliance).
- T21 (`_download` follows redirects without re-check): **fix-before-deploy** (Important #6).
- T21 (private import, sha-duplicate re-download, "found N" timing, LIVE_QUERY_COUNT, identical run searches, palette_json unused): can wait.
- T20 follow-up (docstring/paren layout, reflow): can wait.
- T21 follow-up (executor join at exit, dropped count off by one, pending counter, votes.py read, strip downloaded count): can wait.
- Merge (vacuous commit test, stale store object, lost counter-signal e2e assertions, VaryPanel indentation/cast, single it-loop, O(n²) `.npy` rewrite): can wait.
- Merge follow-up (brittle commit-count test, re-index flush/commit overwrite): can wait.
- T22 (BoardPage keydown untested, alive-guard test, comment; stacked-dialog unmount tests): can wait.
- T24 (items parsed before pruning keep v1 measurements, `_part_mask` commit comment, partial mask rows): can wait.
- T24 (text-kind fail → verify): can wait. Unreachable today; one-line guard in Minor #12.
- T24 (prune re-enqueued every run): can wait. The mask cache makes repeats cheap, and the interior board stays under MIN_PRUNE_IMAGES.

## Declined to judge

- **Anonymous canvas moves and keep/reject on the shared demo boards:** an explicit user decision (2026-10-27 01:07). Only the side effect is noted, as Minor #17.
- **`/pair-code` open without DEMO_MODE:** a controller ruling plus the documented "No accounts" limitation for local single-user use.
- **Default protected set (signals plus confirmed attributes, the rest proposed):** a controller ruling (T20/T23) that reads the spec's "propose" as shown chips. It is a product call.
- **Ranking weights, ΔE/tolerance thresholds and shape constants:** the spec says they are not validated weights. Calibration is out of scope.
- **Whole-image fallback when SAM cannot find a part:** a controller ruling (T24) consistent with "SAM is localisation, not proof". The no-upgrade rule holds.
- **Live search sources failing from the build machine (AIC/Met 403, Smithsonian/Openverse timeouts):** environment, not code.
- **Mock values being arbitrary:** documented, and the UI labels mock-provider values.
- **In-process jobs and a single worker:** documented architecture limitation.
- **Rate-limit state lost on restart:** documented. The global cap still bounds a day.
- **Extension unusable against the Space:** documented as a local tool (host permission is localhost only).
- **The real-corpus thinness (interior has 2 items):** a user decision to stop indexing. Live search covers it at run time.
- **FastAPI 0.162 yield-dependency commit timing relative to the response:** not verified against that version's semantics. No observed defect.

## Recommendations

1. Fix Critical #1 and Important #2–#8, then build the Docker image locally and do one live smoke run with DEMO_MODE on before pushing the Space: unlock, an anonymous Vary, a keep, then vary the kept item, and 45 SSE connections.
2. After deploy, log `client_ip` for one request to confirm `DEMO_PROXY_HOPS`.
3. In DEMO_MODE, consider turning `deepen_item` off and adding a nightly reset of the demo boards from the baked snapshot.
4. Add regression tests:
   - number compare with low confidence
   - keep followed by Vary on the kept item
   - a queued run not marked stale
   - verify duplicate rows not flipping a result
   - board item payload carrying licence and credit

## Assessment

**Ready to merge?** With fixes

**Reasoning:** The architecture, demo guard, SSRF guard and validator invariants are careful and well tested. But the number comparator breaks the core "no pass without reliable evidence" promise. Kept items cannot be varied. And the public deploy has an easy threadpool DoS, false run interruptions under load, missing CC attribution on displayed images, and a README deploy step that deletes the real corpus. All of these are small, targeted fixes.
