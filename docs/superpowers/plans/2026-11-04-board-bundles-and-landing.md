# Board Bundles and Landing Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move a finished board (items, images, analyses, explorations, output, agent runs and steps) from this machine into the deployed app as one bundle file, and give the public demo a landing page that links to each board's replay and embeds the video.

**Architecture:** A bundle is a zip of a manifest, one JSON file of rows per table, and the board's content-addressed files. Export and import are a backend module run from the command line on both machines (no new public write endpoint). Rows keep their ids, so every id held inside JSON columns (step `item_ids`, output `note_ids`, `generation_json`) stays valid. The landing page is a frontend route fed by a small showcase file; in demo mode it is `/`, and the board list moves to `/boards` in both modes.

**Tech Stack:** Python 3.12, SQLAlchemy, SQLite, Alembic, pytest (`uv run pytest`), ruff, mypy; React 19 + TypeScript, Vitest (`npm test`), oxlint.

**Spec:** `docs/superpowers/specs/2026-11-03-board-agent-design.md` §8 "Landing page" (bundle contents; visitors with the board locked can watch the replay and look around, nothing more; the landing page links to each board's replay and embeds the video; deployment is the person's to do).

## Global Constraints

- Bundle contents (spec): items, images, analyses, explorations, output, agent runs and steps — exported locally and imported into the deployed app.
- Locked visitors can watch the replay and look around, and nothing more: they can't toggle highlights, start a Muse agent run, or reach MCP. (Already enforced: `app/demo.py` blocks every write but item position PATCHes; MCP is localhost-only. This plan must not open any new write.)
- `backend/app/` must never contain the words watch, fashion, interior, dial, sofa (a test enforces this). Board-specific copy lives only in the frontend showcase file.
- No new public HTTP write endpoint: bundles move by CLI on each machine.
- Deployment (`fly deploy`, uploading the bundle) is the person's to run; the plan writes the steps down, it does not run them.
- Work on branch `feat/board-bundles` in a worktree.

## Rulings (made while planning; the person can overturn)

- **What a bundle carries:** `boards`, `board_items` (removed ones too: steps refer to them), `item_frames`, `item_attributes`, `item_parts`, `attribute_events`, `explorations`, `explore_options`, `lenses` (the board's own rows plus the one `boards.lens_id` points at), `board_profiles`, `agent_runs`, `agent_steps`; and every file named by a `storage_path`, `thumb_path` or `mask_path` in those rows. Left out, and listed in the manifest's `left_out`: Vary runs and their candidates and decisions, plugin nodes and runs, UI events.
- **Licensed corpus items:** a board with any `corpus_item_id` set refuses to export (`BOARD_HAS_LICENSED_ITEMS`): the corpus is a separate catalogue and the four demo boards have none.
- **Same schema only:** import refuses a bundle whose Alembic head differs from the app's (`SCHEMA_MISMATCH`). Deploy the code first, then import.
- **Re-import:** an existing board id refuses (`BOARD_EXISTS`) unless `--replace`, which deletes that board's rows (the same tables, same scope) in the same transaction before inserting. Files are content-addressed and never deleted.
- **Showcase:** a typed file in the frontend (`frontend/src/landing/showcase.ts`): board id, the run to replay, a cover item id, a title and one line each, and `videoUrl` (null until the video exists). Ids survive import, so the file is the same locally and deployed.

## Review Focus

1. Importing the same bundle twice: `BOARD_EXISTS`, nothing written; with `--replace`: exactly one copy of every row, no orphans. → Task 2 tests `refuses a board that is already here` and `replace leaves one copy`.
2. A bundle from another schema head: refused before any row or file is written. → Task 2 test `refuses another schema`.
3. A hostile or broken zip — a member path with `..` or absolute, a member outside `uploads/`, `thumbs/`, `masks/`, `frames/`, a row naming a file the bundle lacks, a member over 50 MB: refused, no rows written. → Task 2 test `refuses unsafe or incomplete bundles` (parametrised).
4. Items that point at other items (`parent_item_id`, `put_source_item_id`) and options that point at options (`parent_option_id`), in any row order: import succeeds with foreign keys on. → Task 1 test `orders rows so references come first`, Task 2 test `imports a board with item and option chains`.
5. The landing page on a server that lacks some showcase boards: their cards are left out; with none present it says `The demo boards are not on this server yet.`; outside demo mode `/` is still the board list. → Task 4 tests.

---

### Task 1: Export a board to a bundle

**Files:**
- Create: `backend/app/bundle/__init__.py`, `backend/app/bundle/scope.py`, `backend/app/bundle/export.py`
- Test: `backend/tests/integration/bundle/test_export.py`

**Interfaces:**
- Produces:
  - `scope.py`: `FORMAT = "muse-board/1"`; `FILE_DIRS = ("uploads/", "thumbs/", "masks/", "frames/")`; `LEFT_OUT = ("variation_runs", "run_candidates", "validation_results", "decisions", "plugin_nodes", "plugin_runs", "board_plugins", "ui_events")`; `board_rows(session, board_id) -> dict[str, list[dict[str, Any]]]` — table name → rows as column dicts, for the tables in the Rulings, in insert order (`TABLE_ORDER: tuple[str, ...]`), each table's rows ordered so a row's same-table reference (`parent_item_id`, `put_source_item_id`, `parent_option_id`) comes before it; `file_paths(rows) -> list[str]` — every non-null `storage_path` / `thumb_path` / `mask_path`, deduplicated, sorted.
  - `export.py`: `class BundleError(Exception)` with `code: str`; `export_board(session, board_id: str, out: Path) -> dict[str, Any]` — writes the zip, returns the manifest.
  - Zip layout: `manifest.json` = `{"format", "schema_head", "board_id", "title", "exported_at", "counts": {table: n}, "files": n, "left_out": [tables with rows for this board]}`; `rows/<table>.json` (a JSON list); `files/<relative path>`.
- Consumes: `app.db.models`, `app.storage.files.abs_path`, the Alembic head via `app.db.session.alembic_config` (`ScriptDirectory.from_config(cfg).get_current_head()`).

- [ ] **Step 1: Write the failing tests** (build a board through the API with the `client` fixture: two images, a note, an item whose `parent_item_id` and `put_source_item_id` point at the first image, an exploration with a parent and child option, an agent run with two steps; then call `export_board` with a session from `deps._factory()()`):

```python
def test_exports_the_board_and_its_files(tmp_path, built_board):
    m = export_board(session, built_board.id, tmp_path / "b.zip")
    z = zipfile.ZipFile(tmp_path / "b.zip")
    assert m["format"] == "muse-board/1" and m["board_id"] == built_board.id
    assert m["counts"]["board_items"] == 4 and m["counts"]["agent_steps"] == 2
    rows = {t: json.loads(z.read(f"rows/{t}.json")) for t in TABLE_ORDER if f"rows/{t}.json" in z.namelist()}
    assert file_paths(rows)  # the two images name originals and thumbs
    assert all(f"files/{rel}" in z.namelist() for rel in file_paths(rows))

def test_orders_rows_so_references_come_first(...):
    # shuffle created_at so the chained item sorts first by time; exported board_items list still has
    # each referenced id before the row that references it; same for explore_options.parent_option_id

def test_lists_what_it_leaves_out(...):
    # a Vary run on the board → "variation_runs" in manifest["left_out"]; no rows/variation_runs.json

def test_refuses_a_board_with_licensed_items(...):
    # an item with corpus_item_id set → BundleError code "BOARD_HAS_LICENSED_ITEMS"; no file written

def test_unknown_board(...):  # → BundleError "BOARD_NOT_FOUND"
```

- [ ] **Step 2: Run** `uv run pytest tests/integration/bundle/test_export.py -q` — expect FAIL (no module).
- [ ] **Step 3: Implement.** Rows: `{c.name: getattr(row, c.key) for c in Model.__table__.columns}`; JSON columns serialise as they are. Same-table ordering is a topological sort by id (stable on `created_at`).
- [ ] **Step 4: Run** the tests — expect PASS; then `uv run ruff check app tests && uv run mypy app/bundle`.
- [ ] **Step 5: Commit** `feat(bundle): export a board with its files`

---

### Task 2: Import a bundle

**Files:**
- Create: `backend/app/bundle/importer.py`
- Test: `backend/tests/integration/bundle/test_import.py`

**Interfaces:**
- Consumes: Task 1 (`FORMAT`, `FILE_DIRS`, `TABLE_ORDER`, `file_paths`, `BundleError`, `export_board`, `board_rows`).
- Produces: `import_board(session, bundle: Path, *, replace: bool = False) -> dict[str, Any]` — returns the manifest; commits nothing itself (the CLI commits).

Order of work, all checks before any write: open the zip; read the manifest (`BAD_BUNDLE` if missing or `format` differs); compare `schema_head` (`SCHEMA_MISMATCH`); check every member name (`UNSAFE_PATH` for absolute, `..`, or anything outside `manifest.json`, `rows/`, `files/` + `FILE_DIRS`) and size (`FILE_TOO_LARGE` over 50 MB); every path named by the rows is present under `files/` (`MISSING_FILE`); board id not present unless `replace` (`BOARD_EXISTS`). Then write files that do not exist yet under `DATA_DIR` (atomically, as `storage/files.py` does); then, if `replace`, delete the board's existing rows in reverse `TABLE_ORDER`; then insert rows in `TABLE_ORDER` with `session.execute(Model.__table__.insert(), rows)`.

- [ ] **Step 1: Write the failing tests** (export the Task 1 board, then import into a second, empty app: a fresh `DATA_DIR` and database via a fixture that builds a second engine with `run_migrations`):

```python
def test_imports_a_board_with_item_and_option_chains(...):
    # every exported row is in the new database with the same id; GET /api/boards/{id}/items on the
    # second app lists the same item ids; /api/items/{id}/image returns the same bytes

def test_refuses_a_board_that_is_already_here(...):
    # import twice → BundleError "BOARD_EXISTS"; row counts unchanged

def test_replace_leaves_one_copy(...):
    # import, then import again with replace=True → counts equal the manifest's counts exactly

def test_refuses_another_schema(...):
    # rewrite manifest schema_head="0000_other" → "SCHEMA_MISMATCH"; no rows, no files written

@pytest.mark.parametrize("member,code", [
    ("files/../evil.txt", "UNSAFE_PATH"), ("/etc/x", "UNSAFE_PATH"),
    ("files/config/x.png", "UNSAFE_PATH"), (None, "MISSING_FILE"),  # None: drop one thumbs/ member
])
def test_refuses_unsafe_or_incomplete_bundles(member, code, ...):
    # → BundleError(code); the second database has no boards
```

- [ ] **Step 2: Run** `uv run pytest tests/integration/bundle -q` — expect the new tests to FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the bundle tests, then the whole backend suite `uv run pytest -q` (the word-list test included), ruff and mypy — expect PASS.
- [ ] **Step 5: Commit** `feat(bundle): import a board bundle, refusing anything unsafe`

---

### Task 3: The command line and the deploy steps

**Files:**
- Create: `backend/app/bundle/__main__.py`, `docs/demo/board-bundles.md`
- Modify: `Makefile` (two targets)
- Test: `backend/tests/integration/bundle/test_cli.py`

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces:
  - `python -m app.bundle export <board_id> <out.zip>` and `python -m app.bundle import <bundle.zip> [--replace]` (argparse). Both use the app's own engine (`app.db.session`) and settings. On success they print one line: `exported <title> (<board_id>): <n> rows, <m> files -> <path>` / `imported <title> (<board_id>): <n> rows, <m> new files`; on `BundleError` they print `error <CODE>: <message>` to stderr and exit 1.
  - `make board-export BOARD=<id> OUT=<path>` and `make board-import FILE=<path> [REPLACE=1]`.
  - `docs/demo/board-bundles.md`: export the four boards (ids from `reports/demo/*/run.json`); deploy the code first (`fly deploy --ha=false`; the entrypoint migrates); `fly sftp shell` → `put` each zip into `/data/bundles/`; `fly ssh console -C "uv run python -m app.bundle import /data/bundles/<file>.zip"`; check the landing page; take a volume snapshot first (`fly volumes snapshots create <vol>`). Written as steps for the person.

- [ ] **Step 1: Write the failing test** (`subprocess.run([sys.executable, "-m", "app.bundle", ...], env={DATABASE_URL, DATA_DIR pointing at tmp})`): export then import into another tmp `DATA_DIR`/database prints the two lines and exits 0; importing again exits 1 with `error BOARD_EXISTS:` on stderr.
- [ ] **Step 2: Run** `uv run pytest tests/integration/bundle/test_cli.py -q` — expect FAIL.
- [ ] **Step 3: Implement** the CLI, the Makefile targets and the doc.
- [ ] **Step 4: Run** the test — expect PASS; `uv run ruff check app tests`.
- [ ] **Step 5: Commit** `feat(bundle): export and import from the command line; deploy steps`

---

### Task 4: The landing page

**Files:**
- Create: `frontend/src/landing/showcase.ts`, `frontend/src/landing/LandingPage.tsx`, `frontend/src/landing/landing.css`
- Modify: `frontend/src/router.ts` (routes), `frontend/src/App.tsx`, links that point at `/` as "All boards" (`pages/BoardPage.tsx`, `App.tsx`'s not-found)
- Test: `frontend/src/landing/LandingPage.test.tsx`, `frontend/src/router.test.ts`

**Interfaces:**
- Consumes: `useDemo()` (`demoMode`) from `../demo`; `getBoards` / the boards query; `/api/items/{id}/image?size=thumb`.
- Produces:
  - `showcase.ts`: `interface ShowcaseBoard { boardId: string; runId: string; coverItemId: string; title: string; line: string }`; `export const SHOWCASE: { videoUrl: string | null; boards: ShowcaseBoard[] }` with the four boards in this order — car, UI, interior, fashion — using the ids below; cover items: each board's finished output image (pick from the board's output sheet in `reports/demo/<slug>/run.json` → `output.sections[*].items[0]`).
    - car `brd_01m6h989kz0tz8xjvjbp6zbz9x`, run `arun_01m6h991xyrzxq1xyvhrag2pqk`; UI `brd_01m6hcp4q8vrt11mnpw6jrmpb4`, run `arun_01m6hcpsxzz7fx878hx8fhsn7n`; interior `brd_01m6j4rrnz1zzx6qax1rya3j27`, run `arun_01m6j4sg80tqra73g2y11dvnx9`; fashion `brd_01m6j5n5eqdmxv33zhw03qesx5`, run `arun_01m6j5npnz586e22mbk8vrxat4`.
    - Titles and lines: `A new EV coupe` / `Vary one thing, keep the rest: views, a drifted wheel put back, three colourways.`; `What "premium" means` / `The board pins a vague word to named dimensions, then designs three screens in it.`; `One room, four materials` / `A Japandi room held still while only material and palette change.`; `A capsule over two sessions` / `Five looks that stay in one range, and a look reproduced in a second colour.`
  - Routes: `matchRoute('/')` → `{ name: 'home' }`; `matchRoute('/boards')` → `{ name: 'boards' }`; `/boards/:id` unchanged. `App`: `home` renders `LandingPage` when `demoMode`, else `BoardsPage`; `boards` renders `BoardsPage`. "All boards" links go to `/boards`.
  - `LandingPage`: `<h1>Muse</h1>`; the problem in two short paragraphs, from the spec's Why (Problem 1 and Problem 2, plain words, under 60 words together); the video as `<video controls src={videoUrl}>` only when `videoUrl` is set; one card per showcase board that the boards query lists: the cover image, title, line, a `Show me how` link to `/boards/{boardId}?replay={runId}` and a `Look around` link to `/boards/{boardId}`; `All boards` link to `/boards`. With none present: `The demo boards are not on this server yet.`
- [ ] **Step 1: Write the failing tests**

```ts
it('links each present board to its replay', () => {
  // boards query returns the car and UI boards only
  // two cards; "Show me how" hrefs are /boards/brd_01m6h989kz0tz8xjvjbp6zbz9x?replay=arun_01m6h991xyrzxq1xyvhrag2pqk and the UI one
})
it('leaves out boards this server lacks and says so when none are here', () => { /* [] → the message */ })
it('embeds the video only when there is one', () => { /* videoUrl null → no <video>; set → <video src> */ })
// router.test.ts
it('routes / to home and /boards to the list', () => {
  expect(matchRoute('/')).toEqual({ name: 'home' })
  expect(matchRoute('/boards')).toEqual({ name: 'boards' })
})
// App: outside demo mode, / renders the board list (existing BoardsPage heading)
```

- [ ] **Step 2: Run** `npx vitest run src/landing src/router.test.ts` — expect FAIL.
- [ ] **Step 3: Implement.** `backend/app/spa.py` already falls back to `index.html` for any non-file path, so `/boards` needs no backend change.
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build` — expect green.
- [ ] **Step 5: Commit** `feat(landing): the public landing page with each board's replay`

---

### Task 5: Round trip on this machine

No new code unless something fails. Export the four boards with `make board-export`; start a second backend on port 8100 with a fresh `DATA_DIR` and database under the scratchpad, `DEMO_MODE=1` and a test passcode and secret, serving the built frontend; import the four bundles; then, in a browser at that port: the landing page shows four cards with their covers; each `Show me how` plays its replay to the end; locked, the star is hidden and dragging an item works; `PATCH /api/agent-steps/<id>` with `{"highlight": true}` returns the locked error. Write the results, one line per board, in the task report. Delete the scratch data afterwards. The person's backend on :8000 and Vite on :5173 are not touched.
