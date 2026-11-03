# Demo boards: run one with Claude Code and record it

Four boards, one brief each. Claude Code works the board over MCP while a script films it.

## Run a board

1. Start Muse with the MCP endpoint on: `MCP_ENABLED=1 make dev`.
2. Connect Claude Code (once, then restart Claude Code so it picks the server up):
   `claude mcp add --transport http muse http://localhost:8000/mcp`
3. Create the board in the app at http://localhost:5173 and note its id (the last part of
   `/boards/<id>`).
4. Start the recording: `make demo-record BOARD=<id> SLUG=<car|ui|room|outerwear>`. It opens
   Chromium at 1920x1080, films the board, and stops 5 s after the board's next agent run is
   done, needs input or paused (or after 60 minutes; `MAX_MIN=<n>` changes that). Pass
   `APP=` / `API=` if the servers are not on 5173 / 8000.
5. Paste the brief below into Claude Code, with the board id (and the reference folder, for the car).
6. When the script exits, `reports/demo/<slug>/` holds `<slug>.webm` (stays local, git ignores it),
   `run.json` (the run with its steps) and `steps.md`. `steps.md` lists each step with its time
   since the recording began, so a snippet is found by step time in the video. Commit `run.json`
   and `steps.md`.

## Briefs

### Car (`SLUG=car`)

```
Car: Work the Muse board "<id>" to a finished design. Goal: a new EV coupe that keeps the language of the references. Deliverables: exterior 3/4 front, exterior side, exterior rear, interior dashboard, interior seats, 3 exterior colourways, one shared design language. Gather 6–10 references (local folder <path> or Google Images via Chrome, keeping each source page). Read the board, propose a lens, analyse the anchor, explore one dimension at a time, render the other views from one anchor with render_view, and check them against each other; if a detail drifts between views (wheels, lamps), fix it with put_into from the view that has it right. Colourways come from exploring colour, not the colour plugin. Narrate every call with say, mark the 5–8 moments that best show how with highlight, then compose_output and finish.
```

### UI (`SLUG=ui`)

```
UI: Work the Muse board "<id>". Goal: a fintech app screen set that is "more premium", where the board pins "premium" to named dimensions and values. Deliverables: the premium vocabulary as a note naming the dimensions and their values, 3 screens (home, card detail, payment confirmation) in that vocabulary, and one "not this" example. Same working rules: say on every call, highlight the moments that show how, compose_output, finish.
```

### Interior (`SLUG=room`)

```
Interior: Work the Muse board "<id>". Goal: a Japandi living room; keep the room and vary only material and palette. Deliverables: the anchor room, 3 finished variations that change only material and palette, and a note saying what stayed fixed. Same working rules.
```

### Fashion (`SLUG=outerwear`)

Session 1:

```
Fashion (session 1): Work the Muse board "<id>". Goal: an autumn outerwear capsule. Deliverables: 3 looks in range and a note naming the range. Same working rules.
```

Session 2, a later run on the same board (record it again with the same slug after moving or
keeping the first recording's files; it overwrites `run.json` and `steps.md`, so rename the
session 1 files first):

```
Fashion (session 2, a later run on the same board): Goal: extend the capsule to 5 looks that stay in range; reproduce look 1 in a second colour. Deliverables: 2 new looks, look 1 in a second colour. Read the board and the first run's output before starting.
```
