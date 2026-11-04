"""An original music bed for the trailer, synthesised here (no licence needed).

    backend/.venv/bin/python reports/demo/trailer/music.py [seconds]

Warm lo-fi at 80 BPM: electric-piano chords (Am9, Fmaj7, Cmaj9, G6), a soft pad, a brushed beat
that enters after the hook, and a little vinyl crackle. Writes assets/music.wav (git-ignored);
the trailer ducks it under the voice.
"""

import sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile

SR = 44100
BPM = 80
BEAT = 60 / BPM
BAR = 4 * BEAT
OUT = Path(__file__).resolve().parent / "assets" / "music.wav"

# two bars per chord; MIDI notes, voiced low and close
CHORDS = [
    [45, 57, 60, 64, 67, 71],  # Am9
    [41, 53, 57, 60, 64, 69],  # Fmaj7
    [48, 55, 59, 62, 64, 67],  # Cmaj9
    [43, 55, 59, 62, 64, 67],  # G6
]


def hz(n: int) -> float:
    return 440.0 * 2 ** ((n - 69) / 12)


def epiano(freq: float, dur: float, vel: float) -> np.ndarray:
    """A Rhodes-like tine: sine plus a bell partial, a soft attack and an exponential decay."""
    t = np.arange(int(dur * SR)) / SR
    env = (1 - np.exp(-t * 60)) * np.exp(-t * 1.6)
    tone = np.sin(2 * np.pi * freq * t) + 0.25 * np.sin(2 * np.pi * freq * 2 * t) * np.exp(-t * 4)
    tone += 0.08 * np.sin(2 * np.pi * freq * 7.1 * t) * np.exp(-t * 18)  # the tine's ping
    return vel * env * tone * (1 + 0.06 * np.sin(2 * np.pi * 4.5 * t))  # gentle tremolo


def pad(freqs: list[float], dur: float) -> np.ndarray:
    t = np.arange(int(dur * SR)) / SR
    env = np.minimum(1, t / 1.8) * np.minimum(1, (dur - t) / 1.2)
    s = sum(np.sin(2 * np.pi * f * t) + 0.5 * np.sin(2 * np.pi * f * 1.003 * t) for f in freqs)
    return 0.05 * env * s


def kick(dur: float = 0.35) -> np.ndarray:
    t = np.arange(int(dur * SR)) / SR
    f = 55 + 70 * np.exp(-t * 30)
    return 0.5 * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 11)


def brush(rng: np.random.Generator, dur: float = 0.22) -> np.ndarray:
    n = int(dur * SR)
    noise = rng.standard_normal(n)
    hp = np.diff(noise, prepend=0)  # a crude high-pass: brushes are all top end
    return 0.06 * hp * np.exp(-np.arange(n) / SR * 18)


def place(track: np.ndarray, sound: np.ndarray, at: float) -> None:
    i = int(at * SR)
    j = min(len(track), i + len(sound))
    if i < len(track):
        track[i:j] += sound[: j - i]


def main() -> None:
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 170.0
    rng = np.random.default_rng(7)
    n = int(secs * SR) + SR
    keys = np.zeros(n)
    drums = np.zeros(n)
    bar = 0
    while bar * BAR < secs:
        chord = CHORDS[(bar // 2) % len(CHORDS)]
        at = bar * BAR
        if bar % 2 == 0:
            place(keys, pad([hz(m) for m in chord[1:4]], 2 * BAR), at)
        # a lazy, slightly late strum: each note a few ms after the last, velocities that wander
        for k, m in enumerate(chord):
            place(keys, epiano(hz(m), BAR * 1.6, 0.11 + 0.03 * rng.random()), at + 0.012 * k + 0.01 * rng.random())
        # a little answering figure on the off-beat of beat 3
        top = chord[-1] + (2 if bar % 2 else -3)
        place(keys, epiano(hz(top), BEAT * 1.5, 0.08), at + 2.5 * BEAT + 0.02 * rng.random())
        if at > 22:  # the beat enters after the hook
            for b in range(4):
                if b in (0, 2):
                    place(drums, kick(), at + b * BEAT)
                place(drums, brush(rng), at + b * BEAT + BEAT / 2 + 0.01 * rng.random())
                if b in (1, 3):
                    place(drums, 1.6 * brush(rng, 0.3), at + b * BEAT)
        bar += 1
    crackle = np.zeros(n)
    for i in rng.integers(0, n, size=int(secs * 9)):
        crackle[i] = rng.uniform(-0.12, 0.12)
    mix = keys + 0.8 * drums + crackle + 0.002 * rng.standard_normal(n)
    # warmth: a one-pole low-pass, then fade in and out
    out = np.empty_like(mix)
    acc = 0.0
    a = 0.35
    for i, v in enumerate(mix):
        acc += a * (v - acc)
        out[i] = acc
    t = np.arange(n) / SR
    out *= np.minimum(1, t / 2.5) * np.minimum(1, np.maximum(0, (secs - t) / 3.0))
    out /= max(1e-9, np.max(np.abs(out))) / 0.7
    stereo = np.stack([out, np.roll(out, int(0.011 * SR))], axis=1)  # a touch of width
    OUT.parent.mkdir(exist_ok=True)
    wavfile.write(OUT, SR, (stereo * 32767).astype(np.int16))
    print(OUT, round(secs, 1), "s")


if __name__ == "__main__":
    main()
