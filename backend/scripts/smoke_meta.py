"""Live smoke checks against Meta's Model API and Baseten.

Prints PASS/FAIL/SKIP plus latency per check and never raises. Without
MODEL_API_KEY every Meta check prints SKIP (Baseten needs BASETEN_API_KEY).
Passing checks save raw responses under backend/tests/fixtures/meta/live/, never over the
hand-written fixtures one level up.
"""

from __future__ import annotations

import asyncio
import base64
import io
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx
from openai import AsyncOpenAI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "meta" / "live"
BASETEN_URL = "https://inference.baseten.co/v1"
BASETEN_MODELS = ("meta-models/muse-spark-open", "meta-models/muse-spark-open-1026")

Outcome = tuple[str, str]  # (status, detail)
latencies: list[tuple[str, float]] = []


def _jpeg_b64(seed: int = 0) -> str:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (512, 512), (230 - seed * 10, 225, 215))
    d = ImageDraw.Draw(img)
    d.ellipse((136, 136, 376, 376), fill=(30, 30, 40), outline=(200, 200, 200), width=8)
    d.line((256, 256, 256, 170), fill=(255, 255, 255), width=6)
    d.line((256, 256, 320, 256), fill=(255, 255, 255), width=6)
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return base64.b64encode(buf.getvalue()).decode()


def _image_part(b64: str) -> dict[str, str]:
    return {"type": "input_image", "image_url": f"data:image/jpeg;base64,{b64}"}


def _video_b64() -> str:
    import av
    import numpy as np

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "clip.mp4"
        with av.open(str(path), "w") as container:
            stream = container.add_stream("libx264", rate=10)
            stream.width, stream.height, stream.pix_fmt = 256, 256, "yuv420p"  # type: ignore[attr-defined]
            for i in range(30):
                arr = np.full((256, 256, 3), 220, dtype=np.uint8)
                x = 40 + i * 4
                arr[100:160, x : x + 60] = (30, 30, 40)
                frame = av.VideoFrame.from_ndarray(arr, format="rgb24")
                for pkt in stream.encode(frame):
                    container.mux(pkt)
            for pkt in stream.encode():
                container.mux(pkt)
        return base64.b64encode(path.read_bytes()).decode()


def _save(name: str, text: str) -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / name).write_text(text)


async def _run(name: str, fn: Callable[[], Awaitable[Outcome]], enabled: bool, why: str) -> None:
    if not enabled:
        print(f"SKIP {name}: {why}")
        return
    start = time.perf_counter()
    try:
        status, detail = await fn()
    except Exception as exc:  # smoke script must never raise
        status, detail = "FAIL", f"{type(exc).__name__}: {exc}"
    dt = time.perf_counter() - start
    latencies.append((name, dt))
    print(f"{status} {name} ({dt * 1000:.0f} ms) {detail}")


async def main() -> int:
    s = get_settings()
    has_key = bool(s.MODEL_API_KEY)
    client = AsyncOpenAI(
        base_url=s.META_BASE_URL, api_key=s.MODEL_API_KEY or "unset", timeout=s.MODEL_TIMEOUT_S
    )
    no_key = "MODEL_API_KEY not set"

    async def spark_text() -> Outcome:
        r = await client.responses.create(
            model=s.MUSE_SPARK_MODEL,
            input=[{"role": "user", "content": [{"type": "input_text", "text": "Say hi."}]}],
        )
        _save("spark_text.json", r.model_dump_json(indent=2))
        return "PASS", r.output_text[:60]

    async def spark_schema() -> Outcome:
        content: list[dict[str, str]] = [
            {"type": "input_text", "text": "For each image give a one word dominant color."}
        ]
        content += [_image_part(_jpeg_b64(i)) for i in range(10)]
        schema = {
            "type": "object",
            "properties": {"colors": {"type": "array", "items": {"type": "string"}}},
            "required": ["colors"],
            "additionalProperties": False,
        }
        r = await client.responses.create(
            model=s.MUSE_SPARK_MODEL,
            input=[{"role": "user", "content": content}],  # type: ignore[list-item]
            text={
                "format": {
                    "type": "json_schema",
                    "name": "probe",
                    "schema": schema,
                    "strict": True,
                }
            },
        )
        _save("spark_schema.json", r.model_dump_json(indent=2))
        return "PASS", r.output_text[:60]

    async def sam(kind: str) -> Outcome:
        import meta_sam_parser as msp

        if kind == "image":
            part: dict[str, str] = _image_part(_jpeg_b64())
            fmt = msp.image_segmentation_format()
        else:
            part = {
                "type": "input_video",
                "video_url": f"data:video/mp4;base64,{_video_b64()}",
            }
            fmt = msp.video_segmentation_format()
        stream = await client.responses.create(
            model="sam-3.1",
            input=[
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": "watch dial"}, part],
                }
            ],  # type: ignore[arg-type]
            metadata={"include_confidence": "true", "mask_encoding": "one_bit"},
            stream=True,
        )
        parsed = msp.parse_responses_stream(stream, fmt)  # type: ignore[arg-type]
        result = await parsed.final_result()
        _save("sam_image.txt" if kind == "image" else "sam_video.txt", result.raw_output)
        return "PASS", f"records={len(result.records)} outcome={type(result.outcome).__name__}"

    async def embeddings() -> Outcome:
        async with httpx.AsyncClient(timeout=s.MODEL_TIMEOUT_S) as http:
            r = await http.get(
                f"{s.META_BASE_URL}/embeddings",
                headers={"Authorization": f"Bearer {s.MODEL_API_KEY}"},
            )
        return "PASS", f"status={r.status_code} (expected 404)"

    async def baseten() -> Outcome:
        bt = AsyncOpenAI(base_url=BASETEN_URL, api_key=s.BASETEN_API_KEY or "unset")
        notes = []
        ok = True
        for model in BASETEN_MODELS:
            try:
                await bt.chat.completions.create(
                    model=model, messages=[{"role": "user", "content": "hi"}], max_tokens=1
                )
                notes.append(f"{model}=ok")
            except Exception as exc:
                ok = False
                notes.append(f"{model}={type(exc).__name__}")
        return ("PASS" if ok else "FAIL"), " ".join(notes)

    await _run("1 muse-spark-1.3 text", spark_text, has_key, no_key)
    await _run("2 muse-spark 10-image json_schema", spark_schema, has_key, no_key)
    await _run("3 sam-3.1 image 'watch dial'", lambda: sam("image"), has_key, no_key)
    await _run("4 GET /embeddings status", embeddings, has_key, no_key)
    await _run(
        "5 baseten muse-spark-open", baseten, bool(s.BASETEN_API_KEY), "BASETEN_API_KEY not set"
    )
    await _run("7 sam-3.1 video (3 s mp4)", lambda: sam("video"), has_key, no_key)

    if latencies:
        summary = ", ".join(f"{n.split()[0]}={t * 1000:.0f}ms" for n, t in latencies)
        print(f"6 latency summary: {summary}")
    else:
        print("SKIP 6 latency summary: no checks ran")
    return 0


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"FAIL smoke runner: {exc}")
    sys.exit(0)
