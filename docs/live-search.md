# Live search in Vary

A Vary run searches open-licence sources while it also reads the pre-indexed corpus, then treats
both kinds of candidate identically: same exclusions, scores, validator and selection.

## Scope

Licensed APIs only, through the existing `app/corpus/sources/*` adapters: Wikimedia Commons,
Openverse (anonymous), the Met, the Art Institute of Chicago and Smithsonian Open Access. Every
live item passes `check_provenance` (the same licence allowlist as the corpus). No web or image
search engines, Pinterest or Instagram. Pexels stays disabled.

## Flow of one run

1. `write_queries` makes one reasoning call (`live-queries-v1`, cached) for 3 to 5 short queries,
   each naming the target change plus one or two protected cues. If the call fails the run falls
   back to deterministic queries built from the lens labels.
2. `search_live` fans sources x queries out on a thread pool under one `LIVE_TIMEOUT_S` deadline.
   A source that errors or times out is recorded (`failed` / `timeout`) and skipped; what it had
   already returned is kept. Results are de-duplicated (by id and landing URL, also against the
   corpus), filtered by provenance, and capped at `LIVE_MAX_CANDIDATES` round-robin across sources.
3. `quick_index` downloads each new image (6 at a time, resized to at most 1280 px), computes
   sha256 / dHash, one SigLIP embedding row and a whole-image palette, and stores a corpus row with
   `indexing_status='indexed'` and `index_depth='quick'`. No SAM masks, no attributes.
4. The live rows join the corpus pool; exclusions, scoring, the shortlist (16), validation and
   selection run unchanged. Unknown attributes score as unknown and are never matches.
5. For a quick item the validator fills in only what the run checks: SAM on the parts of the
   checked attributes, colour / number / shape measured in code, and every other kind from the
   batched verify answers (which compare against the source image).
6. After validation up to 16 shortlisted quick items get a background `deepen_item` job that runs
   the normal full indexing and sets `index_depth='full'`. `NULL` also means full (rows written by
   the corpus indexer).

Because every checked live candidate is persisted, the next run finds it in the corpus and does
not fetch or index it again.

## Surfaces

- `run.progress`: `{stage: 'searching', live: {sources: {name: 'ok'|'failed'|'timeout'}, found}}`.
  With `LIVE_SEARCH=0` the stage stays `retrieving` and nothing live is reported.
- Run summary: `live: {queries, found, kept, sources, failed}`; the shortfall text names sources
  that did not answer ("Openverse didn't respond").
- Candidate view: `origin: 'corpus' | 'live'` (and `source`).
- Maybe strip: "Searching Wikimedia Commons, the Met, ... (found 23)", then "Checking 8 of 16";
  candidate cards say "Found live on Wikimedia Commons" or "From your library".

## Settings

`LIVE_SEARCH` (default on), `LIVE_SOURCES`, `LIVE_MAX_CANDIDATES=40`, `LIVE_TIMEOUT_S=20`,
`LIVE_PER_SOURCE_LIMIT=15`, `LIVE_QUERY_COUNT=4`. Live calls count against the existing demo run
limits; there are no new ones. Per run: 1 query-writing call, at most 2 verify calls as before,
SAM only for the parts of shortlisted quick items, and at most 16 deepen jobs.
