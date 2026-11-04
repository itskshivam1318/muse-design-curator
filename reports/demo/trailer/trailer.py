"""The Muse trailer (Vox-style, voiceover, under 3 minutes).

    backend/.venv/bin/python reports/demo/trailer/trailer.py

Each beat is a motion graphic drawn here (Pillow frames piped to ffmpeg), a live UI shot
(shots/, from shots.mjs) or a spotlight replay card (../replays/, from record_replays.mjs), with
labels laid over it. The voiceover (vo/NN.wav from Kokoro via vo/kokoro_vo.py, else vo/NN.aiff from `say`) starts at its beat's start; a beat is
as long as its pictures or its voiceover plus a beat of air, whichever is longer.
Writes reports/demo/trailer/out/muse-trailer.mp4 (git-ignored) and out/timeline.txt.
"""

import json
import math
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
DEMO = HERE.parent
A = HERE / "assets"
OUT = HERE / "out"
W, H, FPS = 1920, 1080, 30
FONT = "/System/Library/Fonts/Helvetica.ttc"
INK, PAPER, ACCENT, ALERT = (20, 20, 24), (238, 240, 243), (44, 72, 168), (214, 64, 52)
HL = (255, 214, 64)  # Vox yellow
ENC = ["-r", str(FPS), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "19",
       "-video_track_timescale", "15360"]


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT, size, index=1 if bold else 0)


def img(name: str) -> Image.Image:
    return Image.open(A / f"{name}.img").convert("RGB")


def fit(im: Image.Image, w: int, h: int) -> Image.Image:
    """Cover-crop to w x h."""
    r = max(w / im.width, h / im.height)
    im = im.resize((round(im.width * r), round(im.height * r)), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def ease(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return 1 - (1 - t) ** 3


def shadowed(canvas: Image.Image, im: Image.Image, xy: tuple[int, int], radius: int = 18) -> None:
    sh = Image.new("RGBA", (im.width + 60, im.height + 60), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([30, 36, 30 + im.width, 36 + im.height], radius, fill=(0, 0, 0, 90))
    sh = sh.filter(ImageFilter.GaussianBlur(14))
    canvas.paste(sh, (xy[0] - 30, xy[1] - 30), sh)
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, im.width - 1, im.height - 1], radius, fill=255)
    canvas.paste(im, xy, mask)


def chip(d: ImageDraw.ImageDraw, x: int, y: int, text: str, size: int = 40, fill=HL, ink=INK) -> int:
    f = font(size, True)
    w = int(d.textlength(text, font=f))
    d.rounded_rectangle([x, y, x + w + 40, y + size + 26], 10, fill=fill)
    d.text((x + 20, y + 11), text, font=f, fill=ink)
    return w + 40


def label_png(path: Path, items: list[tuple[int, int, str, tuple[int, int] | None]], tag: str | None = None) -> None:
    """Vox-style labels over a shot: yellow chips with an optional pointer line to a spot."""
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if tag:
        chip(d, 60, 70, tag, 46, fill=INK, ink=HL)
    for x, y, text, to in items:
        if to:
            d.line([x + 20, y + 30, to[0], to[1]], fill=HL, width=6)
            d.ellipse([to[0] - 12, to[1] - 12, to[0] + 12, to[1] + 12], outline=HL, width=6)
        chip(d, x, y, text)
    im.save(path)


# ---------------------------------------------------------------- rendering helpers


def run(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def anim(path: Path, secs: float, frame: Callable[[float], Image.Image]) -> None:
    p = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-", *ENC, str(path)],
        stdin=subprocess.PIPE,
    )
    assert p.stdin
    for i in range(round(secs * FPS)):
        p.stdin.write(frame(i / FPS).convert("RGB").tobytes())
    p.stdin.close()
    if p.wait():
        raise RuntimeError(f"ffmpeg failed on {path}")


def clip(path: Path, src: Path, start: float, secs: float, overlay: Path | None = None,
         zoom: float = 1.0, speed: float = 1.0, overlay_from: float = 0.0) -> None:
    """A piece of a recording, optionally zoomed into the centre, sped up, with a label overlay."""
    v = f"[0:v]setpts=PTS/{speed},"
    if zoom != 1.0:
        v += f"crop=iw/{zoom}:ih/{zoom},"
    v += f"scale={W}:{H},fade=t=in:d=0.25[v]"
    if overlay:
        graph = f"{v};[1:v]format=rgba,fade=t=in:st={overlay_from}:d=0.3:alpha=1[o];[v][o]overlay=0:0"
        run("-ss", str(start), "-t", str(secs * speed), "-i", str(src), "-loop", "1", "-t", str(secs), "-i", str(overlay),
            "-filter_complex", graph, "-t", str(secs), *ENC, str(path))
    else:
        run("-ss", str(start), "-t", str(secs * speed), "-i", str(src), "-filter_complex", v, "-map", "[v]",
            "-t", str(secs), *ENC, str(path))


def replay(path: Path, slug: str, card: int, secs: float = 3.8, overlay: Path | None = None) -> None:
    cards = json.loads((DEMO / "replays" / f"{slug}.json").read_text())
    at = next(c["t"] for c in cards if c["card"] == card) + 0.3
    clip(path, DEMO / "replays" / f"{slug}.webm", at, secs, overlay)


def concat(parts: list[Path], out: Path) -> None:
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{p}'\n" for p in parts))
    run("-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out))


# ---------------------------------------------------------------- the beats


def cold_open(t: float) -> Image.Image:
    """A generic prompt-and-re-roll image tool (no real product's look)."""
    c = Image.new("RGB", (W, H), (18, 18, 22))
    d = ImageDraw.Draw(c)
    prompt = "a vintage coupe, long bonnet, round lamps"
    shown = prompt[: int(len(prompt) * ease(t / 1.8))]
    d.rounded_rectangle([360, 70, 1560, 160], 45, fill=(40, 40, 48))
    d.text((410, 96), shown + ("|" if t < 2.2 and int(t * 3) % 2 == 0 else ""), font=font(40), fill=(230, 230, 235))
    rerolled = t >= 7.6
    names = ["lusso", "lancia", "polestar", "midnight"] if rerolled else ["anchor", "rosso", "etype", "aston"]
    t0 = 7.6 if rerolled else 2.0
    for k, n in enumerate(names):
        a = ease((t - t0 - k * 0.15) / 0.5)
        if a <= 0:
            continue
        tile = fit(img(n), 560, 380)
        x, y = 380 + (k % 2) * 600, 210 + (k // 2) * 420
        if a < 1:
            tile = Image.blend(Image.new("RGB", tile.size, (18, 18, 22)), tile, a)
        c.paste(tile, (x, y))
    if 4.6 <= t < 7.6:  # the close one: its wheels are wrong
        d.ellipse([380 + 175, 210 + 220, 380 + 305, 210 + 350], outline=ALERT, width=8)
        chip(d, 380 + 300, 210 + 300, "wheels wrong", 38, fill=ALERT, ink=(255, 255, 255))
    if 6.4 <= t < 8.0:
        pulse = 1 + 0.06 * math.sin((t - 6.4) * 12)
        bw, bh = int(220 * pulse), int(74 * pulse)
        d.rounded_rectangle([1590, 80, 1590 + bw, 80 + bh], 37, fill=(90, 90, 110))
        d.text((1620, 96), "Re-roll", font=font(38, True), fill=(255, 255, 255))
    if t >= 9.2:
        chip(d, 700, 975, "wheels right... everything else changed", 44, fill=ALERT, ink=(255, 255, 255))
    return c


def title(t: float, line1: str, line2: str | None, secs: float) -> Image.Image:
    c = Image.new("RGB", (W, H), INK)
    d = ImageDraw.Draw(c)
    a = ease(t / 0.6) * (1 - ease((t - secs + 0.4) / 0.4))
    col = tuple(int(255 * a + 20 * (1 - a)) for _ in range(3))
    f = font(76, True)
    d.text(((W - d.textlength(line1, font=f)) / 2, 440), line1, font=f, fill=col)
    if line2 and t > 1.6:
        b = ease((t - 1.6) / 0.5) * (1 - ease((t - secs + 0.4) / 0.4))
        f2 = font(130, True)
        hl = tuple(int(HL[i] * b + 20 * (1 - b)) for i in range(3))
        d.text(((W - d.textlength(line2, font=f2)) / 2, 560), line2, font=f2, fill=hl)
    return c


WATCHES = ["itm_01m5yt65wnvpfjq3sfs1bbzd48", "itm_01m5yt65x1a7c7v4wrsb4rwfg3", "itm_01m5yt65xj0m0jhb19sep580rr",
           "itm_01m5yt65xrdqpdephe0pw36w15", "itm_01m5yt65xx5y127t514va8c1ff"]
SHARED = ["Matte black dial  9 of 12", "Arabic numerals  8 of 13", "Steel case  7 of 8", "Leather strap  9 of 10"]


def in_common(t: float) -> Image.Image:
    c = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(c)
    for k, n in enumerate(WATCHES):
        a = ease((t - k * 0.35) / 0.6)
        if a <= 0:
            continue
        tile = fit(Image.open(A / "watch" / f"{n}.img").convert("RGB"), 320, 320)
        shadowed(c, tile, (110 + k * 345, int(200 + 60 * (1 - a))))
    if t > 2.2:
        q = "What do they have in common?"
        f = font(64, True)
        d.text(((W - d.textlength(q, font=f)) / 2, 80), q, font=f, fill=INK)
    for k, s in enumerate(SHARED):
        if t > 5.2 + k * 0.7:
            x = 130 + (k % 2) * 840
            y = 640 + (k // 2) * 120
            chip(d, x, y, s, 46)
    if t > 5.0:
        d.text((130, 900), "Read off the references by Muse: dimensions, not a vague style.", font=font(36), fill=(80, 82, 90))
    return c


def two_kinds(t: float) -> Image.Image:
    c = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(c)
    d.text((140, 260), "Two kinds of dimension", font=font(80, True), fill=INK)
    if t > 0.6:
        chip(d, 140, 430, "PHYSICAL", 60, fill=INK, ink=HL)
        d.text((520, 445), "lives in a part: a wheel, a lamp, a sofa", font=font(48), fill=INK)
    if t > 1.4:
        chip(d, 140, 580, "ABSTRACT", 60, fill=INK, ink=HL)
        d.text((520, 595), "reads the whole picture: mood, warmth, premium", font=font(48), fill=INK)
    return c


def only_this_changed(t: float) -> Image.Image:
    c = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(c)
    names = ["room0", "room1", "room2", "room3"]
    tags = ["anchor", "smoked oak · charcoal", "walnut · terracotta", "white ash · sage"]
    for k, n in enumerate(names):
        a = ease((t - k * 0.3) / 0.5)
        if a <= 0:
            continue
        tile = fit(img(n), 780, 420)
        x, y = 150 + (k % 2) * 840, 90 + (k // 2) * 480
        shadowed(c, tile, (x, y))
        chip(d, x + 16, y + 352, tags[k], 34, fill=HL if k else INK, ink=INK if k else HL)
    if t > 2.2:
        chip(d, 520, 990, "changed: material & palette      held: camera, layout, every piece", 34, fill=INK, ink=HL)
    return c


def muse_code_prompt(t: float) -> Image.Image:
    c = Image.new("RGB", (W, H), (14, 15, 19))
    d = ImageDraw.Draw(c)
    d.rounded_rectangle([260, 300, 1660, 780], 24, fill=(28, 30, 37))
    for k, col in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([300 + k * 40, 330, 324 + k * 40, 354], fill=col)
    d.text((440, 326), "Muse Code", font=font(32, True), fill=(160, 164, 176))
    ask = "make this home screen more premium"
    shown = ask[: int(len(ask) * ease((t - 0.3) / 1.8))]
    d.text((320, 440), ">", font=font(52, True), fill=HL)
    d.text((370, 440), shown, font=font(52), fill=(236, 238, 242))
    if t > 2.3:
        d.text((370, 560), "add_dimension  Premium feel  (abstract)", font=font(38), fill=(140, 200, 150))
    if t > 2.8:
        d.text((370, 620), "explore  premium_feel  ->  visualize  ->  keep", font=font(38), fill=(140, 200, 150))
    return c


def put_into(t: float) -> Image.Image:
    c = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(c)
    src = fit(img("taycan"), 560, 270)
    shadowed(c, src, (120, 140))
    chip(d, 140, 430, "source: the Taycan", 36, fill=INK, ink=HL)
    before, after = fit(img("anchor"), 1020, 680), fit(img("put"), 1020, 680)
    x0, y0 = 780, 200
    wipe = ease((t - 1.8) / 1.6)
    frame = before.copy()
    cut = int(1020 * wipe)
    if cut:
        frame.paste(after.crop((0, 0, cut, 680)), (0, 0))
    shadowed(c, frame, (x0, y0))
    if 0.6 < t:
        a = ease((t - 0.6) / 0.6)
        ex = int(680 + (x0 + 440 - 680) * a)
        d.line([690, 280, ex, y0 + 470], fill=HL, width=8)
    if cut and cut < 1020:
        d.line([x0 + cut, y0, x0 + cut, y0 + 680], fill=HL, width=6)
    if t > 3.6:
        d.ellipse([x0 + 370, y0 + 410, x0 + 600, y0 + 640], outline=HL, width=8)
        chip(d, x0 + 40, y0 + 700, "wheel design: silver turbine  ->  Taycan aero", 40)
        chip(d, x0 + 40, y0 + 790, "nothing else moved", 40, fill=INK, ink=HL)
    return c


EXPLORE_OPTIONS = ["smoked oak · charcoal", "walnut · terracotta clay", "white ash · sage", "all blonde, tonal",
                   "honey oak · black stone", "raw clay · bamboo", "ebonised · moonlit"]
PICKED = {0, 1, 2}


def explore_options(t: float) -> Image.Image:
    c = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(c)
    anchor = fit(img("room0"), 760, 506)
    shadowed(c, anchor, ((W - 760) // 2, 250))
    chip(d, (W - 760) // 2 + 16, 250 + 440, "anchor", 34, fill=INK, ink=HL)
    d.text((140, 80), "explore:", font=font(44), fill=(90, 92, 100))
    chip(d, 330, 70, "material & palette", 44, fill=INK, ink=HL)
    spots = [(120, 260), (120, 420), (120, 580), (120, 740), (1400, 300), (1400, 480), (1400, 660)]
    for k, name in enumerate(EXPLORE_OPTIONS):
        if t < 0.8 + k * 0.35:
            continue
        x, y = spots[k]
        picked = t > 4.2 and k in PICKED
        dim = t > 4.2 and k not in PICKED
        chip(d, x, y, name, 36, fill=HL if picked else ((215, 217, 222) if dim else (255, 255, 255)),
             ink=(150, 152, 160) if dim else INK)
    if t > 4.6:
        chip(d, 610, 900, "drawn: the three picked. Everything else held.", 38, fill=INK, ink=HL)
    return c


def premium_before_after(t: float) -> Image.Image:
    c = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(c)
    before, after = fit(img("home"), 430, 900), fit(img("premium"), 430, 900)
    shadowed(c, before, (380, 90))
    chip(d, 380, 1000 - 60, "before", 34, fill=INK, ink=HL)
    a = ease((t - 0.6) / 0.6)
    if a > 0:
        shadowed(c, after, (1110, int(90 + 40 * (1 - a))))
        chip(d, 1110, 1000 - 60, "premium feel  up", 34)
    if t > 1.6:
        d.text((860, 380), "->", font=font(110, True), fill=ACCENT)
    if t > 2.4:
        chip(d, 610, 30, "same layout · same balance · same card · same rows", 34, fill=INK, ink=HL)
    return c


def over_time(t: float) -> Image.Image:
    c = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(c)
    looks = ["look1", "look2", "look3", "look4", "look5"]
    for k, n in enumerate(looks):
        a = ease((t - k * 0.25) / 0.5)
        if a <= 0:
            continue
        tile = fit(img(n), 300, 450)
        shadowed(c, tile, (110 + k * 330, 150))
    chip(d, 110, 640, "session 1", 36, fill=INK, ink=HL)
    chip(d, 770, 640, "session 2", 36, fill=INK, ink=HL)
    if t > 2.6:
        ink = fit(img("ink"), 300, 450)
        shadowed(c, ink, (1500, 150 + 0))
        d.rectangle([1490, 140, 1810, 610], outline=HL, width=8)
        chip(d, 1220, 700, "look 1, second colour", 40)
    if t > 3.4:
        chip(d, 110, 820, "one range: stone · camel · olive · moss, one rust accent", 40)
    return c


def end_card(t: float) -> Image.Image:
    c = title(t, "Muse", None, 99)
    d = ImageDraw.Draw(c)
    if t > 0.8:
        s = "Explore. Don't re-roll."
        f = font(64, True)
        d.text(((W - d.textlength(s, font=f)) / 2, 580), s, font=f, fill=HL)
    if t > 1.6:
        s = "Real boards, real runs: Muse Code over Muse's own tools."
        f = font(34)
        d.text(((W - d.textlength(s, font=f)) / 2, 700), s, font=f, fill=(170, 172, 180))
    return c


# ---------------------------------------------------------------- assembly


def vo_file(n: str) -> Path:
    """The Kokoro take (vo/NN.wav) if there is one, else the macOS `say` take (vo/NN.aiff)."""
    wav = HERE / "vo" / f"{n}.wav"
    return wav if wav.is_file() else HERE / "vo" / f"{n}.aiff"


def vo_secs(n: str) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                        str(vo_file(n))], capture_output=True, text=True, check=True)
    return float(r.stdout)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    shots = HERE / "shots"
    with tempfile.TemporaryDirectory() as tmp_s:
        tmp = Path(tmp_s)
        beats: list[tuple[str, str, list[Path]]] = []  # (vo id, label, parts)
        n = 0

        def part() -> Path:
            nonlocal n
            n += 1
            return tmp / f"{n:03d}.mp4"

        # 1 cold open
        p = part(); anim(p, 12.5, cold_open); beats.append(("01", "Cold open: prompt, re-roll, everything changes", [p]))
        # 2 title
        p = part(); anim(p, 4.6, lambda t: title(t, "What if you could change just one thing?", "Muse", 4.6))
        beats.append(("02", "Title", [p]))
        # 3 what's in common
        p = part(); anim(p, 11.5, in_common); beats.append(("03", "What do they have in common? (watches)", [p]))
        # 4 two kinds: card, car physical, room abstract
        ps = [part(), part(), part()]
        anim(ps[0], 3.0, two_kinds)
        lab = tmp / "lab-phys.png"
        label_png(lab, [(1240, 300, "wheels · wheel design", None), (1240, 400, "headlamps · lamp form", None),
                        (1240, 500, "front panel · intake form", None)], tag="PHYSICAL · lives in a part")
        clip(ps[1], shots / "car-physical.webm", 7.5, 8.5, lab, zoom=1.25, overlay_from=0.8)
        lab2 = tmp / "lab-abs.png"
        label_png(lab2, [(150, 760, "mood & atmosphere", None), (150, 860, "material palette harmony", None)],
                  tag="ABSTRACT · reads the whole picture")
        clip(ps[2], shots / "room-abstract.webm", 6.5, 8.0, lab2, zoom=1.15, overlay_from=0.8)
        beats.append(("04", "Two kinds of dimension: physical (car), abstract (room)", ps))
        # 5 explore one dimension (interior)
        ps = [part(), part()]
        anim(ps[0], 7.0, explore_options); anim(ps[1], 8.5, only_this_changed)
        beats.append(("05", "Change one thing: explore material & palette (interior)", ps))
        # 6 Muse Code: say a word (UI)
        ps = [part(), part(), part()]
        anim(ps[0], 3.6, muse_code_prompt)
        cards = json.loads((DEMO / "replays" / "ui-premium.json").read_text())
        at = next(c["t"] for c in cards if c["card"] == 2) + 0.3
        clip(ps[1], DEMO / "replays" / "ui-premium.webm", at, 4.2, zoom=1.6)
        anim(ps[2], 6.0, premium_before_after)
        beats.append(("06", "Muse Code: 'make it more premium' adds an abstract dimension (UI)", ps))
        # 7 put this into that (car)
        p = part(); anim(p, 8.5, put_into); beats.append(("07", "Put this into that: the Taycan wheel (car)", [p]))
        # 8 over time (fashion)
        p = part(); anim(p, 8.5, over_time); beats.append(("08", "It holds over time (fashion)", [p]))
        # 9 end
        p = part(); anim(p, 4.0, end_card); beats.append(("09", "End", [p]))

        # each beat at least as long as its voiceover plus air: pad by holding a black tail if short
        timeline, video_parts, audio_at = [], [], []
        clock = 0.0
        for vo, label, ps in beats:
            secs = sum(float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                             "csv=p=0", str(x)], capture_output=True, text=True).stdout) for x in ps)
            need = vo_secs(vo) + 0.8
            if secs < need:
                pad = part()
                last = ps[-1]
                run("-sseof", "-0.05", "-i", str(last), "-frames:v", "1", str(pad.with_suffix(".png")))
                run("-loop", "1", "-t", str(need - secs), "-i", str(pad.with_suffix(".png")), *ENC, str(pad))
                ps = [*ps, pad]
                secs = need
            audio_at.append((vo, clock + 0.25))
            timeline.append(f"{int(clock // 60)}:{clock % 60:04.1f}  {secs:4.1f}s  {label}")
            video_parts += ps
            clock += secs

        silent = tmp / "video.mp4"
        concat(video_parts, silent)
        inputs, chains = [], []
        for k, (vo, at) in enumerate(audio_at):
            inputs += ["-i", str(vo_file(vo))]
            chains.append(f"[{k + 1}:a]adelay={int(at * 1000)}|{int(at * 1000)}[a{k}]")
        mix = ";".join(chains) + ";" + "".join(f"[a{k}]" for k in range(len(audio_at))) + \
            f"amix=inputs={len(audio_at)}:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11,apad[aout]"
        final = tmp / "muse-trailer.mp4"
        run("-i", str(silent), *inputs, "-filter_complex", mix, "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(final))
        shutil.move(final, OUT / "muse-trailer.mp4")
        (OUT / "timeline.txt").write_text("\n".join(timeline) + f"\n{int(clock // 60)}:{clock % 60:04.1f}  end\n")
    print(OUT / "muse-trailer.mp4")
    print((OUT / "timeline.txt").read_text())


if __name__ == "__main__":
    main()
