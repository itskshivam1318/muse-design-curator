"""The e2e backend: uvicorn with the mock fal client primed (the suite is offline).

The mock fal client is a per-process singleton, so it is scripted here, in the serving process:
every mesh endpoint returns a tiny .glb and every video endpoint a short .mp4.
"""

import io
import sys
from pathlib import Path

import numpy as np
import uvicorn
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from e2e_prepare import FIXTURE_IMAGES, VIDEO_FRAMES, mp4_bytes

from app.analysis import locate
from app.config import get_settings
from app.providers import get_fal
from app.providers.fal import MockFal
from app.providers.segmentation import MockSegmentationProvider, SegInstance, SegResult

BIG = 1500  # object_large.jpg is 1536 px


class BandSegmentation(MockSegmentationProvider):
    """The stock mock puts every noun on one centred box, so an item never has two distinct
    parts. Here each new noun gets the next horizontal band, which is enough for recolouring. Only
    the big object_large.jpg is banded; every other fixture keeps the stock single box."""

    def __init__(self) -> None:
        self.nouns: list[str] = []

    def localize(self, image: bytes, sha256: str, noun: str) -> SegResult:
        with Image.open(io.BytesIO(image)) as im:
            if min(im.size) < BIG:
                return super().localize(image, sha256, noun)
        if noun not in self.nouns:
            self.nouns.append(noun)
        k = self.nouns.index(noun) % 4
        with Image.open(io.BytesIO(image)) as im:
            w, h = im.size
        y1, y2 = int(h * (0.1 + 0.2 * k)), int(h * (0.3 + 0.2 * k))
        x1, x2 = int(w * 0.1), int(w * 0.9)
        mask = np.zeros((h, w), bool)
        mask[y1:y2, x1:x2] = True
        return SegResult(True, [SegInstance((x1, y1, x2, y2), mask, None)])


GLB_URL = "https://v3.fal.media/files/e2e.glb"
MP4_URL = "https://v3.fal.media/files/e2e.mp4"


def prime() -> None:
    s = get_settings()
    fal = get_fal(s)
    assert isinstance(fal, MockFal), "the e2e suite runs on FAL_PROVIDER=mock"
    fal.statuses = ["IN_QUEUE", "COMPLETED"]
    for ep in (s.FAL_MESH_FAST, s.FAL_MESH_DETAILED):
        fal.results[ep] = {"model_mesh": {"url": GLB_URL}, "seed": 1}
    for ep in (s.FAL_VIDEO_STANDARD, s.FAL_VIDEO_PRO):
        fal.results[ep] = {"video": {"url": MP4_URL}}
    fal.files[GLB_URL] = b"glTF" + b"\x02\x00\x00\x00" + b"e2e-mesh"
    fal.files[MP4_URL] = mp4_bytes([FIXTURE_IMAGES / n for n in VIDEO_FRAMES])


if __name__ == "__main__":
    port = int(sys.argv[1])
    prime()
    seg = BandSegmentation()
    locate.get_segmentation = lambda _s: seg  # type: ignore[assignment]
    from app.main import app

    uvicorn.run(app, host="127.0.0.1", port=port)
