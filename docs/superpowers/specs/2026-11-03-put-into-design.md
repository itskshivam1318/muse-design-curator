# Put into: connect one picture to another to put it in

Status: design, awaiting approval · 2026-11-03

## Why

The board can already pull a part out of a picture (Extract) and grow variants of it (a flower of
takes, e.g. eight alloy wheels). Today there is no way back. The person extracted the yellow car's
wheel, grew a bronze Halibrand take from it, and now wants **the yellow car wearing the bronze
wheels**. More generally: take anything on the board (a part, a take, any picture) and put it into
another picture: this wheel on that car, this lamp in that room.

The round trip (extract → vary → put back) is what turns the board from a place to look at
options into a place to compose with them.

## What it is (the person's words, as agreed)

- **Connect, only.** Select a picture; a small dot sits on its edge. Drag from the dot to another
  picture: a line follows the cursor. Drag-and-drop of one picture onto another is **not** part of
  this: dragging a picture still only moves it.
- **Aim at the spot.** End the line on the spot where it should go: a part of the target picture.
- **All matching spots.** Putting the wheel on the car fills **both** wheels, not only the one it
  was cut from.
- **Optional words.** A few words can steer it ("only the hubcap", "keep the motion blur"); blank
  is fine.
- **A new picture.** The result is a new picture beside the target. The two pictures it came from
  never change.

Mockup reviewed with the person: `.superpowers/brainstorm/…/content/put-into-flow.html`
("Way 2 · Connect them" and "The result" are the agreed screens; "Way 1" was dropped; the mockup's
"or onto a part card" is dropped too, see decisions).

## Goals

1. Put a picture (or its subject) into a chosen spot of another picture, as a new picture.
2. Fill every spot of the same kind in one go, with a way to switch spots off before it is made.
3. Optional steering words.
4. Keep where it came from visible: the result is linked to both pictures it was made from.

## Non-goals

- Drag-and-drop onto a picture (explicitly dropped).
- Editing the target picture in place, or changing the source.
- Combining two options/dimensions, or merging callout rows (separate requests).
- More than one source per result (one line, one source; chain results for more).
- Notes, links and videos as source or target (images only for now).

## Anti-goals (would be a failure even if it technically works)

- **A sticker look.** A flat cut-out pasted on top, with wrong perspective, lighting or blur.
- **Anything outside the chosen spots changing**: the car's body, the background, the number.
- **Overlap on the board**: the line, its card or the result covering pictures, cards or flowers
  (the person has pushed hard on "no overlapping").
- A second, competing way to link things that looks like the existing lines but means something
  else.

## How it works

### On the board (frontend)

**1. Start.** A selected image on the canvas (not a note, link or video; a take must be kept first,
since an unkept take lives only inside its petal card) shows a **connect dot** on its right
edge, centred vertically, in the board accent (#2b44c4), like the stem's root dot. It shows only
for a single selection, not in demo-locked mode, and not while dragging. The selection toolbar
stays where it is.

**2. Drag the line.** Pressing on the dot starts a line (a solid accent curve, the spoke style)
from the dot to the cursor. The board does not pan or marquee while it is held. Esc or letting go
over nothing cancels it, leaving nothing behind.

**3. Aim.** While the line's end is over another **image**:

- If the image has an analysis with parts, the part whose region is under the cursor lights up
  (the same region highlight hover uses today), and so does **every part of the same kind**
  (see *Matching spots*). A label by the line's end reads e.g. "2 spots".
- Over an area that is **no part** (or the image has no analysis): a small ring marks the exact
  point; the spot is "here", one spot.
- Over the source itself, a note, a link or a video: nothing lights up; letting go cancels.

**4. Let go: the card.** The line stays, ending on the spot, and a card opens **on the line**
(placed by the living board's physics like any other body so it never overlaps):

- Title: "‹source name› → ‹target name›" (titles, falling back to "Picture").
- One chip per spot ("✓ Front wheel", "✓ Rear wheel", or "✓ Here"). Clicking a chip switches that
  spot off (struck through) or back on; at least one stays on (Put in disabled at zero).
- A one-line text box, placeholder "Anything to add? (optional)", max 200 characters.
- **Cancel** (removes the line and the card) and **Put in** (primary). Enter = Put in, Esc = Cancel.
- Errors (daily limit, model failure) show in the card, as the callout cards do today.

**5. The result.** Put in sends the request. Errors that come back at once (daily limit, demo
lock, a bad spot) show in the card, which stays open. Once the job is accepted, the card and the
line close, and a **client-only ghost** appears beside the target: a dashed box the size the result
will be, with a soft "Putting in…" overlay. It is a physics body, so nothing overlaps it, and it is
not a database row (matching visualize: no item exists until the render succeeds). When the job
finishes, the real picture arrives through the usual board events and replaces the ghost. If the job
fails, the ghost turns into a small error tile with the message plus **Retry** (same request) and
**Dismiss**. After a reload a pending ghost is gone, but the result still appears when the job
finishes. When it
lands it is an ordinary picture: a red "generated" badge, its credit caption, selectable,
analysable, extractable, explorable. It is linked to both pictures it came from (see *Links*).

### Finding the part under the line's end

Hit-testing uses the parts' boxes from the target's analysis, already loaded on the client. When
the line first enters a target, the board also asks for each part's region (`GET …/parts/{key}/region`,
which segments and caches masks), and the highlight sharpens from box to mask as they arrive; boxes
are enough to aim. Where boxes overlap, the smaller one wins. A part with no box cannot be aimed
at directly, but is still offered as a chip when it matches the aimed part. At Put in, the server
locates any spot whose mask is not cached yet, as visualize does.

### Matching spots

Given the aimed part P on the target, the spots are P plus every other part of the target of the
same kind. **Same kind** = the parts' labels share their head noun (last word, lower-cased,
singular): "Front wheel" and "Rear wheel" → "wheel"; "Glass canopy" alone → itself. This is done on
the client from the analysis already loaded (no model call). A builder may improve it later; the
chips let the person correct it either way.

### What gets put in (the source's subject)

- A source with transparency (an Extract cut-out) is used as is.
- Otherwise, if the source has an analysis with exactly one part, or a part covering most of it,
  that part's mask cuts the subject out.
- Otherwise the whole source picture is the reference and the model is told what it shows by the
  source's title/description.

### Making it (backend)

New endpoint `POST /items/{target_id}/put-into` with
`{ source_id, spots: [{ part: key } | { point: {fx, fy} }], words?: string }` → 202 with a job id
and the size and place the result will take; the render runs as a job, like visualize. It counts against the board's daily
**render** limit, refunded on any failure including a model failure (the person got nothing; this
extends `limits.refund`, which today refunds only before a model is called), and is refused in
demo-locked mode. The job reports success/failure through the existing board events, keyed by a job
id the endpoint returns.

The provider takes one image (`ImageProvider.edit(image, prompt)`), so the render is
**paste, then blend**:

1. For each spot, fit the source's subject into the spot's box (a part's box, or a box around the
   point sized relative to the target, ~20% of its shorter edge), keeping its aspect ratio, and
   paste it into a copy of the target.
2. Edit that pasted picture with a prompt that names what was pasted and where, and asks the model
   to make it belong (match perspective, lighting, colour cast, motion blur, scale) and **change
   nothing else**. The optional words are appended.
3. `composite_in_region` the edit back into the original target inside the union of the spots'
   regions (masks where they exist, else boxes), feathered, so nothing outside the spots changes.

If the provider gains multi-image input later, step 1 can give the subject as a reference image
instead of pasting; the endpoint and the board do not change.

### Links (where it came from)

The result's `parent_item_id` is the **target** (it is a version of the car), so the existing
lineage line connects it to the target. A new nullable column `put_source_item_id` on items records
the **source**; the board draws a second, identical lineage line from the source to the result when
either is selected, and none when neither is. Migration `0010`.

## Constraints

- Builds on what is there: React + Konva board and the living-board physics in `frontend/src/living`
  (the card is a body so nothing overlaps), FastAPI + SQLAlchemy backend, the existing image provider
  and jobs, `composite_in_region`, parts and masks from the analysis engine.
- Daily render limits and demo lock apply as for takes.
- No new model or vendor.

## Decisions marked as mine (the person can overrule)

- Aim on the picture only, not on the target's callout cards (cards only show for the selected
  item, which during a connect is the source).
- A take must be kept (on the canvas) before it can be connected.
- While it renders: a client-only ghost; on failure an error tile with Retry / Dismiss.
- Render slot refunded on model failure too.
- Aiming uses part boxes; masks are fetched in the background to sharpen the highlight.

- The connect dot sits on the selected image's right edge.
- Spot matching by head noun of the part label, on the client.
- A point spot is sized ~20% of the target's shorter edge.
- Paste-then-blend render, since the provider takes one image.
- The result's parent is the target; the source is a new column.
- Images only; one source per result.
- Card text: "Anything to add? (optional)", "Put in", "Cancel".

## Left to the builder

- Exact dot, line and highlight styling within the board's existing palette.
- The prompt wording.
- Where exactly the result lands (reuse `free_slot`).
- Tests (frontend unit + one e2e of connect → card → Put in with the mock provider; backend unit tests
  for spot boxes, the paste, and limits/refund).
