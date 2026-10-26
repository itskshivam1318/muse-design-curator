# Design Language Engine — Vertical Slice Spec

Source: the brief pasted by the user on 2026-10-26, followed by the user's amendments from the same day. **Where an amendment conflicts with the original brief, the amendment wins.**

## Amendments (2026-10-26)

1. **Any design domain, not only watches.** Domain knowledge lives in lenses (data). Watch, fashion, interior and UI lenses ship; other domains get a proposed lens that the user reviews.
2. **Seven attribute kinds:** enum, ordinal, number, boolean, color, text, and shape (experimental). Up to 20 attributes per lens. Add a "nudge more/less" mode for ordinal and number attributes.
3. **Canvas interface:** an infinite canvas. Images have no borders.
4. **Anything added gets parsed:** single or multiple uploads, drag-and-drop, paste, links, and a Chrome extension that captures Instagram reels and videos, Pinterest pins and any page onto the board.
5. **Basic flow:** add images (upload one or many) → set the board's context → add links and captures → the board becomes live → the intelligence comes from the board.
6. Stack, corpus sources and Meta interfaces follow `reports/Meta models image sources and stack.md`.

## Original brief (verbatim)

# Implement Design Language Engine: Reference-to-Validated-Candidates Vertical Slice

## Objective

Implement the first working vertical slice of Design Language Engine: reference board, attribute extraction, editable lens, attribute-aware retrieval, candidate validation, and keep/reject feedback.

The initial domain is watches. The product retrieves existing, licensed images; it does not generate or edit images.

## 1. Repository inspection

Before editing code:

- Inspect the repository structure, framework, installed dependencies, existing routes, storage, database, and test setup.
- Inspect the existing Meta SDK and identify the supported Muse Spark and SAM 3.1 interfaces.
- Reuse existing architecture and conventions. Do not replace the scaffold or introduce a new framework.
- Identify missing infrastructure and state your assumptions before implementation.
- Create a short implementation plan, then implement the feature end to end.

Do not stop after writing a plan or scaffold. Deliver a working vertical slice.

## 2. Reference board

Implement:

- Project brief input and one watch-design project.
- Drag-and-drop and file-picker image uploads.
- Image preview, upload progress, error handling, reference selection, and removal.
- Persistent reference records and image storage.
- Extraction status: pending, processing, completed, failed.
- A preloaded demo project and curated seed corpus so the application works without live search APIs.

Validate file type and size on the server and client. Preserve original files and provenance. Do not invent asset URLs, licenses, or source metadata.

## 3. Attribute extraction and editable lens

Create a provider adapter for Muse Spark.

Input: project brief, reference image, domain schema.

Output: schema-validated structured attributes containing key, label, category, value, confidence, status, source, and evidence.

For watches, support at least:

- Case shape and geometry
- Case material and finish
- Dial colour and finish
- Bezel style
- Strap material and colour
- Markers and hands
- Overall style

Represent missing or uncertain values explicitly. Do not infer unsupported facts simply because the model returns a plausible description.

Build an editable attribute panel. Users must be able to edit, confirm, and disable attributes. Preserve user edits across extraction retries. Record provenance and audit history.

If model credentials are unavailable, use a deterministic mock provider. Do not silently pretend the mock is a live model.

## 4. Variation controls

Allow the user to select exactly one target attribute and choose:

- Explore: retrieve diverse alternatives.
- Prefer: prioritize specified target values.
- Avoid: deprioritize or exclude specified target values.

Automatically propose the other enabled attributes as protected constraints. Let the user remove protected attributes deliberately.

Enforce server-side that the target attribute cannot also be protected.

Display the target and protected attributes prominently before the run begins.

## 5. Candidate corpus and retrieval

Implement a searchable corpus of existing, licensed watch images.

Each corpus item must have a stable ID, image URL, source URL, license, creator where available, normalized attributes, and extraction/indexing status.

Use precomputed attributes and image embeddings if available. Cache expensive model calls.

Retrieval pipeline:

1. Retrieve a broad candidate pool.
2. Exclude the source image, duplicates, unusable assets, and assets with invalid provenance.
3. Apply reliable metadata filters.
4. Compute target-change, preservation, relevance, and diversity scores separately.
5. Apply hard constraints for explicit protected attributes when evidence is reliable.
6. Validate the shortlist.
7. Use diversity-aware selection to return up to six candidates.

Use a configurable, versioned ranking formula. Initial weights may be target change 0.35, preservation 0.35, relevance 0.20, diversity 0.10. Do not treat these as validated weights.

Do not silently treat missing attribute values as matches. A candidate with unknown protected attributes must not pass a strict preservation check.

## 6. Candidate validation

Create an explicit validator returning pass, fail, or uncertain for each relevant attribute.

Check:

- Whether the requested target change is supported by evidence.
- Whether protected attributes are preserved.
- Whether the evidence is sufficient.
- Whether the candidate is a duplicate.
- Whether its provenance is valid.

Use SAM 3.1 for localization when useful, not as proof of semantic properties. A segmentation mask alone does not prove a material or finish.

Never label a candidate as validated just because an API call succeeded.

Reject failed candidates. Keep uncertain candidates separate from validated results or exclude them from the main result set.

If fewer than six candidates pass, return fewer than six and explain why. Do not weaken constraints to fill the grid.

## 7. Candidate cards and feedback

Each candidate card should display:

- Image and source attribution
- Target attribute and observed difference
- Protected-attribute checks
- Overall validation state
- Concise validation reasons
- Keep and reject actions
- Optional rejection reason

Distinguish retrieved, validating, validated, rejected, and uncertain states.

Persist decisions with candidate ID, decision, optional reason, timestamp, project ID, and variation-run ID. Preserve the decision history.

Do not update project preferences indiscriminately from every rejection. The initial version may record feedback without yet learning complex preferences.

## 8. API and persistence

Reuse the existing database and API conventions. Support equivalent operations for:

- Creating a project
- Uploading references
- Extracting or retrying attributes
- Editing attributes
- Starting a variation run
- Fetching run status and candidates
- Saving keep/reject decisions

Persist projects, references, attributes, variation runs, candidates, validation results, and decisions.

Use stable IDs, schema validation, explicit errors, and idempotent retry behavior where appropriate. Record the ranking algorithm version for every run.

## 9. UI states and reliability

Handle upload, extraction, retrieval, validation, partial results, no results, and failure states.

Do not lose references or user edits after a model failure. Avoid duplicate records on retry.

Use a deterministic mock model and fixture corpus for repeatable tests. Include a preloaded demo that can be demonstrated without depending on live external search APIs.

## 10. Testing

Add automated tests for:

- Upload validation
- Attribute schema validation
- User-edited attribute persistence
- Target/protected-attribute invariants
- Retrieval exclusion of the source image and duplicates
- Ranking and diversity selection
- Hard constraint violations
- Missing attributes and uncertain validation
- Fewer-than-six passing candidates
- Keep/reject persistence
- Model timeouts, invalid responses, and retries

Add one end-to-end test covering upload or demo-reference selection through extraction, variation, validation, and feedback.

## 11. Implementation order

1. Inspect the repo and report the plan.
2. Implement persistence and mock providers.
3. Implement reference upload and editable attributes.
4. Implement the corpus and deterministic retrieval/ranking.
5. Implement validation and candidate cards.
6. Integrate live Meta model calls behind adapters.
7. Add tests, error states, and a working demo.

Prioritize a complete vertical slice over additional domains or generalized abstractions.

## Completion criteria

The feature is complete when a user can select a watch reference, inspect and edit its attributes, choose a target and protected attributes, retrieve and validate alternatives, see why candidates passed or failed, and persist keep/reject decisions.

Run the project's existing checks and tests. Report what was implemented, which tests passed, any unresolved issues, required environment variables, and how to run the demo. Do not claim functionality is complete if it is mocked or untested.
