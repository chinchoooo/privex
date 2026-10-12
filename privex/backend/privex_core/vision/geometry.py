"""Right-angle rotations and mapping boxes from a rotated copy back to the original image."""

from __future__ import annotations

import cv2
import numpy as np

_CV_ROT = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}


def rotate(image: np.ndarray, k: int) -> np.ndarray:
    """Rotate clockwise by k ∈ {0, 90, 180, 270} degrees."""
    return image if k == 0 else cv2.rotate(image, _CV_ROT[k])


def unrotate_box(b: dict, k: int, W: int, H: int) -> dict:
    """Map a box found in `rotate(original, k)` back to the original (W×H) image."""
    x, y, w, h = b["x"], b["y"], b["w"], b["h"]
    if k == 90:
        return {"x": y, "y": H - x - w, "w": h, "h": w}
    if k == 180:
        return {"x": W - x - w, "y": H - y - h, "w": w, "h": h}
    if k == 270:
        return {"x": W - y - h, "y": x, "w": h, "h": w}
    return dict(b)


def iou(a: dict, b: dict) -> float:
    x0, y0 = max(a["x"], b["x"]), max(a["y"], b["y"])
    x1 = min(a["x"] + a["w"], b["x"] + b["w"])
    y1 = min(a["y"] + a["h"], b["y"] + b["h"])
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    union = a["w"] * a["h"] + b["w"] * b["h"] - inter
    return inter / union if union else 0.0
