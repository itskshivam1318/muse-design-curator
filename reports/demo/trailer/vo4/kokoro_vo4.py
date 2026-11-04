"""Render vo4/lines.txt (id|voice|text) with Kokoro-82M into vo4/<id>.wav.

    <kokoro venv>/bin/python reports/demo/trailer/vo4/kokoro_vo4.py reports/demo/trailer/vo4
"""

import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro import KPipeline

vo = Path(sys.argv[1])
pipes = {"a": KPipeline(lang_code="a"), "b": KPipeline(lang_code="b")}  # American, British
for line in (vo / "lines.txt").read_text().splitlines():
    if not line.strip():
        continue
    n, voice, text = line.split("|", 2)
    pipe = pipes["b" if voice.startswith("b") else "a"]
    audio = np.concatenate([a for _, _, a in pipe(text.replace("...", ","), voice=voice, speed=1.0)])
    sf.write(vo / f"{n}.wav", audio, 24000)
    print(n, voice, round(len(audio) / 24000, 1))
