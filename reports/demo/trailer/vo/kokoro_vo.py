import sys, numpy as np, soundfile as sf
from pathlib import Path
from kokoro import KPipeline
vo = Path(sys.argv[1]); voice = sys.argv[2]
pipe = KPipeline(lang_code='a')
for line in (vo / 'lines.txt').read_text().splitlines():
    if not line.strip(): continue
    n, text = line.split('|', 1)
    text = text.replace('...', ',')
    audio = np.concatenate([a for _, _, a in pipe(text, voice=voice, speed=1.0)])
    sf.write(vo / f'{n}.wav', audio, 24000)
    print(n, round(len(audio) / 24000, 1))
