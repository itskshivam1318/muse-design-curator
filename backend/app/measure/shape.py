"""Shape measurement: Hu moments + aligned-contour IoU."""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

SHAPE_SAME_MIN = 0.85  # experimental
SHAPE_DIFFERENT_MAX = 0.60  # experimental

HU_FLOOR = 1e-10
IOU_POWER = 9.0  # sharpens IoU: Hu1 of circle vs square is near-equal and raw IoU ~0.82, so both are too forgiving alone
N_POINTS = 64
RASTER = 128
RASTER_SCALE = 30.0  # pixels per unit RMS radius


def _log_hu(hu: np.ndarray) -> list[float]:
    # Moments below HU_FLOOR are numerical noise (symmetric shapes give ~1e-18 with random
    # sign); clamp them so two symmetric shapes compare as equal instead of "1e-125 apart".
    return [
        float(-np.sign(h) * np.log10(abs(h))) if abs(h) >= HU_FLOOR else -np.log10(HU_FLOOR)
        for h in hu
    ]


def _contour(mask: np.ndarray) -> np.ndarray:
    m = np.ascontiguousarray(mask.astype(np.uint8))
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    c = max(cs, key=cv2.contourArea).reshape(-1, 2).astype(float)
    closed = np.vstack([c, c[:1]])
    seg = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    t = np.linspace(0, s[-1], N_POINTS, endpoint=False)
    pts = np.stack([np.interp(t, s, closed[:, 0]), np.interp(t, s, closed[:, 1])], axis=1)
    # light circular smoothing removes pixel-staircase noise on small masks
    pts = (np.roll(pts, -1, axis=0) + pts + np.roll(pts, 1, axis=0)) / 3.0
    pts -= pts.mean(axis=0)
    rms = np.sqrt((pts**2).sum(axis=1).mean())
    return pts / rms if rms > 0 else pts


def shape_descriptor(mask: np.ndarray) -> dict[str, Any]:
    """{hu: 7 log-scaled floats, contour: 64x2 normalised polyline}."""
    if not mask.any():
        raise ValueError("empty mask")
    hu = cv2.HuMoments(cv2.moments(mask.astype(np.uint8), binaryImage=True)).ravel()
    return {"hu": _log_hu(hu), "contour": _contour(mask).tolist()}


def _raster(pts: np.ndarray) -> np.ndarray:
    img = np.zeros((RASTER, RASTER), np.uint8)
    p = np.round(pts * RASTER_SCALE + RASTER / 2).astype(np.int32)
    cv2.fillPoly(img, [p], 1)
    return img.astype(bool)


def _best_iou(a: np.ndarray, b: np.ndarray) -> float:
    ra = _raster(a)
    best = 0.0
    for k in range(8):
        th = k * np.pi / 4
        rot = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
        rb = _raster(b @ rot.T)
        union = np.count_nonzero(ra | rb)
        if union:
            best = max(best, np.count_nonzero(ra & rb) / union)
    return best


def shape_similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    d = float(np.abs(np.asarray(a["hu"]) - np.asarray(b["hu"])).sum())
    hu_sim = float(np.exp(-d))
    iou = _best_iou(np.asarray(a["contour"], float), np.asarray(b["contour"], float))
    return float(np.clip(0.5 * hu_sim + 0.5 * iou**IOU_POWER, 0.0, 1.0))
