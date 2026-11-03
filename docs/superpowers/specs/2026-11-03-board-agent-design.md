# Board agent: goal-driven boards, MCP, and the demo video

Status: design, awaiting approval · 2026-11-03

## Why

Muse needs a demo video that states the problem and then shows the app solving it. The problem, in
the person's words:

- **Problem 1, curation along dimensions.** Designers say "like this one, but different in X".
  Today's tools match overall similarity and cannot hold "keep everything, vary only X" as an
  operation, so designers re-query, hand-edit images or restart from text. As boards grow over days,
  suggestions drift toward too similar or too random, and unchecked "more like this" narrows the
  board.
- **Problem 2, shared design language.** Words like "clean", "premium", "more modern" are
  underspecified, carry approval more than visual information, and shift with the project. Human
  designers close the gap by building a project vocabulary from references, questions and options
  side by side. AI tools neither build nor expose one; users re-roll, blame their prompts, and cannot
  reproduce or explain a look across sessions.
- **Combined framing.** The board is the shared language. Each reference is an exemplar, each kept or
  removed item a grounding signal, each dimension a word the user and the system have agreed on.

The person does not want a hand-made tour. They want the platform **used for real**: an agent
chasing a goal end to end on each board, producing a finished output (for the car: a new design
with exterior and interior images and colour options). The good moments from those real runs are
cut into the video.

Two ways in, one set of tools:

- **Claude Code / Muse Code over MCP**: an outside coding agent works a board, and the person sees
  every change land on the open board.
- **The Muse agent** inside the app: the same loop, run by Muse Spark, started from a goal typed on
  the board.

## What it is (as agreed)

- **Four end-to-end boards, one goal each**, in the fields UI, interior, fashion, and car (exterior
  and interior). Each ends with a finished output on the board.
- **The agent does it live (C)**: a panel on the board shows the agent's narration and each tool it
  calls while the board changes.
- **Spotlight (A) shows good examples of C**: inside the app, a spotlight replay walks a visitor
  through the highlights of a finished agent run (dim the board, light up one item, a card with the
  step's caption, Next).
- **The video** is cut from snippets of the real runs, with the problem statement over them.
- Reference repos taken as the pattern: `meta-models/legal-agent-workshop` (one tool per turn, one
  file per tool, progress saved every turn, checks inside tools the agent cannot skip, stop when a
  person must act, a live console) and `sinanuozdemir/ai-experiments/.../meta-hackathon-muse` (Muse
  Spark scored best at `reasoning_effort=low`; grade with code).

## Goals

1. One board-tool registry in the backend, used by both the MCP server and the Muse agent.
2. An MCP server Claude Code can connect to; every action it takes appears on the open board live.
3. Every agent action is recorded as a **step** on the board (tool, arguments, one-line narration,
   result, time), shown live in an agent panel.
4. A goal (brief) per run with a list of **deliverables**, checked by code before the run counts as
   done.
5. Four real boards built by Claude Code over MCP, recorded, good enough to cut into the video.
6. Spotlight replay of a finished run's highlights inside the app.
7. The in-app Muse agent, running the same tools from a typed goal.

## Non-goals

- New image capabilities beyond what exists plus put-into (`2026-11-03-put-into-design.md`).
- Multi-user accounts or auth on the MCP endpoint beyond local use.
- The Muse agent browsing the open web (it uses the licensed live search that exists).
- Editing the final video inside the app.

## Anti-goals (failure even if it works)

- **Faked runs.** Snippets are cut from real runs; nothing in the video is a scripted mock passed off
  as the agent. Re-taking a run is fine; staging one is not.
- **Hidden actions.** An agent change that does not show on the board, or shows without a step
  explaining it.
- **Generic outputs.** A finished output whose images don't share the board's language (the car's
  interior looks like a different car) defeats Problem 2.
- **A tour that hides the board.** Spotlight must leave the board readable; it is a replay of real
  work, not an app tutorial.

## Constraints

- Backend: FastAPI, Python 3.12, SQLite, in-process job runner and in-process event pub/sub
  (`app/events.py`, board SSE at `GET /api/boards/{id}/events`). Events only reach the browser if
  the change happens **in the backend process**. So tools must run inside the backend, not in a
  separate process writing the DB.
- Model access: Meta Model API via the OpenAI SDK (`app/providers/meta_client.py`). Muse agent uses
  Muse Spark at `reasoning_effort=low`.
- Image model: renders use `IMAGE_PROVIDER` / `IMAGE_MODEL` (default `muse-image-1.0`). Muse Image
  is listed as not available from India. **The person's decision: showcase both** Muse Image and a
  second model, both behind the provider switch. The second provider must support `edit(image,
  prompt)` as well as generate, since vary-only-X, put-into and `render_view` all edit. Which model
  that is gets picked when the provider is built. Never route around geo controls.
- `DEMO_MODE` (public, read-only unless unlocked) must not be bypassable through MCP or the agent.
- Many actions are background jobs (analyse, explore, visualize, plugin runs). Tools must let the
  agent wait for a job and read its result.
- Daily per-board analyse limits exist (`app/analysis/limits`); tools surface a limit hit as a
  refusal the agent can read, not a crash.

## How it works (decided)

### 1. Board tools

New package `backend/app/agent/`. `tools/` has one file per tool, each with a `DEFINITION` (name,
description, JSON-schema parameters, what the model sees) and `run(ctx, args) -> dict`, calling the
existing services in-process so events fire exactly as when a person acts. `tools.definitions()` and
`tools.run()` are all a caller needs. A refused call returns `{"error": ...}` the agent can correct
from; it never raises to the caller.

Every tool takes an optional `say`: one plain sentence of narration ("The room reads warm-minimal;
I'll keep that and vary only the material."). It is stored on the step and shown in the panel.

Starting tool set, mapped onto what exists (builder may merge or split):

| Tool | Backed by |
|---|---|
| `create_board(title, context, domain)`, `list_boards`, `open_board` | `api/boards.py` |
| `set_goal(goal, deliverables[])` | new (see 3) |
| `add_reference(url, x?, y?)`, `upload_reference(path)` (MCP only: a local file) | `POST /boards/{id}/items` ingest. Every item keeps where it came from (file path or page URL) |
| `search_references(query)` → candidates, then `add_reference` | `app/live/search.py` (licensed sources) |
| `add_note(text)`, `visualize_note(note)` (text → generated image) | `api/notes.py` |
| `remove_item(item)`, `move_item(item, x, y)` | `api/items.py` |
| `propose_lens`, `set_lens` | `api/lenses.py` |
| `analyse(item)`, `get_analysis(item)` | `api/analysis.py` |
| `add_dimension(item, key, …)` | `api/analysis.py` dimensions |
| `read_board()`: items, the board's shared signals, tensions, "not this" | `GET /boards/{id}/profile`, `/context` |
| `explore(item, dimension)`, `visualize_option(option)`, `keep_option`, `unkeep_option` | `api/explore.py` |
| `put_into(source, target, spot, words?)` | put-into, once built |
| `run_plugin(...)` (colour variation, clean-up, 3D, animate) | `api/plugins.py` |
| `wait(job)` → status and result | job / item state |
| `render_view(anchor, view, words?)`: the same design from another viewpoint or its matching interior, made by image edit from an anchor item | new, small: the existing edit call with a view prompt *(my call: this is how the car stays one car; it is the one new image action this build adds)* |
| `compose_output(title, sections[])` | new (see 3) |
| `finish(summary)` | new: runs the deliverables check (see 3) |

### 2. MCP server

Mounted **inside the FastAPI app** at `/mcp` (streamable HTTP), serving the same tool registry, so
every MCP call runs in the backend process and the open board updates through the existing SSE.
Claude Code connects with `claude mcp add --transport http muse http://localhost:8000/mcp`. Off
unless `MCP_ENABLED=1`. With `DEMO_MODE` on, write tools follow the same lock as the REST API.

### 3. Runs, steps, goal, output

- **Agent run**: one per goal per board, with `source` (`mcp` or `muse`), status (`running`,
  `needs_input`, `done`, `paused`), turn count. MCP calls attach to the board's open run (an MCP
  session that calls `set_goal` opens one).
- **Step**: one row per tool call (run, tool, args, `say`, result summary, ok/refused, time,
  `highlight` flag). Published as a board event, so the panel updates live. New tables, next
  migration after `0009`.
- **Goal**: `set_goal(goal, deliverables[])`. Deliverables are concrete, countable things, e.g. for
  the car: "exterior 3/4 front", "exterior side", "exterior rear", "interior dashboard", "interior
  seats", "3 colourways of the exterior".
- **Output**: `compose_output` lays out the chosen items as a labelled sheet on the canvas (a
  titled region of existing items and notes, sections in order, one caption per item saying *why*
  it was chosen in the board's own dimension words). It reuses items and notes; no new item kind
  unless the builder finds the canvas needs one.
- **Deliverables check** (inside `finish`, the agent cannot skip it): every deliverable is mapped to
  ≥1 output item, every output item that has a result check (explore visualizations, note renders)
  passed it, and nothing in the output was removed. *(My call: outputs with no check today, such as
  plugin results, are not blocked; colourways should come from exploring the colour dimension, which
  is checked, rather than the colour plugin.)*
- **Consistency check** *(my call)*: after the code checks pass, one Muse Spark call looks at the
  output images together and says whether they read as one design (same car, same room language),
  naming the ones that don't. Like the workshop's claims check, it is model-graded but outside the
  agent's control. A failure goes back to the agent like any refused `finish`. A failure returns the problems to the agent; after 3 failed finishes the run goes to
  `needs_input` for the person. This is the run's eval: pass/fail plus counts (turns, tool calls,
  refusals, renders, failed checks), shown on the run like the workshop's console.

### 4. Board UI

- **Agent panel (C)**: a right-side panel on the board: the goal and deliverables (ticked as the
  output fills), then the step feed: narration as chat lines, each tool call as a small tool line,
  coloured by outcome. Clicking a step selects and pans to the item it touched. A goal box at the
  bottom starts a Muse agent run (5); during an MCP run it shows "Claude Code is working".
- **Spotlight replay (A)**: on a finished run, "Show me how" plays the highlighted steps over the
  current board: dim, light up the item the step touched, a card with the step's `say` and step
  number, Next / Back. It replays recorded steps; it does not re-run tools. Highlights are marked by
  the agent (`highlight: true` on a tool call) and can be toggled by the person in the panel.

### 5. Muse agent (in app)

The workshop loop: each turn ask Muse Spark (Responses API, tools from the registry,
`parallel_tool_calls=False`, `reasoning_effort=low`) for one tool call, run it, send the result
back, save progress. Stops on `finish` passing, `needs_input`, the turn limit (`paused`, resumable),
or repeated model failure (`paused`). System instructions in `app/agent/instructions.md`: work like
a designer: read the board first, vary one dimension at a time, keep the board's language, use
`say` on every call, end with `compose_output` and `finish`. Runs on the in-process job runner.

### 6. The four boards (goals, first draft)

The field list and the car goal are the person's; the other goals are my draft and are expected to
be rewritten when the runs happen.

| Board | Goal | Shows |
|---|---|---|
| Car | A new EV coupe: exterior (3/4 front, side, rear), interior (dashboard, seats), 3 exterior colourways, one shared design language | Problem 1 (vary only X, put this wheel into that car) and Problem 2 (exterior and interior agree) |
| UI | A fintech app screen set that is "more premium", where the board pins "premium" to named dimensions and values | Problem 2 (the vocabulary) |
| Interior | A Japandi living room: keep the room, vary only material and palette, three finished room variations | Problem 1 |
| Fashion | An autumn outerwear capsule (5 looks) built over more than one session, staying in range | Drift and narrowing over time, reproducing a look across sessions |

### 7. Where references come from (the person's decision)

- **Local files**: a folder of images per board, added with `upload_reference`.
- **Google search in Chrome**: Claude Code uses Claude in Chrome to search Google Images, download
  the chosen images, and add them with `upload_reference` (or `add_reference` with the image URL),
  keeping the source page URL on the item.
- The in-app Muse agent uses the licensed live search only.
- There is no car lens; the car board relies on `propose_lens` (or a car lens is added if the
  proposed one is weak; builder's call).

### 8. Landing page (the person's decision: video and landing page both)

The four finished boards and their spotlight replays go on the public landing page.

- **Board export/import** *(new)*: a bundle per board (items, images, analyses, explorations,
  output, agent runs and steps) exported locally and imported into the deployed app. Nothing like it
  exists today.
- **Visitors with the board locked can watch the replay and look around, and nothing more** *(my
  call)*: they can't toggle highlights, start a Muse agent run, or reach MCP. This protects the model
  credit. Unlocking with the passcode opens everything as today.
- The landing page links to each board's replay ("Show me how") and embeds the video.
- Deployment needs the Fly app back up (the trial ended 2026-11-03 and needs a card), which is the
  person's to do.

### 9. The video

Claude Code runs each board over MCP while the board is screen-recorded at 1080p (Playwright video
capture or the person's screen recorder; builder's choice). Recordings, the runs' step logs and the
finished outputs are kept per board under `reports/demo/<board>/` so snippets can be found by step.
Cutting and titling the final video is outside this build.

## Order

1. Tools + MCP endpoint + steps and board events (Claude Code can work a board and the person sees it).
2. Goal, `compose_output`, `finish` with the deliverables check.
3. Agent panel (C).
4. Image model swap, then run and record the four boards with Claude Code.
5. Spotlight replay (A).
6. Board export/import and the landing page.
7. In-app Muse agent.

Put-into is a separate plan (`2026-11-03-put-into.md`); the car board uses it if it has landed by
step 4 and does without it otherwise.

## Calls I made (the person can overturn)

- "Agent run" gets a name distinct from the existing Vary `runs` table.
- Board events now published in route handlers (e.g. item patch/delete) move into services, so tools
  fire the same events.
- Fashion "over time" = several runs on the same board, each with its own goal (the second extends
  the first); the panel lists past runs, spotlight replays one run at a time. No real-time gap is
  required between recordings.
- `render_view` and the consistency check (above).

## Left to the builder

- Exact tool names, argument shapes, and which tools merge or split.
- The MCP library and the mount details.
- Table and column names, and the migration number.
- Output sheet layout on the canvas.
- Panel and spotlight visual design, within the existing board UI style.
- How recordings are captured.
