# Board chat agent — design

Date: 2026-11-04. Branch `feat/board-chat-agent` (worktree `../muse-agent-chat`, from `origin/main` ae00f83).
Evidence: three spike runs on board `brd_01m6j8qq6xvtzafn8jp3ka6r7c`; traces in the session scratchpad
(`spike/run1..3/trace.md`, `trace.jsonl`, highlight PNGs). The spike script was throwaway; nothing of it
is in the repo.

## 1. Intent

The person types into the agent card's chat box on the board ("For the body on this car, explore a
retro-futuristic direction", "add wheel caps as an attribute and get the mask", "add the grille from the
green car to the red car") and the agent turns it into actions on the board: find or create parts, add
dimensions, explore with the person's words as the steer, visualise, put one picture into another, keep,
lay out, finish.

Today the box says "Agent coming soon"; only an outside MCP client (Claude Code) can drive the board.

**Why:** the board's controls are many and spread out; plain language is the fastest way in. The agent
must make the board easier, never harder to follow.

## 2. What the spike showed

A Muse Spark (`muse-spark-1.3`, Responses API, function tools) loop over the board's existing MCP tools,
plus spike-only tools `look_at`, `ask_user`, `confirm_part`, `add_part`, `extract_part`. Scripted answers
stood in for the person.

| Run | Request | Calls / model time / wall | Outcome |
|---|---|---|---|
| 1 | body → retro-futuristic, push further, keep + wrap | 27 / 141 s / ~9 min | Done. 4 renders, all passed the check. |
| 2 | wheel caps attribute + mask, explore, keep | 52 / 210 s / ~20 min | Done. Mask OK-ish; 1 of 7 renders passed. |
| 3 | grille from green coupe onto red car | 15 / 68 s / ~4 min | Done, wrong target car, weak result. |

Muse Spark tool calling is reliable: correct tool choice, valid arguments, sensible recovery from
refusals (`finish` refusal → rendered bolder options until one passed). The `say` field on every tool
kept the agent card readable.

### Problems, root causes, solutions

| # | Seen | Root cause | Solution in this design |
|---|---|---|---|
| P1 | Run 1: "body" not a part; person said "the whole shell"; agent fell back to an **abstract** dimension — the correction was lost. | The agent had no tool to create a part; `add_dimension(physical)` needs an existing part. | `add_part` tool (wraps existing `POST /items/{id}/parts`). Rule: never downgrade a physical request to abstract without asking. |
| P2 | Run 2: "only the centre cap" → retyped labels; long labels gave `REGION_EMPTY`, short ones gave the same whole-wheel mask. | SAM is prompted by a short noun only; without a box hint it returns the best-scored instance. | **Fix by drawing**: the confirm step lets the person drag a box on the picture; the part is re-added with `region {kind: "mask", box}` → existing `_hinted_mask` picks the instance overlapping the box (falls back to the box). No backend segmentation change. |
| P3 | Run 3: "the red car below it" with 8+ red E-Types; agent picked the original photo without asking. | No notion of what the person is looking at; no ambiguity rule. | The chat sends the **current selection** with each message; "this/that car" resolves to it. Rule: if a reference matches more than one item and nothing is selected, ask with picture choices. |
| P4 | Run 3: `put_into` result had `check: null`; agent called it "clean" after a glance; plate text garbled. | Put jobs are not checked like visualised options. | Put/view results get the same target check as options (`check_target`); the agent must report a failed or unclear check rather than call it done. |
| P5 | Run 2: 6 of 7 hubcap renders failed ("too small to see"). | Muse Image edits the whole picture; a part ~5% of the frame barely changes. | For a part under ~10% of the image area, visualise via crop → render → `put_into` back at the part (or tell the person it is small and offer to zoom). Builder may stage this after v1 (see §9). |
| P6 | Run 2: two empty parts left on the item (`small_chrome_cap_in_centre_of_front_whee`, `front_wheel_centre_hubcap`). | Failed `add_part` attempts were not cleaned up. | `add_part` removes the part itself when its region comes back empty, and returns the error. |
| P7 | Runs 2–3: every chat turn called `set_goal` → three runs per conversation. | `set_goal` is per request; the loop had no thread concept. | **One run per chat thread.** The loop opens the run on the first message; later messages continue it; `set_goal` is not offered in chat (goal/deliverables are set by the loop and updated by a `update_goal` tool). |
| P8 | Each `wait` blocked 30–120 s; two renders in a row ≈ 2–4 min of silence in chat. | Sequential `visualize_option` → `wait` → `visualize_option` → `wait`. | Queue all renders first, then one `wait_all`; renders post `agent.step` events as they land so the card fills in. The person can type while it works (§5.4). |
| P9 | Run 1: ~413k input tokens for 27 calls. | `store: false` means the whole history is resent; tool results (board reads, analyses) are long. | History compaction (§5.3): old tool results shrink to one line; old images are dropped; board state is re-read rather than remembered. |
| P10 | Reasoning text not visible in traces. | Muse Spark returns reasoning encrypted. | Accept. Traces keep the message text, tool calls, arguments, results, usage and timing (§5.6). |
| P11 | Put card opens under the agent card at the bottom-right; its **Put in** button goes off-screen. | Card placement ignores the agent card. | Out of scope for the agent itself but fixed alongside (§6.4), since the chat card makes it worse. |

## 3. Goals, non-goals, anti-goals

**Goals**
- Chat box on the agent card drives the board in plain language, for the requests above and the
  existing agent workflows (references, lens, renders, views, put-into, output sheet).
- The agent goes ahead on its own and **asks only when unsure** (person's decision). Part guesses are
  shown as a highlight on the picture; the person confirms or fixes (person's decision).
- Every board change is visible as it happens and attributable to a chat message.
- Full traces for debugging (person asked for model input/output traces).

**Non-goals (v1)**
- Web image search from chat (no Google/Chrome in-app). References come from the board, uploads, or the
  existing live licensed-source search if the builder wires it (§9).
- Multiple concurrent chat threads per board.
- Voice, multi-user.

**Anti-goals** (failure even if it works)
- The board changes and the person cannot tell what happened, or gets lost in clutter.
- The agent quietly does something other than what was asked (P1, P3).
- A chat that sits silent for minutes.

## 4. Constraints

- **Muse Spark only** for the loop; Muse Image only for pictures (person's decision: keep it all Meta).
  Same `MODEL_API_KEY` / `META_BASE_URL` / `MUSE_SPARK_MODEL` as `providers/reasoning.py`.
- Tools act only through the app's REST API (`ToolContext.api`), so validation, demo lock and daily caps
  apply. Existing per-board render/analyse caps stay the cost guard.
- `backend/app/` must not contain the words watch, fashion, interior, dial, sofa (a test enforces it).
- Next migration is **0012**.
- `DEMO_MODE` write-lock: chat is disabled (input shows why) when the board is read-only.

## 5. Backend

### 5.1 The loop — `app/agent/chat/loop.py`

```
run_turn(board_id, run_id, user_message):
  history = load(run_id) + user_message (+ selection, + board summary on first turn)
  for step in range(MAX_STEPS=40):
     resp = muse_spark.responses.create(model, instructions=SYSTEM, input=compact(history),
                                        tools=chat_tools, reasoning={effort:"medium"}, store=False)
     history += resp.output            # reasoning items (encrypted) included, needed for continuity
     trace(model_call ...)
     calls = function_calls(resp)
     if not calls: post agent message (resp.output_text); status → "running" idle; break
     for call in calls:
        if call is ask_user / confirm_part: post question; status → "needs_input"; save; return
        result = registry.run(ctx, call.name, args)   # records an agent_step as today (say, item_ids)
        history += function_call_output(result)
        history += pending images (look_at)
     if a user message arrived meanwhile: append it, continue
  else: post "I stopped after 40 steps" message
  save(history)
```

- Runs as a background task (same pattern as other jobs), one at a time per board (lock on run_id).
- `ask_user` / `confirm_part` **suspend** the loop: history is saved, the run goes to `needs_input`
  (existing status). The person's reply (a message, a choice, or a drawn box) resumes it with the
  answer as that call's `function_call_output`.
- Stop: existing `PATCH /agent-runs/{id}` (status) — the loop checks it before every model call and
  tool call.
- Model errors: retry once (existing `call_model` helper); then post an agent message with the error
  code and leave the run open.

### 5.2 Tools offered in chat

The existing registry, minus `MCP_ONLY` and minus `create_board`, `list_boards`, `open_board`,
`upload_reference`, `set_goal` (the board is the open one; the loop owns the run). New registry tools
(also useful over MCP):

| Tool | Does | Wraps |
|---|---|---|
| `add_part(item_id, label, box?)` | Adds a part; locates its mask; with `box` the mask is SAM-hinted. Removes the part again if the region is empty. | `POST /items/{id}/parts`, `GET .../region` |
| `remove_part(item_id, part)` | Removes a wrong part. | `DELETE /items/{id}/parts/{key}` |
| `extract_part(item_id, part)` | Cuts a part out as its own picture (source for `put_into`). | `POST /items/{id}/parts/{key}/extract` |
| `look_at(item_ids≤6)` | Gives the model the pictures (next input as images). | `GET /items/{id}/image` |
| `wait_all(ids, kind)` | Waits for several queued renders; returns each as it finishes. | existing `wait` logic |
| `update_goal(goal?, deliverables?)` | Changes the thread's run goal/deliverables. | run_state |

Chat-only tools (handled by the loop, not the registry):

| Tool | Does |
|---|---|
| `ask_user(question, choices?)` | Suspends; `choices` may be item ids (shown as picture buttons) or short text options. |
| `confirm_part(item_id, part, why)` | Suspends; the board highlights the part's mask on the item; the person answers **Yes**, **Fix** (draw a box → the loop gets `{box}`), or types. |

### 5.3 History and compaction

- Stored per run: `agent_runs.history_json` (migration 0012) — the Responses input items. Encrypted
  reasoning items kept for the last 2 turns only.
- Before each call: tool outputs older than the last 2 person-turns are replaced with
  `{"tool": name, "summary": first 200 chars}`; images older than the current turn are dropped;
  `read_board` results are capped to 60 items (id, kind, title, role, position).
- Target: under 30k input tokens per call on boards like the spike's.

### 5.4 Messages — migration 0012

Table `agent_messages`: `id`, `run_id`, `board_id`, `role` (`person` | `agent` | `question`),
`text`, `data_json` (selection ids; question choices; the answered call id; a drawn box), `created_at`.

Routes (`app/api/agent.py`):
- `POST /boards/{board_id}/agent/messages` `{text, selection: [item_ids], answer?: {call_id, choice | box}}`
  → 202 `{run_id, message}`. Opens a run (`source: "chat"`) if the board has no open chat run; joins it
  otherwise. While the loop is working, the message is queued and picked up at the next step.
- `GET /agent-runs/{run_id}/messages` → the thread.
- Events (existing `events.publish`): `agent.message` (new message), `agent.step` (unchanged),
  `agent.question` (question with choices / part highlight), `agent.status`.

An MCP run (Claude Code) and a chat run on the same board: the chat input is disabled while an MCP run is
open ("Claude Code is working"), as today.

### 5.5 Rules in the system prompt (from the spike)

1. Fill `say` on every board-changing tool: one plain sentence.
2. "This/that/it" = the selection sent with the message. If a reference matches more than one item and
   nothing is selected, `ask_user` with the candidate items as choices.
3. A part the person names that is not in the analysis: `add_part`, then `confirm_part` before using
   it. On a correction, re-add (with the drawn box if given) and remove the wrong part. Never turn a
   physical request into an abstract one without asking.
4. An attribute of a part is a physical dimension on that part.
5. Explore with the person's words as the steer; visualise the 2 strongest; queue both, then `wait_all`.
6. Moving a part between pictures: `extract_part` on the source, `put_into` the target at the matching
   part (confirm both parts).
7. A result whose check failed or is unclear is reported as such, not called done.
8. Ask only when genuinely unsure; otherwise go ahead.
9. End each reply with what changed (item ids are linked in the UI) and what the person can do next.

### 5.6 Traces

- Existing `agent_steps` keep tool name, args, `say`, result, item ids (unchanged).
- New: `data/agent_traces/{run_id}.jsonl`, one line per model call (input delta, output items with
  encrypted reasoning shown as length only, usage, latency), per tool call, per person message — the
  spike's format. Written always in dev; behind `AGENT_TRACES=1` elsewhere.
- `GET /agent-runs/{run_id}/trace` (dev only) returns it; the card's ⋯ menu links "Download trace".

### 5.7 Put / view result checks (P4)

After a put-into or render-view job lands, run the same target check visualised options get (target =
the words / the source's subject at the spot) and store it on the item, so `wait`/`put_into` return a
non-null `check`.

## 6. Frontend

### 6.1 Agent card becomes the chat

`frontend/src/shell/AgentCard.tsx` (now with spotlight replay's `useRun`, run picker and "Show me how"
from ae00f83 — build on those, do not fork them):

- Thread view in the expanded card: person messages, agent messages, and the run's steps interleaved by
  time (steps as the existing compact `say` lines, item ids clickable → focus item).
- Input enabled when the board is writable and no MCP run is open. Enter sends; sends the current
  selection with it; a chip above the input shows "About: 1 picture selected" so the person knows.
- While working: status "working" + **Stop** (existing). Messages typed meanwhile appear as queued.

### 6.2 Questions

- `ask_user` with item choices: picture thumbnails as buttons; with text choices: buttons; always a text
  field too.
- `confirm_part`: the canvas frames the item and draws the part's mask (pink overlay, as in the spike)
  with **Yes** / **Fix** on the card. Fix → crosshair on that item, drag a box → sent as the answer.
  Esc cancels back to the question.

### 6.3 Seeing what changed

- Each agent reply lists the items it touched; hovering highlights them on the board.
- New items from the run get the existing "generated" badge; the run picker + spotlight replay
  ("Show me how") already lets the person replay a run step by step — chat runs use it unchanged.

### 6.4 Put card placement (P11)

The Put card avoids the agent card's rectangle (and the viewport edge): placed above/left of the drop
point when it would overlap.

## 7. Decided by the person

- Muse Spark drives the loop; all Meta (no Claude in-app).
- The agent goes ahead on its own; asks only when unsure.
- Part detection: the agent marks its guess, the person confirms or fixes.
- Every change must be visible; full traces for debugging.

## 8. Calls made in this design (check these)

- One run per chat thread; `set_goal` hidden in chat (P7).
- Selection sent with every message resolves "this car" (P3).
- Fix-a-part = drag a box, using the existing SAM box hint (P2).
- Chat input disabled during an MCP run rather than merging the two.
- History stored on `agent_runs.history_json`; compaction rules in §5.3.
- Traces on disk as JSONL, not in the DB.
- Max 40 steps per person message.

## 9. Left to the builder

- Whether P5 (crop-render-put for small parts) ships in v1 or right after.
- Whether chat gets a `search_references` tool over `app/live/search.py` (licensed sources) in v1.
- Exact compaction thresholds, once measured on real boards.
- Wording of the "Agent coming soon" replacement states and the chip.

## 10. Testing

- Loop unit tests with a fake Muse Spark client that replays scripted Responses outputs (the spike's
  three runs become fixtures: wrong-car ambiguity, part correction by box, put-into check).
- Tool tests for `add_part` (empty region removes the part), `extract_part`, `wait_all`.
- Route tests: message opens/joins a run; answer resumes a `needs_input` run; stop halts the loop.
- Frontend: thread rendering, question buttons, confirm-part Fix flow, input disabled states.
- One manual end-to-end with the real model on a car board, trace reviewed.
