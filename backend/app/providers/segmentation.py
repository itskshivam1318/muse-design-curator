"""Segmentation providers: localize / track a noun phrase with SAM 3.1 (or a mock)."""

from __future__ import annotations

import asyncio
import io
import tempfile
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import openai
from PIL import Image

from app.providers.meta_client import check_model_id, data_url
from app.providers.reliability import ModelError, call_model

SAM_MODEL = "sam-3.1"


@dataclass
class SegInstance:
    bbox: tuple[int, int, int, int]  # x1, y1, x2, y2 (half-open), pixels
    mask: np.ndarray  # bool, shape (H, W)
    score: float | None = None


@dataclass
class SegResult:
    found: bool = False
    instances: list[SegInstance] = field(default_factory=list)


class SegmentationProvider(Protocol):
    id: str
    is_mock: bool

    def localize(self, image: bytes, sha256: str, noun: str) -> SegResult: ...

    def track(self, video: bytes, noun: str) -> list[SegResult]: ...


def _video_info(video: bytes) -> tuple[int, int, int]:
    """(width, height, frame_count) via PyAV."""
    import av

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "v.bin"
        p.write_bytes(video)
        with av.open(str(p)) as c:
            s = c.streams.video[0]
            n = sum(1 for _ in c.decode(s))
            return s.codec_context.width, s.codec_context.height, n


def _video_mime(video: bytes) -> str:
    if video[:4] == b"\x1a\x45\xdf\xa3":
        return "video/webm"
    if video[4:12] == b"ftypqt  ":
        return "video/quicktime"
    return "video/mp4"


def _full_mask(raster: bytes, mh: int, mw: int, bounds: tuple[int, int, int, int],
               width: int, height: int) -> np.ndarray:  # fmt: skip
    """Stretch a box-local raster to its box and paste it on a (height, width) canvas."""
    left, top, right, bottom = bounds
    local = np.frombuffer(raster, dtype=np.uint8).reshape(mh, mw).astype(bool)
    bw, bh = max(right - left, 1), max(bottom - top, 1)
    ys = np.minimum((np.arange(bh) * mh) // bh, mh - 1)
    xs = np.minimum((np.arange(bw) * mw) // bw, mw - 1)
    box_mask = local[np.ix_(ys, xs)]
    canvas = np.zeros((height, width), dtype=bool)
    x2, y2 = min(right, width), min(bottom, height)
    canvas[top:y2, left:x2] = box_mask[: y2 - top, : x2 - left]
    return canvas


def _instances(records: Iterable[Any], width: int, height: int) -> dict[int, list[SegInstance]]:
    """Pair box + mask records per (frame, object) and rasterise. Keyed by frame index."""
    from meta_sam_parser import SegmentationBoxRecord, SegmentationMaskRecord, decode_mask_to_raster

    boxes: dict[tuple[int, str], Any] = {}
    masks: dict[tuple[int, str], Any] = {}
    for r in records:
        frame = r.frame.frame_index if getattr(r, "frame", None) is not None else 0
        if isinstance(r, SegmentationBoxRecord):
            boxes[(frame, r.object_id)] = r
        elif isinstance(r, SegmentationMaskRecord):
            masks[(frame, r.object_id)] = r  # later revisions win
    out: dict[int, list[SegInstance]] = {}
    for (frame, oid), m in masks.items():
        b = boxes.get((frame, oid))
        bounds = (int(m.bounds.left), int(m.bounds.top), int(m.bounds.right), int(m.bounds.bottom))
        raster = decode_mask_to_raster(m.mask)
        full = _full_mask(raster, m.mask.height, m.mask.width, bounds, width, height)
        x1, y1 = bounds[0], bounds[1]
        x2, y2 = min(bounds[2], width), min(bounds[3], height)
        score = m.confidence if m.confidence is not None else (b.confidence if b else None)
        out.setdefault(frame, []).append(SegInstance((x1, y1, x2, y2), full, score))
    return out


API_MAX_EDGE = 1024  # larger images make the client-side mask decoder take minutes


def shrink_for_api(image: bytes, max_edge: int = API_MAX_EDGE) -> tuple[bytes, tuple[int, int]]:
    """The bytes to send and their (width, height); a downscaled JPEG copy if the image is large."""
    with Image.open(io.BytesIO(image)) as im:
        w, h = im.size
        if max(w, h) <= max_edge:
            return image, (w, h)
        k = max_edge / max(w, h)
        small = im.convert("RGB").resize(
            (max(1, round(w * k)), max(1, round(h * k))), Image.Resampling.LANCZOS
        )
    buf = io.BytesIO()
    small.save(buf, "JPEG", quality=92)
    return buf.getvalue(), small.size


def _rescale(inst: SegInstance, src: tuple[int, int], dst: tuple[int, int]) -> SegInstance:
    """Map an instance found on the downscaled copy back onto the original's pixel grid."""
    fx, fy = dst[0] / src[0], dst[1] / src[1]
    mask = np.asarray(
        Image.fromarray(inst.mask.astype(np.uint8) * 255).resize(dst, Image.Resampling.NEAREST)
    )
    x1, y1, x2, y2 = inst.bbox
    box = (round(x1 * fx), round(y1 * fy), min(dst[0], round(x2 * fx)), min(dst[1], round(y2 * fy)))
    return SegInstance(box, mask > 127, inst.score)


class Sam31Provider:
    id = "sam31"
    is_mock = False

    def __init__(self, client: openai.OpenAI, model: str = SAM_MODEL, *, max_retries: int = 2,
                 timeout: float = 60) -> None:  # fmt: skip
        self.client = client
        self.model = check_model_id(model)
        self.max_retries = max_retries
        self.timeout = timeout

    def _segment(self, noun: str, media_part: dict[str, str], video: bool) -> Any:
        import meta_sam_parser as msp

        def go() -> Any:
            kwargs: dict[str, Any] = {
                "model": self.model,
                "input": [
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": noun}, media_part],
                    }
                ],
                "metadata": {"include_confidence": "true", "mask_encoding": "one_bit"},
            }
            stream = self.client.responses.create(**kwargs, stream=True)

            async def events() -> AsyncIterator[Any]:
                for ev in stream:  # sync SDK stream, drained inside this worker thread
                    yield ev

            fmt = msp.video_segmentation_format() if video else msp.image_segmentation_format()

            async def parse() -> Any:
                return await msp.parse_responses_stream(events(), fmt).final_result()

            return asyncio.run(parse())

        try:
            return call_model(go, timeout=self.timeout, max_retries=self.max_retries)
        except ModelError:
            raise
        except Exception as exc:  # parser errors: stream failed / refused / malformed
            raise ModelError(
                "MODEL_INVALID_RESPONSE", message=f"{type(exc).__name__}: {exc}"
            ) from exc

    def localize(self, image: bytes, sha256: str, noun: str) -> SegResult:
        with Image.open(io.BytesIO(image)) as im:
            width, height = im.size
        small, (sw, sh) = shrink_for_api(image)
        part = {"type": "input_image", "image_url": data_url(small)}
        result = self._segment(noun, part, video=False)
        insts = _instances(result.records, sw, sh).get(0, [])
        if (sw, sh) != (width, height):
            insts = [_rescale(i, (sw, sh), (width, height)) for i in insts]
        return SegResult(found=bool(insts), instances=insts)

    def track(self, video: bytes, noun: str) -> list[SegResult]:
        width, height, n = _video_info(video)
        part = {"type": "input_video", "video_url": data_url(video, _video_mime(video))}
        result = self._segment(noun, part, video=True)
        by_frame = _instances(result.records, width, height)
        total = max(n, max(by_frame, default=-1) + 1)
        return [SegResult(bool(by_frame.get(i)), by_frame.get(i, [])) for i in range(total)]


def _centre(width: int, height: int) -> SegResult:
    x1, x2 = int(width * 0.2), int(width * 0.8)
    y1, y2 = int(height * 0.2), int(height * 0.8)
    mask = np.zeros((height, width), dtype=bool)
    mask[y1:y2, x1:x2] = True
    return SegResult(True, [SegInstance((x1, y1, x2, y2), mask, None)])


class MockSegmentationProvider:
    """One centred box covering the middle 60% of the image, with a matching mask."""

    id = "mock"
    is_mock = True

    def localize(self, image: bytes, sha256: str, noun: str) -> SegResult:
        with Image.open(io.BytesIO(image)) as im:
            return _centre(*im.size)

    def track(self, video: bytes, noun: str) -> list[SegResult]:
        width, height, n = _video_info(video)
        return [_centre(width, height) for _ in range(n)]
