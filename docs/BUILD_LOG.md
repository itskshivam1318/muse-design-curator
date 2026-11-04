# Build log

Every commit in this repository, oldest first (`git log --reverse --format="%ad  %h  %s" --date=short`).

```
2026-10-26  511f061  docs: spec, plan and research for Design Language Engine
2026-10-26  0ff8859  docs: make plan tasks self-contained; add item embedding columns
2026-10-26  769580e  chore: scaffold backend, frontend, extension; meta smoke script
2026-10-26  8117c00  fix: load .env from repo root regardless of cwd
2026-10-26  b590b28  feat(domain): seven attribute kinds, lens schema, four curated lenses
2026-10-26  619cc55  feat(db): boards, items, lineage, profiles, runs schema and repos
2026-10-26  d0c14e4  fix(db): monotonic ids for ordering; unique curated lens versions
2026-10-26  edc25e2  feat(ingest): images, video keyframes, link unfurl
2026-10-26  c858c57  fix(ingest): bounded video sampling, duration cap, pinned SSRF connections
2026-10-26  c282f21  feat(providers): Meta client, SAM decode, embedders, reliability, cache, mocks
2026-10-26  563e438  fix(providers): accept documented hyphenated selector values
2026-10-26  cd6be86  feat(measure): palette, shape and crop measurement
2026-10-26  f0132f1  fix(measure): typing
2026-10-26  b6eea72  feat(lens): board-driven lens selection and proposal
2026-10-26  be7e845  fix(lens): defer events and jobs until after commit
2026-10-26  bd006e3  feat(parsing): lens-driven item parsing with edit-preserving merge
2026-10-26  89747fe  fix(parsing): measure whole-image parts and release write lock before model call
2026-10-26  67df1e5  feat(board): live board profile and SSE
2026-10-26  34e622d  test(board): cover attribute edit route recompute
2026-10-26  2079877  feat(corpus): licensed importers, provenance, indexer, seed
2026-10-26  512b3a9  fix(corpus): keep invalid items pending, drop index-time dedupe
2026-10-26  5372437  fix(corpus): failed rows that turn invalid become pending
2026-10-26  7a69526  feat(variation): request invariants incl. nudge
2026-10-26  883ca34  feat(retrieval): domain pool, comparators, exclusions
2026-10-26  f81ddf6  feat(retrieval): scores and diversity selection
2026-10-26  44aa0cf  fix(retrieval): clamp pair similarity so diversity stays in 0..1
2026-10-26  51e2e0d  feat(validation): per-kind validator with batched verify
2026-10-26  35e5f96  fix(validation): unreliable number cannot pass a nudge
2026-10-26  3a9bcda  feat(runs): orchestration, summary, API
2026-10-26  e572118  feat(feedback): decisions, keep onto board, not-this
2026-10-26  f2b03c8  fix(feedback): neutralise spreadsheet formulas in decisions CSV
2026-10-26  419d39e  feat(retrieval): exclude candidates already on the board
2026-10-26  a0a5e12  feat(extension): one-click capture to board
2026-10-26  03bcc02  fix(extension): limit pair-code attempts and validate code format
2026-10-26  5b9bc70  feat(api): serve item images and video frames by id; board lens lookup
2026-10-27  6b6a54e  feat(ui): typed API client, SSE cache sync, upload validation
2026-10-27  74ff7d6  feat(ui): infinite board canvas, add flow, context and board signals
2026-10-27  78e42c5  fix(api): board lens lookup returns {lens: null} instead of 404
2026-10-27  8f967e9  fix(ui): end marquee on any mouseup, guard stray file drops, keep Space for focused buttons
2026-10-27  f707ab0  fix(ui): no third-party favicon fetch; abort uploads on unmount and on Cancel
2026-10-27  c853e0a  feat(ui): typed attribute/run/decision client and pure vary logic
2026-10-27  70d77ea  feat(ui): Inspect and Vary drawer panels
2026-10-27  4d40fd3  feat(ui): Maybe strip, candidate popover and keep/reject decisions
2026-10-27  cf0356b  feat(ui): Compare, toolbar and board wiring for inspect/vary/strip
2026-10-27  144ca5f  fix(ui): Inspect skips a PATCH when the value is unchanged; toolbar tests
2026-10-27  74b6d68  chore: make install target; keep live Meta recordings separate from test fixtures
2026-10-27  d39a54f  fix(ui): only http(s) source links; modal, focus-trapped candidate and shortfall dialogs
2026-10-27  2b7c324  test(providers): replay live Meta recordings
2026-10-27  e4d6d76  fix(providers): mock lens proposal is a valid lens
2026-10-27  c5cf70b  fix(seed): leave candidates in the pool
2026-10-27  37ec362  fix(feedback): place kept items without overlap
2026-10-27  6792e18  fix(boards): choosing a curated domain attaches its lens
2026-10-27  e7af6c3  feat(ingest): test-only LINK_ALLOW_PRIVATE_HOSTS exemption
2026-10-27  4aeea3c  feat(frontend): VITE_API_URL for a cross-origin API; DLE_API_PROXY for dev
2026-10-27  6833028  test(e2e): offline Playwright demo flow and extension suite
2026-10-27  c7587a1  build(deploy): HF Docker Space image for the API, Vercel config for the app
2026-10-27  2ef5040  docs: README with quick start, live vs mock, keys, corpus licences, extension, architecture, tests, limitations, deploy
2026-10-27  94c6e33  test(e2e): wait for the nudge run itself, not the previous run's status
2026-10-27  28cd83d  feat(demo): DEMO_MODE guard - read-only until unlocked, capped Vary runs
2026-10-27  008838d  feat(api): serve the built frontend with an SPA fallback when FRONTEND_DIST is set
2026-10-27  3eaf1e5  feat(frontend): demo badge, passcode unlock, read-only controls while locked
2026-10-27  971f611  style(frontend): show the + button as disabled in a locked demo
2026-10-27  d266d04  build(deploy): one Space serves API and app; root multi-stage Dockerfile
2026-10-27  71fda37  docs(readme): single-Space deploy, public demo guard and cost note; current test counts
2026-10-27  385f3dd  build(backend): CPU-only torch on Linux
2026-10-27  3c12b1b  fix(demo): client IP not spoofable via X-Forwarded-For; non-ASCII cookie is locked
2026-10-27  2b8967e  feat(config): live providers by default, mocks for tests
2026-10-27  c9cd2b5  feat(board): auto-attach curated lens from domain votes
2026-10-27  936f9ed  feat(live): query writing and licensed-source search
2026-10-27  0a4f714  fix(backend): nudge/feedback/demo/attribute/profile polish
2026-10-27  2cef9d6  perf(ui): lazy panels
2026-10-27  f44acff  fix(ui): dialog focus containment, shortcut guard, compare source picker, flush text edit
2026-10-27  55c9562  feat(live): quick index and deepen job
2026-10-27  5e20649  docs(extension): show apiBase and host_permissions note in pairing screen
2026-10-27  13b7617  fix(ui): only the topmost dialog contains focus and handles Escape
2026-10-27  a005ebd  feat(runs): hybrid live + corpus retrieval
2026-10-27  1043f2a  feat(ui): live search progress and origin labels
2026-10-27  27c1278  feat(corpus): real-photo manifests and make demo-data
2026-10-27  f27bb32  docs: real corpus and live defaults
2026-10-27  b8cacba  chore: ignore .claude/ worktrees
2026-10-27  592121c  Merge branch 'worktree-agent-aae4b193b4df389a0' into feat/design-language-engine
2026-10-27  8cb3c13  docs: live search
2026-10-27  f9f933f  docs: live search (lint fixes)
2026-10-27  0ea274e  fix(corpus): real batch size and timeout constant, demo-data needs --yes and seeds without re-indexing
2026-10-27  b758810  fix(live): embedding lock, background job queue, bounded live stage
2026-10-27  1f2d63c  Merge live licensed-source search into design-language-engine
2026-10-27  608aee8  fix(corpus): indexer shares the embeddings lock; public attribute store
2026-10-27  8678869  test: batch indexer commits per item; e2e forces LIVE_SEARCH off
2026-10-27  db00808  feat(vary): pre-select only signals, confirmed and same-part protections
2026-10-27  5cf5149  fix(corpus): batch indexer holds no write transaction across slow work or the embeddings lock
2026-10-27  305c4e5  fix(db): busy timeout and short write transactions
2026-10-27  cb85bfb  fix(validation): whole-image fallback when a part isn't localised
2026-10-27  8b7c559  feat(lens): prune curated parts per board
2026-10-27  e244cec  perf(validation): concurrent verify and SAM
2026-10-27  1ae189b  feat(live): cool down unreachable sources
2026-10-27  c4f3bc0  fix(validation): fix round 1 for task 24 (val-4, keep reliable fails, isolate crashes, prune older boards)
2026-10-27  fe812c3  fix(validation): number comparator returns unknown for unreliable values
2026-10-27  5e46e12  fix(feedback): kept and not-this items carry the corpus embedding and palette
2026-10-27  03f4048  fix(events): SSE awaits an asyncio queue and caps open streams
2026-10-27  673b199  fix(runs): judge staleness by a progress heartbeat; never revive interrupted runs
2026-10-27  2d0547c  fix(credit): show the stored licence credit for licensed images on the canvas
2026-10-27  443580d  fix(live): guard live image downloads against SSRF on every redirect hop
2026-10-27  73c9d21  fix(demo): no background deepening for anonymous runs unless DEMO_DEEPEN
2026-10-27  f4f6543  fix(validation): a text check the comparator failed is never sent to verify
2026-10-27  1a555fd  fix(validation): the first valid verify answer wins; NaN confidence is ignored
2026-10-27  4321717  perf(providers): load the embedder once per process
2026-10-27  fa59769  docs: safe deploy snapshot, public data warning, live search, real test counts
2026-10-27  f250dcc  docs: archive build ledger (rulings, deferred items) and final review
2026-10-28  2ea3705  docs: explore → visualize design (text-first variation)
2026-10-28  a6be0af  docs: explore → visualize implementation plan
2026-10-28  20fe01d  feat(providers): swappable image edit provider (muse-image | mock)
2026-10-28  03ba13e  feat(db): explorations, explore options, generated items
2026-10-28  bb6ca99  fix(db): no FK cycle on explore_option_id; safe downgrade; migration test covers constraints
2026-10-28  2eab6eb  fix(db): downgrade clears runs' candidates and validations first
2026-10-28  56ccef5  feat(explore): option and check prompts, provider methods
2026-10-28  52b9fad  feat(explore): explore service and endpoints
2026-10-28  90171e6  fix(explore): default edit prompt carries the description; boolean value; varied mock options
2026-10-28  da9f279  feat(explore): visualize an option, grow the vocabulary, check the result
2026-10-28  1cdb58a  fix(explore): isolate vocabulary step, recover stuck visualizes, kept counts decidable keys
2026-10-28  45afb80  feat(frontend): explore data layer, events, hover store
2026-10-28  b3eeffa  feat(frontend): explore panel, options listed under the dimension
2026-10-28  c0245dc  feat(canvas): explore options as notes linked to the source
2026-10-28  a25f175  feat(frontend): generated caption and check verdict
2026-10-28  aec9c44  fix(frontend): verdict while the option is unknown; guard licence on generated
2026-10-28  2850901  fix(frontend): fallback verdict keeps target and drift tones
2026-10-28  a002912  test(e2e): explore and visualize; docs
2026-10-28  59306b3  fix(make): Ctrl-C in make dev stops both servers
2026-10-28  b5e1d6d  feat: subject filter, board UI event log, more live licensed sources
2026-10-28  2232af7  fix(db): 0004 migration rebuilds board_items with FK checks deferred
2026-10-28  a58c663  test(e2e): wait for the generated item by id
2026-10-28  8ca2f8c  fix(db): defer FK checks around the migration run so version stamps stay atomic
2026-10-28  212617a  fix(explore): place generated images beside the drawn note, guard claims, keep-rest prompts
2026-10-28  d881f44  fix(frontend): send the drawn note position, permanent generated badge, note state
2026-10-28  12fbb91  merge main into feat/explore-visualize; re-chain explore migration to 0006 after 0005
2026-10-28  0d6a20c  docs: round 2 design (calm board, text-first axis, notes, plugin nodes)
2026-10-28  42a8491  docs: round 2 design based on main 12fbb91
2026-10-29  4217030  docs: round 2 implementation plan
2026-10-29  815445b  docs: round 2 artboards for reference
2026-10-29  950eb21  feat(db): round 2 migration (notes, staged takes, plugin tables)
2026-10-29  a1a676a  feat(notes): note items, excluded from image work, read as context
2026-10-29  41f8ce8  fix(notes): keep notes out of extraction context
2026-10-29  ad74d89  feat(notes): visualize a note (text to image), check the result
2026-10-29  3c864b5  feat(explore): staged takes with keep and un-keep
2026-10-29  234e2f7  fix(explore): keep respects claims and dismissal, one kept take, staged upload dedupe
2026-10-29  a6c6615  fix(explore): drop stray .bak, announce un-staged upload dedupe
2026-10-29  2733c5c  feat(plugins): manifests, discovery, packs, per-board install
2026-10-29  9143b69  fix(plugins): fit/formula placeholders, critique available, False counts as unset
2026-10-29  4213f5c  feat(plugins): python, llm and model runners; palette and critique built-ins
2026-10-29  af2cfe4  fix(plugins): count per input image, kill plugin process group on every path, strict plugin schemas
2026-10-29  1ad81a1  feat(plugins): nodes and runs, write-back with lineage, docs and examples
2026-10-29  26ed184  fix(plugins): keep existing attribute kinds, list plugin attributes, check inputs before queueing, progress heartbeat
2026-10-29  093710e  feat(frontend): data layer for notes, takes, plugins and nodes
2026-10-29  cdff986  fix(frontend): generated means origin, plugin images get no verdict, stale run refetch, clear activity per board
2026-10-29  7084cef  feat(frontend): calm board shell with slim rails, agent card and tools
2026-10-29  05229e4  fix(frontend): agent card merges UI actions, rail focus and Escape rules, lens dot on Library
2026-10-29  3b8e4ad  feat(canvas): notes with in-place editing and visualize
2026-10-29  6537746  fix(canvas): v/i/x skip notes; no selection outline over the note editor
2026-10-29  1bc36c1  feat(canvas): text-first axis with staged takes, keep, and chips on the selected item
2026-10-29  c6de769  fix(canvas): kept takes stay selectable items; visualize in progress; pager start
2026-10-29  7b9c067  test(e2e): notes and axis keep flows; update specs for the calm board shell
2026-10-29  0f607d6  feat(plugins): plugins panel, nodes menu and node cards
2026-10-29  c5d7e8d  fix(plugins): removed inputs don't block Run, demo lock, card keys, drop notices
2026-10-29  2f4739c  test(e2e): plugin node flow, axis thumbnail asserts, escaped selectors; README calm board section
2026-10-29  f1f97f0  fix(round2): final review fixes — lens-only explore chips, run summaries, counts, node undo, kept-take delete
2026-10-29  300182c  fix(frontend): reconcile note visualizing state on every items load; refetch items on first stream open
2026-10-29  d2bf619  docs: open beta on Fly.io design (tester identity, board stories, cost guards)
2026-10-29  a4bf1c9  build(deploy): fly.toml for a single open machine with a data volume
2026-10-29  8f4a1cf  build(deploy): fly launch config for muse-curator in sin (no bom region)
2026-10-29  268fdef  fix(deploy): ship the shared vary fixture to the web build; fly.toml notes
2026-10-30  88ff2c4  chore: drop stale peer flags from lockfiles (npm install churn)
2026-11-02  9447222  docs: item analysis engine and exploration map design
2026-11-02  e5de536  docs(spec): no board re-analysis; existing explorations keep working
2026-11-02  7626287  docs: item analysis engine implementation plan (17 tasks)
2026-11-02  2145423  feat(db): item parts, dimension types, content types (0008)
2026-11-02  48b0c2a  feat(analysis): per-item dimension types and spec_for
2026-11-02  1023663  fix(analysis): reject dimensions that cannot form a valid spec
2026-11-02  3f4c9de  feat(analysis): image, UI and text analysers in one Spark call
2026-11-02  c61815f  feat(analysis): analyse service and merge that keeps your edits
2026-11-02  5d9dae0  feat(analysis): resolve part regions on demand
2026-11-02  df07ef8  feat(analysis): label edits and extract a part into its own item
2026-11-02  8c9544d  fix(analysis): keep a chosen content type through re-analysis; reject mismatched part regions
2026-11-02  84119b5  feat(explore): per-item dimensions; retire Vary
2026-11-02  26d5135  feat(map): deterministic free-space layout for callouts and flowers
2026-11-02  a63808e  fix(map): unbounded outward fallback, order-independence test, connector-aware culling
2026-11-02  3560d11  fix(explore): check holds every other dimension; retire Vary decisions
2026-11-02  461ff42  feat(analysis): growing board context and board dimension offers
2026-11-02  c0dd1b2  feat(analysis): per-board daily limits for analyse and render
2026-11-02  8d2e9ec  fix(analysis): count ingest against the daily limit; refund tests
2026-11-02  3662426  feat(render): renderer registry, in-region composite, passage rewrite
2026-11-02  2e004e1  fix(render): keep the feather inside the region, refuse unusable regions, part rows are physical
2026-11-02  9945287  feat(api): analysis, label, extract, renderers and board context routes
2026-11-02  3b3879e  feat(frontend): analysis API types and queries
2026-11-02  d6e1019  fix(frontend): region kinds, raw part region and AttrKind in analysis types
2026-11-02  07d87b2  feat(map): part callouts with region hover; drop chips, Explore drawer and Vary
2026-11-02  522966d  fix(map): drop Find real examples from Search; clear hovered part; mask fallback outline
2026-11-02  b6fc0f7  feat(map): flowers with note petals, renderer-named render, keep as item
2026-11-02  0bb03aa  fix(map): stable flowers on load and across items; callouts avoid flowers
2026-11-02  3276e50  fix(map): draw flowers in id order up to the first analysis still loading
2026-11-02  6d23ba6  feat(board): learned context and dimension offers
2026-11-02  5836020  fix(api): dimension source reads ai or you; sharpen renderer_id test
2026-11-03  6efc599  fix(explore): a note is explored from its text, not refused
2026-11-03  f38318f  fix(canvas): callouts and note bar no longer share a React key
2026-11-03  25e108c  fix(map): an open petal card sits above the selected item's callouts
2026-11-03  42d26bd  test(e2e): exploration map flows; docs
2026-11-03  19218bf  fix(analysis): match the routes to what the board sends
2026-11-03  b1a2566  fix(analysis): note render limit, lost masks, learned room, re-run keys
2026-11-03  337d7f9  feat(board): Re-analyse on the item toolbar; + Add part on images only
2026-11-03  4edd0da  fix(map): fresher caches, petal card focus and placement, onboarding
2026-11-03  9388790  docs: Explore → Visualize as the calm board works; bounded e2e renders
2026-11-03  6be5145  test(e2e): a note hides Getting started; drop the scroll-around workaround
2026-11-03  1b01839  fix(analysis): re-queue analyses left pending or processing by a restart
2026-11-03  ef2a933  feat(frontend): Re-analyse in the note menu; drop the unreachable note branch from the item toolbar
2026-11-03  2d70b11  docs(readme): drop Vary from the intro, architecture and demo-guard sections
2026-11-03  241256e  chore(frontend): remove Vary and lens-review leftovers (API client, run query, helpers, CSS)
2026-11-03  3fff62a  chore(backend): drop the Vary run-limit and replay helpers and settings; fix duplicated test line
2026-11-03  bc1ba89  Merge main (item analysis engine + exploration map) into feat/open-beta-fly
2026-11-03  f7118a5  fix(deploy): run alembic upgrade head before serving
2026-11-03  fb285f6  docs(spec): living board design — fluid nodes, connected flowers, kept-in-ring
2026-11-03  b82b174  docs(spec): keep the living-board prototype beside its design
2026-11-03  18f605c  docs(spec): living board — builder-check answers
2026-11-03  d84f2e8  docs(plan): living board implementation plan
2026-11-03  e45fa82  feat(board): floating add button beside the tool dock
2026-11-03  3d5f3dd  feat(living): damped spring physics core with homes, collisions and drift
2026-11-03  b4732b4  fix(living): order-independent starts, eased sizes, explicit spec copy
2026-11-03  2593867  feat(living): ring geometry and scene builder (bodies, homes, edges)
2026-11-03  1901b27  fix(living): loading analyses hold back unplaced flowers; petal stagger skips kept; fixtures in test/
2026-11-03  dbfc489  feat(living): runtime world with frame loop, pinning and drag API
2026-11-03  bd5d1f2  feat(living): board items, flowers and callouts float in one world
2026-11-03  c40c3da  fix(living): toolbar obstacle, measured callouts, live node wires, quieter frames
2026-11-03  d4f9c74  fix(living): no true overlap at rest, fixed-step world, roomier petal rings
2026-11-03  af36f31  feat(explore): hub offsets and undocked flag (migration 0009)
2026-11-03  231f29c  feat(living): drag flower hubs; one undoable write per release
2026-11-03  4514117  fix(living): turn rings with a dragged hub; locked writes only plain moves; a failed release reverts whole
2026-11-03  a309bf3  feat(living): kept takes dock in their ring and explore further from there
2026-11-03  486671f  fix(living): locked boards dock old takes in locally; no dock-in mid-drag; pending pulses expire; one live-slot helper
2026-11-03  b829063  feat(living): grow-in, keep swell and e2e coverage
2026-11-03  6ac950f  fix(living): a pulled-out take stays spoked to its hub
2026-11-03  e9524f3  fix(living): only flowers near the viewport mount
2026-11-03  6963307  fix(living): a loop restarted inside a frame subscriber never runs twice
2026-11-03  631c554  perf(living): lines at rest are not rewritten each frame
2026-11-03  f1dcfcc  fix(living): hubs and badges show a grab hand and take touch drags; living cards get their own layer
2026-11-03  511d7f6  fix(living): a docking take's picture eases with its body instead of jumping
2026-11-03  6dfe54d  fix(living): a note take docks small like any take
2026-11-03  dba93ef  fix(living): a selected docked take follows its slot on undo
2026-11-03  2657556  fix(living): old takes dock in at their slot's resolved spot, not where a springing hub is
2026-11-03  74949b4  fix(living): drop the dead Branch button from the petal card
2026-11-03  5ec7666  fix(board): the add popover takes focus on its first action
2026-11-03  85d3223  fix(analysis): image parts carry a rough box that picks their mask
2026-11-03  f0f66fb  fix(map): show exploring and rendering on the hub and the dimension row
2026-11-03  f3054c1  fix(living): callout cards clear their image, a selected item's flowers open beyond them, one link per take
2026-11-03  ce32d41  docs: put-into design (connect one picture to another)
2026-11-03  45656e5  docs: put-into implementation plan
2026-11-03  4d47927  fix(providers): retry a gateway timeout once; tell people why a model call failed
2026-11-03  8aada94  feat(put): items record the picture put into them
2026-11-03  cbbac97  feat(put): paste-and-blend helpers
2026-11-03  bf4016b  feat(put): put-into endpoint and job
2026-11-03  1980508  feat(put): client call, events and pending ghosts
2026-11-03  0040b6b  fix(put): a job that settles before its ghost is added still settles it
2026-11-03  589b4b2  feat(put): aiming at parts and their kind
2026-11-03  c433922  fix(put): box-less parts of the same kind are still offered
2026-11-03  6cc44d4  feat(put): connect dot, line and aiming highlights
2026-11-03  7262068  fix(put): the connect dot takes the board accent like its line
2026-11-03  06a637b  fix(inspect): show the item's own parts and dimensions; the close button closes
2026-11-03  a75141b  feat(callouts): remove a dimension or a part from an item
2026-11-03  6d88250  feat(put): put-in card and pending ghosts
2026-11-03  f1822c3  fix(put): the card never sits on the source and its body fits it
2026-11-03  87c4140  docs: board agent design (goal-driven boards, MCP, demo video)
2026-11-03  fe44e43  docs: board agent part 1 plan (tools, MCP, steps, goal, agent panel)
2026-11-03  60106ec  feat(put): source lineage line, e2e and README
2026-11-03  ac5cbea  fix(put): the open card gives way to pinned pictures and toolbars
2026-11-03  8f40583  fix(put): narrow the alpha channel's extrema for mypy
2026-11-03  7a3cbc0  fix(put): end the line when its source or target leaves the board
2026-11-03  bcae5ef  fix(lens): a board whose items fit no curated domain stays on Auto
2026-11-03  23c2679  Merge main into feat/put-into
2026-11-03  eebb069  feat(agent): agent run and step tables
2026-11-03  92371ce  feat(agent): tool registry over the in-process API, steps on the board feed
2026-11-03  5b3d958  feat(agent): board, reference, note and lens tools
2026-11-03  f994fae  feat(agent): analysis, explore, plugin and wait tools
2026-11-03  f385f6f  feat(agent): goal, output sheet, finish with deliverables and consistency checks
2026-11-03  35422ac  fix(agent): output sheet clears items the previous sheet dropped; cap finish image fetches
2026-11-03  27fca7c  feat(agent): MCP server at /mcp behind MCP_ENABLED
2026-11-03  fdd0598  feat(agent): read agent runs and steps, toggle highlights
2026-11-03  b94f3d0  feat(agent): live agent panel in the board's agent card
2026-11-03  7d78cbc  fix(agent): keep live agent steps across a missing cache or an in-flight fetch; say when a highlight fails
2026-11-03  a19fea1  docs(agent): connect Claude Code over MCP; end-to-end test
2026-11-03  bb86384  fix(agent): final-review fix wave
2026-11-03  5cf3a45  Merge main into feat/board-agent; board-agent migration becomes 0011 after put-into's 0010
2026-11-03  22fb8c5  test: put-into migration test expects the new head; plan part 2 (render_view, put_into tool, recording)
2026-11-03  86fe208  feat(views): render the same design from another viewpoint
2026-11-03  e1e04b8  feat(agent): render_view and put_into tools that hand back the new picture
2026-11-03  0d0ba42  feat(demo): record a board while an agent works it; board briefs
2026-11-03  4a9859f  fix(views,put): reserve the landing slot of a queued render until its job ends; wait tool wording
2026-11-03  125c8af  fix(demo): recorder follows joined and newer runs, refuses to overwrite; brief and setup fixes
2026-11-04  4e8470f  fix(lens): proposals work against strict Muse Spark
2026-11-04  6a954f1  fix(views,put): results are read like any new picture; a restart no longer fails them
2026-11-04  b6fb6e8  fix(agent): the sheet undocks kept takes; a contrast row is not compared
2026-11-04  98809ed  test: a file_db marker for tests that send concurrent requests
2026-11-04  bf74010  fix(demo): the recorder keeps filming through a backend restart
2026-11-04  08b8a9e  demo: car and UI board runs (step logs; videos stay local)
2026-11-04  1106c8b  fix(agent): set_lens confirms a proposal made over the curated lens
2026-11-04  449679f  fix(agent): the one-design check reads a range as one design
2026-11-04  7a3cee7  docs: spotlight replay plan
2026-11-04  5d06c25  feat(spotlight): the replay store
2026-11-04  52e62f6  feat(spotlight): past runs and Show me how in the agent card
2026-11-04  4fe0534  feat(spotlight): the dim, the cut-outs and the caption card
2026-11-04  bd7b9bb  feat(spotlight): the canvas lights up and frames each step
2026-11-04  4c44cd8  fix(spotlight): a step is framed once its pictures are in, and the first fit leaves it
2026-11-04  0f16a8b  feat(spotlight): /boards/<id>?replay=<run> opens a replay
2026-11-04  ae00f83  fix(spotlight): final review fixes
2026-11-04  291e6cc  docs: board chat agent design (spike findings, loop, tools, chat card)
2026-11-04  384ba2d  docs(chat-agent): thread lifecycle, demo mode off, MCP/chat rule, result checks
2026-11-04  a783f47  docs: board bundles and landing page plan
2026-11-04  780a1c6  feat(bundle): export a board with its files
2026-11-04  b410084  docs: board chat agent implementation plan
2026-11-04  5ed6135  feat(bundle): import a board bundle, refusing anything unsafe
2026-11-04  83ae146  fix(bundle): replace clears this server's runs and decisions; lenses of other boards refuse; directory entries import
2026-11-04  3630b15  feat(agent): chat messages, run history, waiting status (0012)
2026-11-04  5e5a575  feat(bundle): export and import from the command line; deploy steps
2026-11-04  7794f7d  feat(agent): MCP refuses to join an open chat run
2026-11-04  cdd03d5  fix(bundle): run remote import as the app user; stronger CLI tests
2026-11-04  37f300b  feat(landing): the public landing page with each board's replay
2026-11-04  d224ecc  fix(landing): hold the home route until demo status settles; say when boards fail to load
2026-11-04  8369a31  feat(agent): add_part, remove_part, extract_part, wait_all, update_goal tools
2026-11-04  fbd8aa8  fix(bundle): hold the no-FK references and step items inside the board; refuse an unmigrated database
2026-11-04  b82574d  fix(landing,docs): covers through the API base, two-column cards; deploy steps check the database and turn demo mode on
2026-11-04  0b81564  feat(put,views): results carry a target check
2026-11-04  1827bce  feat(agent): Muse Spark chat model client
2026-11-04  045da9e  feat(agent): chat history compaction and JSONL traces
2026-11-04  779eeef  feat(agent): the board chat loop
2026-11-04  04b3676  fix(agent): chat tool and turn failures end the turn as waiting
2026-11-04  bd96e68  feat(agent): chat routes and runner
2026-11-04  83c0c7f  feat(frontend): chat agent types, calls and events
2026-11-04  d9bdac4  fix(frontend): refetch chat messages for an uncached run instead of seeding a partial list
2026-11-04  0f2ca05  feat(frontend): chat thread in the agent card
2026-11-04  46df578  fix(frontend): keep the chat thread's newest line in view
2026-11-04  177dc93  demo: the 3-minute rough cut, from live recordings and spotlight replays
2026-11-04  58c14d0  feat(frontend): agent questions and part confirmation on the board
2026-11-04  4202a6f  fix(frontend): one answer per agent question; any answer ends box drawing
2026-11-04  2e86cf2  fix(put): the Put card stays clear of the agent card and the screen edge
2026-11-04  ad6d1a6  feat(agent): the MCP agent is called Muse Code in the app
2026-11-04  9c7c5dc  fix(agent): read_board tells originals from made pictures; compaction never cuts mid-JSON
2026-11-04  823acd6  fix(agent): an answer closes its question at once; a repeat answer is refused
2026-11-04  fbcf3be  fix(agent): a message sent while the agent works is never taken as an unseen question's answer
2026-11-04  e106024  fix(put,views): commit the result before its check; done only once the check is stored
2026-11-04  ec0c302  fix(agent): stop a chat turn from the event loop, not the threadpool
2026-11-04  ba19c79  demo: the Vox-style trailer with voiceover
2026-11-04  6fe09e0  merge main into feat/board-chat-agent
2026-11-04  701cd8f  demo: the trailer's voiceover from Kokoro, loudness-normalised
2026-11-04  d9e1e03  demo: trailer v3 (live shots, Vox framing, check/agent/Meta beats)
2026-11-04  a8af462  demo: trailer v3 filmed live on a copy of the car board
2026-11-04  2bd3425  feat(agent): the card opens itself when Muse asks a question
2026-11-04  fea59f0  feat(canvas): a small sparkle icon marks made pictures instead of the generated tag
2026-11-04  e957088  demo: trailer v4, the deck's story with a live board camera
2026-11-04  10788e4  demo: trailer v4 story-dims shot
```
