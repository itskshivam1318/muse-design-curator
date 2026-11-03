# Board agent part 2: render_view, put_into for the agent, and the recording kit

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** the agent can make the same design from another viewpoint (`render_view`) and put one picture into another (`put_into`), getting the new picture's id back in the same call; and each demo board can be run by Claude Code and recorded with its steps saved.

**Architecture:** `render_view` is a new job beside put-into (`backend/app/views/`): one whole-image Muse Image edit of an anchor picture with a view prompt, the result added as a generated child of the anchor. Both agent tools queue through the REST API and then await the board's own done/failed event for their job id (subscribed before the request, so a synchronous job is not missed). Recording is a Playwright script that films the board at 1920×1080 until the board's latest agent run stops, then saves the run and its steps.

**Tech Stack:** FastAPI, SQLAlchemy, in-process jobs and events (`app/jobs.py`, `app/events.py`), Pillow, pytest; Playwright (already in `frontend/node_modules`).

**Spec:** `docs/superpowers/specs/2026-11-03-board-agent-design.md` (§1 `render_view`, `put_into`; §6 the four boards; §9 the video). Part 1 plan: `docs/superpowers/plans/2026-11-03-board-agent-tools-mcp.md`.

## Global Constraints

- Image model: Muse Image only (the person's decision, 2026-11-03), through `get_image_provider(get_settings())`; no new provider, no new key.
- `backend/app/` stays domain-agnostic: `tests/.../test_domain_agnostic` forbids `watch`, `fashion`, `interior`, `dial`, `sofa` anywhere under `backend/app/` (prompts, docstrings, tool descriptions included). Say "inside", not the forbidden word.
- A render costs one `limits.check_and_count(board_id, "render")`; any failure after counting refunds it (`limits.refund`), as put-into does.
- Tools call the app over its own REST API in-process (`ctx.api`), never services directly; a refusal is `{"error": CODE, "message": ...}`, never an exception.
- Every new route is a write and stays behind the existing demo lock like other POSTs (no new code needed if it lives under `/api` like `put.py`; the test proves it).
- Migration head stays `0011_board_agent`; this plan adds no table or column.
- Python style as in `app/put/service.py`: `# fmt: skip` on long call lines, module docstring saying what the job does and how it fails.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **The job finishes before the tool starts listening.** Under `JOBS_SYNC=1` (and on a fast mock) the job runs inside the POST; the tool must subscribe to the board's events before posting, or it times out on a picture that already exists. Test: Task 2 `test_render_view_tool_returns_item_with_sync_jobs`.
2. **The anchor is removed while the view renders.** The job must fail as `view.failed` with the render refunded, not crash or add an orphan. Test: Task 1 `test_view_of_removed_anchor_fails_and_refunds`.
3. **A note or a staged item as the anchor.** A refusal `422 VIEW_NOT_IMAGE` with no render counted. Test: Task 1 `test_view_refuses_note_and_costs_no_render`.
4. **A slow real render.** Muse Image takes 20–30 s per view; the tool's default wait (90 s) must cover it, and a timeout must hand back the job id so `wait(kind="job")` can pick it up. Test: Task 2 `test_wait_job_finds_the_result_later`.
5. **Two views at once of the same anchor.** Each lands in its own free slot and each tool call gets its own item (job ids match, not "newest child"). Test: Task 2 `test_two_views_each_get_their_own_item`.

---

### Task 1: render_view job and route

**Files:**
- Create: `backend/app/views/__init__.py` (empty), `backend/app/views/service.py`, `backend/app/api/views.py`
- Modify: `backend/app/main.py` (include the router as `put.py`'s is included), `backend/app/put/service.py` (`_stamped` gains a `key` parameter, default `"muse:put"`)
- Test: `backend/tests/integration/api/test_render_view.py`

**Interfaces:**
- Consumes: `app.extraction.service._require_item, _image_for`; `app.put.service._name, _open, _png, _stamped`; `app.analysis.extract.Bounds, free_slot`; `app.ingest.common.ItemMeta, create_item, default_size`; `app.analysis.limits`.
- Produces:
  - `POST /api/items/{anchor_id}/render-view`, body `{"view": str (1–120 chars, stripped), "words": str | null (≤200)}` → `202 {"job_id": "view_<hex>", "x", "y", "w", "h"}`.
  - Events on the anchor's board: `item.added` (the new item), then `view.done {"job_id", "item_id"}`; on failure `view.failed {"job_id", "code", "message"}`.
  - The new item: `kind="image"`, `origin="generated"`, `rights_status="generated"`, `parent_item_id=anchor.id`, `original_filename=f"{_name(anchor)}, {view}.png"`, `generation_json={"model", "prompt", "view", "view_job": job_id}`, PNG stamped with key `"muse:view"`.
  - `view_prompt(view: str, words: str | None) -> str` in `app/views/service.py`.

- [ ] **Step 1: Write the failing tests** (mock image provider, `JOBS_SYNC=1`, existing fixtures from `tests/integration/api/test_put_into.py` for a board with two images):

```python
def test_render_view_adds_a_child_of_the_anchor(client, board_with_image):
    anchor = board_with_image.image_id
    r = client.post(f"/api/items/{anchor}/render-view", json={"view": "from the rear right"})
    assert r.status_code == 202 and r.json()["job_id"].startswith("view_")
    made = [i for i in items_of(client, board_with_image.id) if i["parent_item_id"] == anchor]
    assert len(made) == 1
    assert made[0]["origin"] == "generated"
    assert made[0]["generation"]["view"] == "from the rear right"
    assert made[0]["generation"]["view_job"] == r.json()["job_id"]
    assert made[0]["original_filename"].endswith(", from the rear right.png")

def test_render_view_publishes_done(client, board_with_image):  # subscribe before posting
    with events.subscribe(board_with_image.id) as sub:
        job = client.post(f"/api/items/{board_with_image.image_id}/render-view",
                          json={"view": "from the front left"}).json()["job_id"]
        seen = drain(sub)
    done = [e for e in seen if e["type"] == "view.done"]
    assert done and done[0]["data"]["job_id"] == job and done[0]["data"]["item_id"]

def test_view_prompt_keeps_the_design_and_adds_words():
    p = view_prompt("seen from inside, from the open door", "plain studio background")
    assert "seen from inside, from the open door" in p
    assert "same shape, proportions, colours, materials and details" in p
    assert p.endswith("plain studio background.")
    assert not view_prompt("from above", None).endswith(" .")

def test_view_refuses_note_and_costs_no_render(client, board_with_note):
    r = client.post(f"/api/items/{board_with_note.note_id}/render-view", json={"view": "from above"})
    assert r.status_code == 422 and r.json()["code"] == "VIEW_NOT_IMAGE"
    assert render_count(board_with_note.id) == 0

def test_view_rejects_empty_and_long_view(client, board_with_image):
    url = f"/api/items/{board_with_image.image_id}/render-view"
    assert client.post(url, json={"view": "  "}).status_code == 422
    assert client.post(url, json={"view": "x" * 121}).status_code == 422

def test_view_of_removed_anchor_fails_and_refunds(board_with_image, session):
    # call the job function directly after removing the anchor
    remove(board_with_image.image_id)
    with events.subscribe(board_with_image.id) as sub:
        render_view_job("view_x", board_with_image.image_id, "from above", None, 0, 0)
        seen = drain(sub)
    assert [e["data"]["code"] for e in seen if e["type"] == "view.failed"] == ["ITEM_NOT_FOUND"]
    assert render_count(board_with_image.id) == 0   # counted by the request, refunded here

def test_view_is_demo_locked(locked_client, board_with_image):
    r = locked_client.post(f"/api/items/{board_with_image.image_id}/render-view",
                           json={"view": "from above"})
    assert r.status_code in (401, 403)  # whatever the lock answers other POSTs with
```

Helpers `items_of`, `drain`, `render_count`, `remove`, `locked_client` reuse what `test_put_into.py` and the demo-lock tests already use; add to the test file only what does not exist.

- [ ] **Step 2: Run them to see them fail**

Run: `cd backend && uv run pytest tests/integration/api/test_render_view.py -q`
Expected: FAIL (404 on the route / import error).

- [ ] **Step 3: Implement** `app/views/service.py` on the pattern of `app/put/service.py`:
  - `request_render_view(session, anchor_id, view, words) -> dict`: anchor must be live, `kind == "image"`, have `storage_path`, not `staged`, else `AppError(422, "VIEW_NOT_IMAGE", "Only a picture can be seen from another view")` (unknown id → the existing 404 from `_require_item`); count the render; free slot near the anchor sized `default_size(anchor.width, anchor.height)` (refund and re-raise on failure); enqueue job `"render_view"` after commit; return `{"job_id", "x", "y", "w", "h"}`.
  - `view_prompt` (exact copy, the spec of the words the model sees):

```python
VIEW_PROMPT = (
    "Show this same design, {view}. It must read as the very same one: the same shape, "
    "proportions, colours, materials and details, in the same design language. Photo-real."
)

def view_prompt(view: str, words: str | None) -> str:
    prompt = VIEW_PROMPT.format(view=view.strip())
    extra = (words or "").strip().rstrip(".")
    return f"{prompt} {extra}." if extra else prompt
```

  - `render_view(session, job_id, anchor_id, view, words, x, y)`: re-check the anchor (as `_pictures` does), `provider.edit(image_bytes, view_prompt(view, words))` on the whole picture (no mask, no composite), ingest as in `put.service._ingest` with the Produces fields, publish `item.added` then `view.done` after commit. `ModelError`/`AppError` → rollback, refund, `view.failed`; any other exception in `render_view_job` → `VIEW_ERROR`, "Could not make this view". Register with `jobs.register("render_view", render_view_job)`.
  - `app/api/views.py`: `RenderViewBody(view: str = Field(min_length=1, max_length=120), words: str | None = Field(None, max_length=200))` with a validator that strips `view` and rejects blank; route as Produces.

- [ ] **Step 4: Run the tests and the put-into tests**

Run: `cd backend && uv run pytest tests/integration/api/test_render_view.py tests/integration/api/test_put_into.py -q && uv run ruff check app tests && uv run mypy app`
Expected: PASS, no lint or type errors.

- [ ] **Step 5: Commit**

```bash
git add backend/app/views backend/app/api/views.py backend/app/main.py backend/app/put/service.py backend/tests/integration/api/test_render_view.py
git commit -m "feat(views): render the same design from another viewpoint"
```

---

### Task 2: agent tools render_view and put_into, and wait for a job

**Files:**
- Create: `backend/app/agent/tools/render_view.py`, `backend/app/agent/tools/put_into.py`
- Modify: `backend/app/agent/context.py` (add `queue_and_wait`), `backend/app/agent/tools/__init__.py` (`_MODULES`), `backend/app/agent/tools/wait.py` (kind `job`), `README.md` (MCP section: the two tools in the tool list, one line each)
- Test: `backend/tests/integration/agent/test_view_tools.py`

**Interfaces:**
- Consumes: Task 1's route and events; put-into's `POST /api/items/{target_id}/put-into` (`{"source_id", "spots": [{"part": key} | {"point": {"fx", "fy"}}], "words"}`) and its `put.done {"job_id","item_id"}` / `put.failed {"job_id","code","message"}`; `app.events.subscribe_async`; part 1's `require_item`, `api_error`, `board_items`.
- Produces:
  - `async def queue_and_wait(ctx: ToolContext, path: str, body: dict, done: str, failed: str, timeout_s: float) -> dict` in `context.py`: subscribes to `ctx.board_id` with `subscribe_async` **before** posting, posts, and on a non-202 returns `api_error`; then awaits events whose `data.job_id` matches until `done` → `{"job_id", "item_id", "item_ids": [item_id]}`, `failed` → `{"error": code, "message": message, "job_id"}`, or the timeout → `{"job_id", "timed_out": True, "hint": "wait(kind='job', id=job_id)"}`. Always closes the subscription.
  - Tool `render_view(anchor_id, view, words?, timeout_s=90)`. Its description says what view text works ("from the front left at three-quarters", "from the rear", "seen from inside, from the open door"), that the result is a new picture beside the anchor, and that it keeps the design but may drift in small details, which the agent should check with its own eyes or with `finish`.
  - Tool `put_into(target_id, source_id, spots, words?, timeout_s=90)`. Its description says spots are part keys from `get_analysis` or points as fractions, at most 8.
  - `wait(kind="job", id=job_id)`: done when an item on the board has `generation.view_job == id` or `generation.put_job == id` → `{"state": "done", "result": {"item_id", "check"}}` plus `item_ids`. Until then busy; a failed job is not detectable here and reads as a timeout (the tool's own call already returned the failure).
  - Both tools clamp `timeout_s` with `wait.clamp_timeout`, with a default of 90.

- [ ] **Step 1: Write the failing tests** (mock providers, `JOBS_SYNC=1`, a `ToolContext` on a board with two analysed images, as the part 1 agent tests build it):

```python
async def test_render_view_tool_returns_item_with_sync_jobs(ctx, anchor_id):
    res = await run_tool(ctx, "render_view", {"anchor_id": anchor_id, "view": "from the rear"})
    assert "error" not in res and res["item_ids"] == [res["item_id"]]
    item = await require_item(ctx, res["item_id"])
    assert item["parent_item_id"] == anchor_id

async def test_two_views_each_get_their_own_item(ctx, anchor_id):
    a, b = await asyncio.gather(
        run_tool(ctx, "render_view", {"anchor_id": anchor_id, "view": "from the rear"}),
        run_tool(ctx, "render_view", {"anchor_id": anchor_id, "view": "from above"}),
    )
    assert a["item_id"] != b["item_id"] and a["job_id"] != b["job_id"]

async def test_render_view_tool_refuses_a_note(ctx, note_id):
    res = await run_tool(ctx, "render_view", {"anchor_id": note_id, "view": "from above"})
    assert res["error"] == "VIEW_NOT_IMAGE"

async def test_render_view_failure_comes_back_as_refusal(ctx, anchor_id, monkeypatch):
    monkeypatch.setattr(MockImageProvider, "edit", raising_model_error)
    res = await run_tool(ctx, "render_view", {"anchor_id": anchor_id, "view": "from the rear"})
    assert res["error"] and res["job_id"].startswith("view_")

async def test_put_into_tool_with_a_point(ctx, target_id, source_id):
    res = await run_tool(ctx, "put_into", {"target_id": target_id, "source_id": source_id,
                                           "spots": [{"point": {"fx": 0.5, "fy": 0.5}}]})
    item = await require_item(ctx, res["item_id"])
    assert item["parent_item_id"] == target_id and item["put_source_item_id"] == source_id

async def test_put_into_tool_unknown_part(ctx, target_id, source_id):
    res = await run_tool(ctx, "put_into", {"target_id": target_id, "source_id": source_id,
                                           "spots": [{"part": "no_such_part"}]})
    assert res["error"] == "PART_NOT_FOUND"

async def test_wait_job_finds_the_result_later(ctx, anchor_id, monkeypatch):
    # timeout 0 forces the timed-out path even though the sync job has finished
    monkeypatch.setattr(context, "_await_job", fake_never_sees_event)  # or clamp min to 0 via the test seam you add
    res = await run_tool(ctx, "render_view", {"anchor_id": anchor_id, "view": "from the rear"})
    assert res["timed_out"] is True
    done = await run_tool(ctx, "wait", {"kind": "job", "id": res["job_id"], "timeout_s": 1})
    assert done["state"] == "done" and done["item_ids"] == [done["result"]["item_id"]]

def test_new_tools_are_listed_for_mcp_and_muse():
    names = {d["name"] for d in definitions("mcp")}
    assert {"render_view", "put_into"} <= names
    assert {"render_view", "put_into"} <= {d["name"] for d in definitions("muse")}
```

`test_wait_job_finds_the_result_later` needs a seam for "the event never arrives": split the event loop of `queue_and_wait` into a private `_await_job(sub, job_id, done, failed, timeout_s)` and patch that. Pick the seam; keep the assertion.

- [ ] **Step 2: Run them to see them fail**

Run: `cd backend && uv run pytest tests/integration/agent/test_view_tools.py -q`
Expected: FAIL (`render_view` not a tool).

- [ ] **Step 3: Implement** `queue_and_wait`, both tool modules (each checks its item ids with `require_item` first, so an id from another board is `ITEM_NOT_ON_BOARD` before anything is posted), the `job` probe in `wait.py` (add `"job"` to `KINDS`, mention it in the description), and the registry entries. Steps record as for every tool; `item_ids` makes the panel focus the new picture.

- [ ] **Step 4: Run the agent tests and the full backend suite**

Run: `cd backend && uv run pytest tests/integration/agent tests/unit -q && uv run ruff check app tests && uv run mypy app`
Expected: PASS (bar the known `test_siglip_features_unwrap_model_output`, no torch).

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent backend/tests/integration/agent/test_view_tools.py README.md
git commit -m "feat(agent): render_view and put_into tools that hand back the new picture"
```

---

### Task 3: recording kit and board briefs

**Files:**
- Create: `frontend/scripts/record-board.mjs`, `docs/demo/boards.md`, `reports/demo/.gitignore`
- Modify: `Makefile` (target `demo-record`)
- Test: `frontend/scripts/record-board.test.mjs` is not needed; the check is a dry run (Step 3).

**Interfaces:**
- Consumes: `GET /api/boards/{id}/agent-runs` (part 1; newest first, each with `status`), `GET /api/agent-runs/{id}` (run with `steps`), the board page at `${APP}/boards/{id}` (check the real route in `frontend/src` routing and use it).
- Produces:
  - `node frontend/scripts/record-board.mjs --board <board_id> --slug <car|ui|room|outerwear> [--app http://localhost:5173] [--api http://localhost:8000] [--max-min 60]`. It opens Chromium at 1920×1080 with `recordVideo` into `reports/demo/<slug>/`, loads the board, and polls the API every 5 s. It stops once the board has a run that started after recording began and whose status is `done`, `needs_input` or `paused`, holding 5 s longer so the finished board is on film, or at `--max-min`. It writes `reports/demo/<slug>/run.json` (the run with its steps) and `steps.md` (one line per step: number, time since start as `mm:ss`, tool, `say`, ok/refused, highlight star), so a snippet can be found by step in the video. It exits non-zero if the board does not load.
  - `make demo-record BOARD=<id> SLUG=<slug>` runs it.
  - `reports/demo/.gitignore` ignores `*.webm` (videos stay local; `run.json` and `steps.md` are committed with the boards).
  - `docs/demo/boards.md`: how to run a board (start `MCP_ENABLED=1 make dev`, `claude mcp add --transport http muse http://localhost:8000/mcp`, create the board, start `make demo-record`, paste the brief into Claude Code), then one brief per board for Claude Code to work from. The four briefs below are fixed text; put them in as written.

Briefs (exact, from spec §6 with the person's car goal):

```
Car: Work the Muse board "<id>" to a finished design. Goal: a new EV coupe that keeps the language of the references. Deliverables: exterior 3/4 front, exterior side, exterior rear, interior dashboard, interior seats, 3 exterior colourways, one shared design language. Gather 6–10 references (local folder <path> or Google Images via Chrome, keeping each source page). Read the board, propose a lens, analyse the anchor, explore one dimension at a time, render the other views from one anchor with render_view, and check them against each other; if a detail drifts between views (wheels, lamps), fix it with put_into from the view that has it right. Colourways come from exploring colour, not the colour plugin. Narrate every call with say, mark the 5–8 moments that best show how with highlight, then compose_output and finish.

UI: Work the Muse board "<id>". Goal: a fintech app screen set that is "more premium", where the board pins "premium" to named dimensions and values. Deliverables: the premium vocabulary as a note naming the dimensions and their values, 3 screens (home, card detail, payment confirmation) in that vocabulary, and one "not this" example. Same working rules: say on every call, highlight the moments that show how, compose_output, finish.

Interior: Work the Muse board "<id>". Goal: a Japandi living room; keep the room and vary only material and palette. Deliverables: the anchor room, 3 finished variations that change only material and palette, and a note saying what stayed fixed. Same working rules.

Fashion (session 1): Work the Muse board "<id>". Goal: an autumn outerwear capsule. Deliverables: 3 looks in range and a note naming the range. Same working rules.
Fashion (session 2, a later run on the same board): Goal: extend the capsule to 5 looks that stay in range; reproduce look 1 in a second colour. Deliverables: 2 new looks, look 1 in a second colour. Read the board and the first run's output before starting.
```

- [ ] **Step 1: Write the script and docs** as in Produces.

- [ ] **Step 2: Lint**

Run: `cd frontend && npx eslint scripts/record-board.mjs`
Expected: no errors (if `scripts/` is outside the lint config, add it).

- [ ] **Step 3: Dry run against a dev server with mock providers**

Run: start `MCP_ENABLED=1` dev with mock providers, make a board, run `node frontend/scripts/record-board.mjs --board <id> --slug dryrun --max-min 1` while the part 1 scripted MCP client (`tests/integration/agent/test_end_to_end.py`'s flow, or a copy in the scratchpad) works the board.
Expected: `reports/demo/dryrun/` has a `.webm` and `run.json`, and `steps.md` lists the steps with times. Delete `reports/demo/dryrun/` afterwards.

- [ ] **Step 4: Commit**

```bash
git add frontend/scripts/record-board.mjs docs/demo/boards.md reports/demo/.gitignore Makefile
git commit -m "feat(demo): record a board while an agent works it; board briefs"
```

---

## After this plan (not tasks: the runs themselves)

1. The person restarts Claude Code with the `muse` MCP server added (a session cannot pick up a new MCP server mid-run).
2. For each board: create it, start `make demo-record`, give Claude Code the brief from `docs/demo/boards.md`, and let it run; Claude Code fetches references (local folder or Google Images via Chrome).
3. Commit `reports/demo/<slug>/run.json` and `steps.md`; the videos stay local for cutting.
