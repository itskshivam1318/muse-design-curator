"""Regenerates the hand-written SAM fixtures.

No MODEL_API_KEY was available, so these are NOT recordings. The mask payload is
produced with meta_sam_parser's own one-bit raster encoder (private helper
`_encode_raster`), so the installed parser decodes and validates it.
Run: uv run python tests/fixtures/meta/gen_sam_fixture.py
"""

import json
from pathlib import Path

from meta_sam_parser._mask_codec import _encode_raster

HERE = Path(__file__).parent
W, H = 100, 80
X1, Y1, X2, Y2 = 10, 8, 89, 71  # inclusive box
MW, MH = 40, 32


def _mask_bits() -> list[int]:
    cx, cy = (MW - 1) / 2, (MH - 1) / 2
    return [
        int(((x - cx) / (MW / 2)) ** 2 + ((y - cy) / (MH / 2)) ** 2 <= 1)
        for y in range(MH)
        for x in range(MW)
    ]


def sam_text() -> str:
    payload = _encode_raster(_mask_bits(), MW, MH)
    box = f"<|box;x1={X1};y1={Y1};x2={X2};y2={Y2};w={W};h={H};c=0.91|>"
    mask = f"<|mask;x=0;y=0;data={MH},{MW},{payload};c=0.88|>"
    return f"<0f>1{box}{mask}"


def events(text: str) -> list[dict[str, object]]:
    lane = {"item_id": "msg_1", "output_index": 0, "content_index": 0}
    mid = len(text) // 2
    out: list[dict[str, object]] = [
        {"type": "response.output_text.delta", "delta": text[:mid], **lane},
        {"type": "response.output_text.delta", "delta": text[mid:], **lane},
        {"type": "response.output_text.done", "text": text, **lane},
        {"type": "response.completed", "response": {"id": "resp_1"}},
    ]
    return out


def sse(evts: list[dict[str, object]]) -> str:
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in evts)


if __name__ == "__main__":
    (HERE / "sam_image.txt").write_text(sam_text())
    (HERE / "sam_image.sse").write_text(sse(events(sam_text())))
    (HERE / "sam_empty.sse").write_text(sse(events("")))
    resp = {
        "id": "resp_x", "object": "response", "created_at": 0, "status": "completed",
        "model": "muse-spark-1.3", "parallel_tool_calls": False, "tool_choice": "auto",
        "tools": [],
        "output": [{"id": "msg_1", "type": "message", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "annotations": [],
                                 "text": json.dumps({"palette": "warm", "confidence": 0.8})}]}],
    }  # fmt: skip
    (HERE / "spark_schema.json").write_text(json.dumps(resp, indent=2))
