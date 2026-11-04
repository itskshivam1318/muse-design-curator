"""The Muse trailer, v4: the story from the deck (Figma "Design Exercise" > Story).

    backend/.venv/bin/python reports/demo/trailer/trailer_v4.py

Three stakeholders want one car three ways (heritage, made next year, warm); every tool hands
the designer more images; Muse holds the language in between, and one coupe answers all three.
The words under heritage / next year / warm are Muse's own readings of the references
(GET /api/items/<id>/analysis on the car board); the live shots and their marks come from
shots.mjs; the voiceover is vo4/ (kokoro_vo4.py). Reuses trailer.py's drawing and framing.
Writes out/muse-trailer-v4.mp4 and out/timeline-v4.txt.
"""

import json
import math
import random
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw

from trailer import (ALERT, ENC, HL, INK, OUT, PAPER, W, H, anim, chip, concat, ease, fit,
                     font, framed, img, labels, marker, marks, run, shadowed)

HERE = Path(__file__).resolve().parent
VO = HERE / "vo4"
SHOTS = HERE / "shots"
GREY = (150, 152, 160)
STORY = json.loads((SHOTS / "story.check.json").read_text())


def takes_landed(t: float) -> Image.Image:
    """The two takes the agent kept in the story shot, with their own checks (shots/story.check.json)."""
    c = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(c)
    d.text((110, 70), "Landed on the board: darker, and nothing else changed", font=font(52, True), fill=INK)
    for k, (asset, take) in enumerate(zip(["story_moss", "story_fern"], STORY["chat_takes"])):
        a = ease((t - 0.3 - k * 0.4) / 0.5)
        if a <= 0:
            continue
        x = 110 + k * 870
        shadowed(c, fit(img(asset), 820, 546), (x, int(190 + 30 * (1 - a))))
        ck = take["check"]
        chip(d, x, 770, take["option"], 40, fill=INK, ink=HL)
        if t > 1.4 + k * 0.4:
            chip(d, x, 860, f"held {ck['kept']} of {ck['of']} · nothing else moved", 36)
    return c

# ---------------------------------------------------------------- the hook: three voices


def hook_quote(who: str, quote: str, photo: str, tag: str):
    def frame(t: float) -> Image.Image:
        c = Image.new("RGB", (W, H), (14, 14, 17))
        d = ImageDraw.Draw(c)
        d.text((140, 250), who, font=font(36), fill=GREY)
        shown = quote[: int(len(quote) * ease(t / 2.6))]
        for k, line in enumerate(textwrap.wrap(shown, 26)):
            d.text((140, 320 + k * 92), line, font=font(76, True), fill=(245, 245, 247))
        a = ease((t - 0.8) / 0.8)
        if a > 0:
            pic = fit(img(photo), 620, 460)
            pic = Image.blend(Image.new("RGB", pic.size, (14, 14, 17)), pic, a)
            c.paste(pic, (1180, 300))
            if t > 1.6:
                chip(d, 1180, 790, tag, 40)
        return c
    return frame


def nothing(t: float) -> Image.Image:
    c = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(c)
    for k, (photo, tag) in enumerate([("etype", "heritage"), ("taycan", "made next year"), ("seats_wood", "warm")]):
        shadowed(c, fit(img(photo), 520, 360), (150 + k * 560, 200))
        chip(d, 150 + k * 560, 590, tag, 40, fill=INK, ink=HL)
    if t > 0.5:
        q = "What do they have in common?"
        f = font(64, True)
        d.text(((W - d.textlength(q, font=f)) / 2, 720), q, font=f, fill=INK)
    if t > 2.6:
        f = font(120, True)
        d.text(((W - d.textlength("Nothing.", font=f)) / 2, 830), "Nothing.", font=f, fill=ALERT)
    return c


CARS = ["etype", "aston", "lusso", "lancia", "polestar", "taycan", "rosso", "midnight", "cream", "anchor"]


def regenerate(t: float) -> Image.Image:
    """A generic prompt-and-regenerate tool (no real product's look): more images, never the one."""
    c = Image.new("RGB", (W, H), (18, 18, 22))
    d = ImageDraw.Draw(c)
    prompt = "a new coupe for a 70-year-old brand: heritage, made next year, warm"
    shown = prompt[: int(len(prompt) * ease(t / 1.6))]
    d.rounded_rectangle([200, 60, 1560, 150], 45, fill=(40, 40, 48))
    d.text((250, 84), shown, font=font(36), fill=(230, 230, 235))
    rounds = int(max(0.0, t - 1.6) / 1.9)
    rng = random.Random(rounds)
    names = rng.sample(CARS, 4) if rounds else ["anchor", "rosso", "etype", "aston"]
    for k, n in enumerate(names):
        tile = fit(img(n), 540, 340)
        c.paste(tile, (330 + (k % 2) * 580, 200 + (k // 2) * 380))
    pulse = 1 + 0.06 * math.sin(t * 9) if t > 1.6 else 1
    bw, bh = int(250 * pulse), int(74 * pulse)
    d.rounded_rectangle([1590, 70, 1590 + bw, 70 + bh], 37, fill=(90, 90, 110))
    d.text((1612, 86), "Regenerate", font=font(36, True), fill=(255, 255, 255))
    if rounds:
        d.text((1610, 170), f"x{rounds}", font=font(40, True), fill=GREY)
    if t > 6.0:
        chip(d, 560, 980, "a supermarket of almost-right", 46, fill=ALERT, ink=(255, 255, 255))
    return c


def turn(t: float) -> Image.Image:
    c = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(c)
    d.text((160, 330), "She doesn't need more images.", font=font(80, True), fill=INK)
    marker(d, 160, 500, "push the ones she trusts in one direction", t - 2.2, 56)
    marker(d, 160, 610, "without losing the other two", t - 4.2, 56, fill=INK, ink=HL)
    return c


def positioning(t: float) -> Image.Image:
    c = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(c)
    for cx, text, at in [(420, "Boards\nhold images", 0.2), (1500, "AI\nmakes images", 1.4)]:
        if t > at:
            d.ellipse([cx - 230, 310, cx + 230, 770], fill=(214, 216, 222))
            for k, line in enumerate(text.split("\n")):
                f = font(52, True)
                d.text((cx - d.textlength(line, font=f) / 2, 480 + k * 66), line, font=f, fill=INK)
    if t > 2.6:
        d.line([650, 540, 1270, 540], fill=(170, 172, 180), width=4)
        for k, line in enumerate(["Muse holds", "the language", "in between"]):
            f = font(58, True)
            w = d.textlength(line, font=f)
            d.rounded_rectangle([960 - w / 2 - 20, 410 + k * 84, 960 + w / 2 + 20, 410 + k * 84 + 74], 10, fill=HL)
            d.text((960 - w / 2, 418 + k * 84), line, font=f, fill=INK)
    return c


# Muse's own readings (dimension values) of each reference, from the car board's analyses.
READINGS = [
    ("heritage", "etype", ["very long low bonnet", "upright oval round lamp", "fastback, rounded roof"]),
    ("made next year", "taycan", ["smooth fastback, short tail", "large multi-spoke alloy", "dark tinted glass"]),
    ("warm", "seats_wood", ["warm tan leather", "thin wood-rim wheel", "warm, luxurious, calm"]),
]


def read_refs(t: float) -> Image.Image:
    c = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(c)
    d.text((140, 60), "What each word actually means, read off the references", font=font(48, True), fill=INK)
    for k, (word, photo, values) in enumerate(READINGS):
        x = 140 + k * 570
        shadowed(c, fit(img(photo), 500, 330), (x, 170))
        chip(d, x, 530, word, 46, fill=INK, ink=HL)
        for j, v in enumerate(values):
            at = 2.0 + k * 3.2 + j * 0.6
            if t > at:
                marker(d, x, 640 + j * 100, v, t - at, 38)
    return c


VIEWS = [("anchor", "front 3/4"), ("side", "side"), ("rear", "rear"), ("dash_wood", "dashboard"), ("seats_wood", "seats")]


def every_view(t: float) -> Image.Image:
    c = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(c)
    shadowed(c, fit(img("anchor"), 860, 574), (110, 250))
    chip(d, 126, 760, "front 3/4", 36, fill=INK, ink=HL)
    for k, (photo, tag) in enumerate(VIEWS[1:]):
        if t < 0.8 + k * 0.7:
            continue
        x, y = 1040 + (k % 2) * 400, 140 + (k // 2) * 420
        shadowed(c, fit(img(photo), 370, 247), (x, y))
        chip(d, x + 10, y + 260, tag, 32, fill=INK, ink=HL)
    if t > 3.8:
        chip(d, 110, 900, "one car, in every view", 46)
    return c


# Muse's readings of the final coupe (anchor) and its cabin (seats view): the three asks, answered.
ANSWERED = [
    ("heritage", ["long bonnet, set-back cabin, fastback rear", "paired round lamps, teardrop housing"]),
    ("made next year", ["small horizontal oval slot", "large silver multi-spoke turbine discs"]),
    ("warm", ["warm tan leather with green piping", "thin-rimmed wood-rim wheel"]),
]


def answer(t: float) -> Image.Image:
    c = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(c)
    shadowed(c, fit(img("anchor"), 900, 600), (110, 150))
    shadowed(c, fit(img("seats_wood"), 420, 280), (110 + 900 - 420 - 20, 150 + 600 - 280 - 20))
    for k, (word, values) in enumerate(ANSWERED):
        at = 0.6 + k * 1.2
        if t < at:
            continue
        y = 160 + k * 270
        w = chip(d, 1080, y, word, 46, fill=INK, ink=HL)
        tx, ty = 1080 + w + 22, y + 14  # a drawn tick (the font has no check mark)
        d.line([tx, ty + 22, tx + 14, ty + 38, tx + 42, ty + 4], fill=(40, 150, 80), width=9, joint="curve")
        for j, v in enumerate(values):
            marker(d, 1080, y + 84 + j * 78, v, t - at - 0.3 - j * 0.2, 32)
    return c


def close(t: float) -> Image.Image:
    c = Image.new("RGB", (W, H), (14, 14, 17))
    d = ImageDraw.Draw(c)
    s = "Agencies are drowning in generic AI slop."
    f = font(60, True)
    if t < 5.0:
        d.text(((W - d.textlength(s, font=f)) / 2, 470), s, font=f, fill=(235, 236, 240))
        return c
    f = font(140, True)
    d.text(((W - d.textlength("Muse", font=f)) / 2, 380), "Muse", font=f, fill=(255, 255, 255))
    if t > 5.8:
        s = "Explore. Don't regenerate."
        f = font(64, True)
        d.text(((W - d.textlength(s, font=f)) / 2, 590), s, font=f, fill=HL)
    if t > 6.6:
        s = "Taste, for AI exploration. Real boards, real runs."
        f = font(34)
        d.text(((W - d.textlength(s, font=f)) / 2, 700), s, font=f, fill=GREY)
    return c


# ---------------------------------------------------------------- assembly


def secs_of(p: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp_s:
        tmp = Path(tmp_s)
        beats: list[tuple[str, str, list[Path]]] = []
        n = 0

        def part() -> Path:
            nonlocal n
            n += 1
            return tmp / f"{n:03d}.mp4"

        def drawn(vo: str, label: str, secs: float, frame) -> None:
            p = part()
            anim(p, secs, frame)
            beats.append((vo, label, [p]))

        drawn("h1", "Hook: the brand director (heritage)", 5.6,
              hook_quote("Brand director, at kickoff", "“We're a 70-year-old company. Heritage is the whole point.”",
                         "etype", "heritage"))
        drawn("h2", "Hook: the marketing head (made next year)", 6.1,
              hook_quote("Marketing head, two minutes later",
                         "“If it looks old, we're dead. It has to feel like it was made next year.”", "taycan",
                         "made next year"))
        drawn("h3", "Hook: the CEO (warm)", 5.2,
              hook_quote("CEO, in the lift", "“And warm. People should feel something. Our competitors are cold.”",
                         "seats_wood", "warm"))
        drawn("n1", "What do they have in common? Nothing.", 5.2, nothing)
        drawn("n2", "The supermarket: type, regenerate, regenerate", 11.8, regenerate)
        drawn("n3", "The turn: push what she trusts, keep the other two", 8.8, turn)
        drawn("n4", "Positioning: the language in between", 7.0, positioning)
        drawn("n5", "Muse reads what each word means (real readings)", 14.6, read_refs)

        # n6 LIVE: the board glides in on the coupe; its parts light up (shots/story.webm, real board zoom)
        m = marks("story")
        story = SHOTS / "story.webm"
        p = part()
        framed(p, story, m["zoom-in"] - 0.8, m["part-headlamps"] + 2.6 - (m["zoom-in"] - 0.8), push=0.03,
               tag="LIVE · on the board",
               overlay=labels([(3.2, lambda d, t: marker(d, 240, 985, "pick the coupe: every part, read", t)),
                               (4.6, lambda d, t: marker(d, 1080, 985, "wheels · lamps · bonnet", t, fill=INK, ink=HL))]))
        beats.append(("n6", "LIVE: the board zooms in on the coupe; its parts light up", [p]))
        drawn("n7", "It holds in every view", 7.0, every_view)

        # n8 LIVE: the curveball, asked on the board (same take; the chat panel floats, so the cut zooms on it)
        chat = (1.0, 1.0, 1.9)
        ps = [part(), part(), part(), part()]
        framed(ps[0], story, m["ask"] - 0.3, m["sent"] - m["ask"] + 1.3, focus=chat, push=0.05,
               tag="LIVE · the client changes their mind")
        asked = m["answered"] + 1.5
        framed(ps[1], story, m["sent"] + 1.0, 4.0, speed=max(1.0, (asked - m["sent"] - 1.0) / 4.0), focus=chat, push=0.04,
               overlay=labels([(0.6, lambda d, t: marker(d, 240, 985, "not sure? it asks", t))]))
        framed(ps[2], story, asked, 3.5, speed=max(1.0, (m["landed"] + 2 - asked) / 3.5), focus=chat, push=0.04,
               overlay=labels([(0.4, lambda d, t: marker(d, 240, 985, "each step lands on the board", t))]))
        anim(ps[3], 4.2, takes_landed)
        beats.append(("n8", "LIVE: 'make it darker', it asks, two takes land", ps))

        # n9 LIVE: change one thing yourself: the wheels (same take: explore, pick, draw, keep, zoom back out)
        near_card = (1.0, 0.5, 1.6)  # the petal card, right of the coupe
        ps = [part(), part(), part(), part(), part()]
        framed(ps[0], story, m["part-headlamps"] + 2.6, 3.2,
               speed=max(1.0, (m["petals"] + 0.6 - m["part-headlamps"] - 2.6) / 3.2), push=0.04,
               tag="LIVE · change one thing",
               overlay=labels([(0.3, lambda d, t: marker(d, 240, 985, "explore: wheel design", t))]))
        framed(ps[1], story, m["petals"] + 0.6, m["render"] - m["petals"] + 0.2, focus=near_card, push=0.04,
               overlay=labels([(0.3, lambda d, t: marker(d, 240, 985, "pick one option", t))]))
        framed(ps[2], story, m["render"] + 0.8, 2.6, speed=max(1.0, (m["checked"] - m["render"] - 0.8) / 2.6),
               focus=near_card, push=0.03,
               overlay=labels([(0.3, lambda d, t: marker(d, 240, 985, "Muse draws only the wheels", t))]))
        framed(ps[3], story, m["checked"] + 0.3, m["zoom-out"] - m["checked"] - 0.3, focus=near_card, push=0.05,
               overlay=labels([(0.5, lambda d, t: marker(d, 240, 985, "kept · on the board", t))]))
        framed(ps[4], story, m["zoom-out"], m["board-again"] + 0.8 - m["zoom-out"], push=0.0,
               overlay=labels([(0.6, lambda d, t: marker(d, 240, 985, "and back to the whole board", t, fill=INK, ink=HL))]))
        beats.append(("n9", "LIVE: explore the wheels, draw one, keep it, zoom out", ps))

        drawn("n10", "The answer: one car, all three asks", 7.0, answer)
        drawn("n11", "Close: taste for AI exploration", 11.0, close)

        timeline, video_parts, audio_at = [], [], []
        clock = 0.0
        for vo, label, parts in beats:
            secs = sum(secs_of(x) for x in parts)
            need = secs_of(VO / f"{vo}.wav") + 0.8
            if secs < need:  # hold the last frame until the voice has finished
                pad = part()
                run("-sseof", "-0.05", "-i", str(parts[-1]), "-frames:v", "1", str(pad.with_suffix(".png")))
                run("-loop", "1", "-t", str(need - secs), "-i", str(pad.with_suffix(".png")), *ENC, str(pad))
                parts = [*parts, pad]
                secs = need
            audio_at.append((vo, clock + 0.25))
            timeline.append(f"{int(clock // 60)}:{clock % 60:04.1f}  {secs:4.1f}s  {label}")
            video_parts += parts
            clock += secs

        silent = tmp / "video.mp4"
        concat(video_parts, silent)
        inputs, chains = [], []
        for k, (vo, at) in enumerate(audio_at):
            inputs += ["-i", str(VO / f"{vo}.wav")]
            chains.append(f"[{k + 1}:a]adelay={int(at * 1000)}|{int(at * 1000)}[a{k}]")
        nv = len(audio_at)
        mix = ";".join(chains) + ";" + "".join(f"[a{k}]" for k in range(nv)) + f"amix=inputs={nv}:normalize=0[vo]"
        whoosh = tmp / "whoosh.wav"
        run("-f", "lavfi", "-i", "anoisesrc=d=0.7:c=pink:a=0.6", "-af",
            "highpass=f=400,lowpass=f=2800,afade=t=in:d=0.35,afade=t=out:st=0.35:d=0.35,volume=0.18", str(whoosh))
        cuts = [at - 0.25 for _, at in audio_at[1:]]
        for k, at in enumerate(cuts):
            inputs += ["-i", str(whoosh)]
            ms = int(max(0.0, at - 0.3) * 1000)
            mix += f";[{nv + 1 + k}:a]adelay={ms}|{ms}[w{k}]"
        mix += ";" + "".join(f"[w{k}]" for k in range(len(cuts))) + f"amix=inputs={len(cuts)}:normalize=0[sfx]"
        mix += (f";[vo][sfx]amix=inputs=2:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11,"
                f"apad=whole_dur={clock:.2f}[aout]")
        final = tmp / "muse-trailer-v4.mp4"
        run("-i", str(silent), *inputs, "-filter_complex", mix + ";[0:v]noise=alls=5:allf=t[vout]",
            "-map", "[vout]", "-map", "[aout]", *ENC, "-c:a", "aac", "-b:a", "192k", "-t", f"{clock:.2f}",
            "-movflags", "+faststart", str(final))
        shutil.move(final, OUT / "muse-trailer-v4.mp4")
        (OUT / "timeline-v4.txt").write_text("\n".join(timeline) + f"\n{int(clock // 60)}:{clock % 60:04.1f}  end\n")
    print(OUT / "muse-trailer-v4.mp4")
    print((OUT / "timeline-v4.txt").read_text())


if __name__ == "__main__":
    main()
