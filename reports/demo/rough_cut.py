"""Cut the demo rough cut (3 minutes max) from the board recordings: title cards, then each board's
best moments — live footage sped up and captioned, and spotlight replay cards (record them with
record_replays.mjs) that frame each step's pictures — then an end card.

    backend/.venv/bin/python reports/demo/rough_cut.py [--false-start PATH]

The fashion board's opening (references, lens, range note) exists only in its first take,
reports/demo/outerwear-false-start/outerwear-false-start.webm (an interrupted recording, kept
local like the other videos).

Writes reports/demo/rough-cut/rough-cut.mp4 (git-ignored). Clip times are seconds into each
recording, read off the step logs (steps.md) and, for car.webm and the fashion opening, from the
steps' created_at against the recording's start. Edit CUT below and run again.
"""

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
OUT = HERE / "rough-cut"
W, H, FPS, SPEED = 1920, 1080, 30, 2.0
FONT = "/System/Library/Fonts/Helvetica.ttc"
INK, PAPER, ACCENT = (24, 24, 27), (236, 239, 242), (44, 72, 168)

# ("card", seconds, title, body)
# | (recording, start_s, length_s, caption)  live recording, sped up SPEED times, captioned
# | ("replay", slug, card_no)  a spotlight replay card (replays/<slug>.webm), held REPLAY_HOLD s;
#   the card carries the step's own narration, so no caption is added
REPLAY_HOLD = 3.8
CUT = [
    ("card", 3, "Muse", "Claude Code works real design boards in Muse, live, through its tools."),
    ("card", 4.5, "Problem 1: curation along dimensions",
     '"Like this one, but different in X." Today\'s tools match overall similarity, so they '
     'cannot hold "keep everything, vary only X".'),
    ("card", 4.5, "Problem 2: a shared design language",
     '"Premium", "clean", "more modern" mean different things to different people. '
     "The board pins them to named dimensions and values from your own references."),

    ("card", 2.5, "1 · A new EV coupe", "Vary one thing, keep the rest. Real run, nothing staged."),
    ("car/car.webm", 17, 12, "Goal first, then references: one new electric coupe in the classic GT language."),
    ("replay", "car", 4), ("replay", "car", 5), ("replay", "car", 6), ("replay", "car", 7),
    ("replay", "car", 8),
    ("car-2/car-2.webm", 218, 14, "Colourways come from exploring the paint: each changes the colour and nothing else."),
    ("replay", "car", 10),
    ("car-3/car-3.webm", 33, 16, "The sheet. Muse checks it is all one car before the run may end."),

    ("card", 2.5, '2 · What "premium" means', "Pin a vague word to dimensions, then design in it."),
    ("ui/ui.webm", 8, 12, 'Goal first. "Premium" means nothing until it is pinned to dimensions and values.'),
    ("replay", "ui", 4), ("replay", "ui", 5), ("replay", "ui", 6),
    ("ui/ui.webm", 238, 10, "The board's own check catches a bad render: three screens where one was asked for."),
    ("replay", "ui", 7), ("replay", "ui", 8), ("replay", "ui", 10), ("replay", "ui", 12),

    ("card", 2.5, "3 · One room, four materials", "Keep the room. Vary only material and palette."),
    ("room/room.webm", 19, 12, "Japanese bones, Danish furniture: references from open collections."),
    ("replay", "room", 2), ("replay", "room", 3), ("replay", "room", 4), ("replay", "room", 5),
    ("room/room.webm", 765, 14, "The anchor and three versions side by side. Only material and palette moved."),
    ("replay", "room", 6),

    ("card", 2.5, "4 · A capsule over two sessions", "Stay in range, and reproduce a look."),
    ("false-start", 474, 14, "Name the range first: four colours and one accent, three cloths, one silhouette family."),
    ("replay", "outerwear", 2), ("replay", "outerwear", 5), ("replay", "outerwear", 6),
    ("outerwear/outerwear.webm", 398, 14, "So looks 2 and 3 are written from the range, each checked against its own words."),
    ("replay", "outerwear-2", 2), ("replay", "outerwear-2", 3),

    ("card", 3, "Every step is a real tool call", "Narrated on the board, and checked by Muse before a run may end."),
]


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT, size)


def card_png(path: Path, title: str, body: str) -> None:
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    d.rectangle([160, 400, 172, 520], fill=ACCENT)
    d.text((210, 380), title, font=font(84), fill=INK)
    y = 500
    for line in textwrap.wrap(body, 58):
        d.text((214, y), line, font=font(42), fill=(70, 72, 80))
        y += 58
    img.save(path)


def caption_png(path: Path, text: str) -> None:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    lines = textwrap.wrap(text, 70)[:3]
    box_h = 36 + 52 * len(lines)
    top = H - 120 - box_h  # above the board's bottom toolbar
    d.rounded_rectangle([120, top, 1380, top + box_h], radius=18, fill=(20, 20, 24, 215))
    for i, line in enumerate(lines):
        d.text((150, top + 18 + 52 * i), line, font=font(38), fill=(250, 250, 250))
    img.save(path)


def run(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--false-start", type=Path, default=HERE / "outerwear-false-start" / "outerwear-false-start.webm",
                   help="the fashion board's first take (has the opening)")
    a = p.parse_args()
    OUT.mkdir(exist_ok=True)
    enc = ["-r", str(FPS), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "20", "-an", "-video_track_timescale", "15360"]
    with tempfile.TemporaryDirectory() as tmp_s:
        tmp = Path(os.environ.get("KEEP_PARTS") or tmp_s)
        tmp.mkdir(exist_ok=True)
        parts = []
        for i, seg in enumerate(CUT):
            part = tmp / f"{i:02d}.mp4"
            if seg[0] == "card":
                _, secs, title, body = seg
                png = tmp / f"{i:02d}.png"
                card_png(png, title, body)
                run("-loop", "1", "-t", str(secs), "-i", str(png), "-vf", f"scale={W}:{H}", *enc, str(part))
            elif seg[0] == "replay":
                _, slug, card_no = seg
                cards = json.loads((HERE / "replays" / f"{slug}.json").read_text())
                at = next(c["t"] for c in cards if c["card"] == card_no) + 0.3  # the pan has settled
                run("-ss", str(at), "-t", str(REPLAY_HOLD), "-i", str(HERE / "replays" / f"{slug}.webm"),
                    "-vf", f"scale={W}:{H}", *enc, str(part))
            else:
                src, start, length, text = seg
                if src == "false-start":
                    if not a.false_start.is_file():
                        print(f"skip {i:02d}: {a.false_start} not found")
                        continue
                    # an interrupted recording has no seek index: decode from the start, trim in the filter
                    inp = ["-i", str(a.false_start)]
                    pick = f"trim=start={start}:duration={length},setpts=PTS-STARTPTS,"
                else:
                    inp = ["-ss", str(start), "-t", str(length), "-i", str(HERE / src)]
                    pick = ""
                cap = tmp / f"{i:02d}-cap.png"
                caption_png(cap, text)
                vf = f"[0:v]{pick}scale={W}:{H},setpts=PTS/{SPEED}[v];[v][1:v]overlay=0:0"
                run(*inp, "-i", str(cap), "-filter_complex", vf, *enc, str(part))
            parts.append(part)
            print(f"{i:02d} done")
        listing = tmp / "parts.txt"
        listing.write_text("".join(f"file '{p}'\n" for p in parts))
        final = tmp / "rough-cut.mp4"
        run("-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(final))
        shutil.move(final, OUT / "rough-cut.mp4")
    print(OUT / "rough-cut.mp4")


if __name__ == "__main__":
    main()
