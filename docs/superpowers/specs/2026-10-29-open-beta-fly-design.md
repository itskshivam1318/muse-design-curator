# Open beta on Fly.io: who used it, what they did, and what it costs

Date: 2026-10-29. Builds on `main` after round 2 (`feat/round2-calm-board-plugins`) is reviewed and
merged. Nothing here starts before that merge.

## Why

Muse needs to be in real people's hands now. Two reasons, both from the user:

1. **Learn what people are looking for.** For each board, see step by step what its person did:
   what they added, what they typed, what they kept and threw away, so the product can be improved
   around real intent.
2. **Pick the demo.** A 3-minute demo video has to be planned. The board stories show which board
   and which sequence of steps make the strongest showcase.

## Goals

- Anyone with the link can use the app. No login, no passcode for visitors.
- Every board has a known person: an email (validated) and an optional name, asked when they
  create their first board.
- A readable, ordered story per board of everything its person did, reviewable by the owner of
  Muse (the "admin"), with a board overview that makes good demo candidates easy to spot.
- Spend on the Meta key is bounded no matter how many people or fake emails show up.
- Deployed on Fly.io from the existing root `Dockerfile`, one machine, persistent volume.

## Non-goals

- Accounts, passwords, email verification codes, magic links.
- Visitors editing boards that aren't theirs.
- The Chrome extension on the hosted app (it stays a local tool).
- Analytics dashboards beyond the board stories and overview below.
- Scaling past one machine.

## Anti-goals (would be a failure even if it technically works)

- An unbounded Meta bill.
- A board story that only logs clicks ("button pressed") and loses what the person typed or chose.
- Asking for the email so early or so insistently that people bounce before trying anything.
- Collecting emails and activity without telling people.

## What visitors see and can do

**Board list.** Seeded demo boards first. Below them, a "Your boards" section with the boards this
browser created. Below that, "Everyone's boards": other visitors' boards, view-only (user's call:
everyone with the link can see every board). Each shows the owner's name, or "Anonymous" without
one; emails are never shown to visitors (my call). Reads therefore stay open as today; only writes
are owner-checked.

**Demo boards** keep today's anonymous access (my call, so people can try Muse before giving an
email): browse, inspect, move items, Vary (existing per-address limits), Keep/Reject on
candidates. Everything else on them stays admin-only. These actions are logged in the demo board's
story under an anonymous visitor id (the cookie), linked to the email later if that browser gives
one. A new board starts empty.

**Creating a board.** The first time a browser creates a board, it asks for:
- email (required), validated: well-formed, and the domain has mail (MX, or A as fallback per
  RFC 5321) checked server-side with a short timeout. *My call: if the DNS lookup times out or
  errors, accept a well-formed address rather than block the person.* Obvious throwaway domains
  may be rejected with a small blocklist (builder's call).
- name (optional).
- one line under the form: "Your boards, and what you do on them, are visible to everyone using
  Muse and recorded to improve it."

The browser remembers them (a long-lived signed cookie identifying the visitor, plus the email and
name stored server-side), so later boards don't ask again. The form offers "not you?" to change.

Identity is the cookie, not the email (my call). Emails aren't verified, so typing an email that's
already on record never reconnects anyone to existing boards: it makes a new visitor that shares
the email. A person who switches device starts fresh there. The admin overview groups by email,
so one person's boards across devices still read together. The 3-boards cap counts per email
across all its visitors.

**On their own boards** visitors can do everything the app does today: uploads, links, notes,
Explore, Visualize, Vary, Keep/Reject, plugins and nodes, lens edits, deleting items.

Ownership: a board belongs to the visitor (cookie) that created it. Writes to a board require that
visitor's cookie or the admin key. This replaces today's `DEMO_MODE` default-deny passcode guard
(`backend/app/main.py`, `backend/app/demo.py`) for visitors.

**Admin.** The existing passcode becomes the admin key (unlock as today). With it: write anywhere,
no limits, plugin reload, and the board story pages. `POST /api/plugins/reload` and any other
instance-wide write are admin-only.

## Guards (cost and abuse)

All numbers are environment variables; the values are defaults (my call), tune after launch.

| Guard | Default | Counts |
|---|---|---|
| Image generations per board | **100** (user's number) | every generated image: Explore Visualize, note Visualize, plugin images |
| Boards per visitor | 3 | per email *and* per client address (whichever hits first) |
| Daily image generations, whole app | 300 | same as per-board |
| Daily model runs, whole app | 500 | Vary runs, Explore requests, Spark/LLM plugin runs, upload/link parsing |
| Daily uploads + links, whole app | 300 | |
| Existing Vary per-address limits | unchanged | `DEMO_RUNS_PER_IP_PER_HOUR`, `DEMO_RUNS_PER_DAY` |

When a limit is hit the app says which one and when it resets ("This board has used its 100
images", "Muse is resting until tomorrow — the daily budget is used up"), never a generic error.
Each board shows its image count against the cap (e.g. "37 / 100 images"). Admin is exempt.
Limits are counted in the database, not memory, so a restart doesn't reset them.

## The board story (activity log)

Builds on what exists: `ui_events` (`backend/app/api/ui_events.py`, frontend posts batches) and
`decisions`. Changes:

- Every event records the board, the visitor, server time, and the action.
- **Content, not just clicks.** Events carry what matters for intent: text typed into Explore
  requests, notes, Vary nudges and lens edits; which option/candidate was kept, rejected or
  un-kept; which plugin ran on what; uploads and links added (item id and source URL, not the
  file); items deleted; Visualize started and its result (done/failed); limit-hit and error
  events; session start/end (first and last activity of a visit).
- Model failures and server errors that a visitor saw are logged into the same story, so drop-off
  points are visible.
- Visitors can post events only for boards they own (fixes today's state, where anonymous visitors
  are blocked from posting events in demo mode).

**Admin views** (behind the admin key; plain pages, function over polish):

1. **Overview**: one row per board: person (name, email), created, last active, number of visits,
   items, Explore requests, images generated, keeps vs rejects, plugin runs, errors. Sortable, so
   boards with the richest use (good demo candidates) rise to the top.
2. **Board story**: the board's events in time order, grouped by visit, written as readable steps
   (e.g. "typed 'same dial, warmer strap' → 3 takes → kept take 2"), with thumbnails of the items
   involved and a link to open the board itself.
3. **Export**: the overview as CSV, each story as JSON, for reading outside the app.

## Deploy on Fly.io

- `fly.toml` at the repo root using the existing `Dockerfile`; internal port `$PORT`.
- One machine, never autoscaled beyond one (SQLite, rate limits and SSE live in one process).
  4 GB RAM (SigLIP2 embedder loads at start). Region: Mumbai (`bom`) unless the builder finds a
  reason otherwise. Machine stays running (no scale-to-zero cold starts during a visit).
- 3 GB volume mounted at `/data` (the snapshot is ~229 MB and grows with uploads and generated
  images; my call); `DATA_DIR=/data`, `DATABASE_URL=sqlite:////data/dle.sqlite`.
  The entrypoint already copies the baked snapshot on first start.
- Secrets via `fly secrets set`: `MODEL_API_KEY`, admin passcode, `DEMO_SECRET`. Variables:
  providers live (`muse-spark`, `sam-3.1`, `siglip2`), `DEMO_TRUST_PROXY=1`, `DEMO_PROXY_HOPS=1`
  (verify the hop count against Fly's proxy), `CONTACT_EMAIL`, `PUBLIC_APP_URL`.
- Health check on an existing cheap GET.
- **Clean `data/` before baking:** deploy from a copy with only `seed` and `candidate` board items
  (today's `data/` also holds 27 generated, 3 upload and 1 link item from development). The
  README's check must print 0. The working `data/` is not touched.
- Backups: rely on Fly volume snapshots, plus an admin-triggered download of the SQLite file
  (builder's call how).
- Smoke test after deploy: create a board with an email, upload, Explore, Visualize, run a plugin,
  hit a limit (with a lowered env value), read the story as admin.

## Constraints

- Audience: 5–10 people the user shares the link with; not a public launch. The guards are a
  backstop, not the main control.
- The hosted app uses the live image model as in development (`IMAGE_PROVIDER=muse-image`, user's
  call for this small beta). Meta's policy lists Muse Image as unavailable from India; the user
  knows and plans to swap the model before the demo video. It stays behind `IMAGE_PROVIDER`; no
  geo workarounds.
- Meta applies no spending cap; the daily budgets above are the only ceiling.
- Existing tests stay green; new behaviour gets tests (backend, frontend, one e2e for the
  email-then-board flow).

## Feedback box

A small "Tell us something" box on every board; what's sent lands in the board story as a
feedback event and shows in the overview (my call: kept, it's small and gives intent in the
person's own words).

Deleting a person's data on request is out (my call: with 5–10 known people, do it by hand if
asked).

## Left to the builder

Table and column names, cookie format, how the story is rendered, admin page layout, the
throwaway-domain list, how counts are stored, and the exact event vocabulary — as long as the
content listed above is captured.
