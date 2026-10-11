"""
Image redaction: propose (detect, nothing modified) → human review → apply.
"""

from __future__ import annotations

import cv2
import numpy as np

from privex_core.text.analyzer import default_analyzer
from privex_core.vision import ocr
from privex_core.vision.faces import detector

REDACTION_STYLES = ("black", "blur", "pixelate")


def decode(data: bytes) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Unsupported or corrupt image")
    return img


def union(boxes: list[dict]) -> dict:
    if not boxes:
        return {"x": 0, "y": 0, "w": 0, "h": 0}
    x0 = min(b["x"] for b in boxes); y0 = min(b["y"] for b in boxes)
    x1 = max(b["x"] + b["w"] for b in boxes); y1 = max(b["y"] + b["h"] for b in boxes)
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def propose(image: np.ndarray) -> dict:
    analyzer = default_analyzer()
    h, w = image.shape[:2]
    proposals = []

    for i, f in enumerate(detector().detect(image)):
        proposals.append({
            "id": f"face_{i}", "type": "face", "entity_type": "FACE", "label": "Human Face",
            "reason": f"face detector ({detector().backend}) confidence {f.score:.2f}",
            "sensitive": True, "approved": True, "confidence": f.score,
            "bbox": f.bbox(), "boxes": [f.bbox()], "source": f"face:{detector().backend}",
        })

    lines = ocr.run_ocr(image)
    doc = ocr.build_document(lines)
    entities = analyzer.analyze(ocr.normalize_for_analysis(doc))
    for i, e in enumerate(entities):
        e.text = doc[e.start:e.end]
        boxes = ocr.span_to_boxes(lines, e.start, e.end)
        if not boxes:
            continue
        sensitive = e.score >= analyzer.threshold
        ctx = doc[max(0, e.start - 40):e.end + 40].replace("\n", " ")
        proposals.append({
            "id": f"text_{i}", "type": "text", "entity_type": e.type, "label": e.label,
            "value": e.text, "context": ctx, "reason": "; ".join(e.reasons),
            "sensitive": sensitive, "approved": sensitive, "confidence": round(e.score, 3),
            "bbox": union(boxes), "boxes": boxes, "source": e.source,
        })

    return {
        "image_w": w, "image_h": h,
        "proposals": proposals,
        "ocr_text": doc,
        "sensitive_count": sum(p["sensitive"] for p in proposals),
        "safe_count": sum(not p["sensitive"] for p in proposals),
        "threshold": analyzer.threshold,
    }


def apply(image: np.ndarray, boxes: list[dict], style: str = "black") -> tuple[np.ndarray, int]:
    out = image.copy()
    H, W = out.shape[:2]
    applied = 0
    for b in boxes:
        x0, y0 = max(0, int(b["x"])), max(0, int(b["y"]))
        x1, y1 = min(W, x0 + int(b["w"])), min(H, y0 + int(b["h"]))
        if x1 <= x0 or y1 <= y0:
            continue
        roi = out[y0:y1, x0:x1]
        if style == "blur":
            k = max(31, (max(roi.shape[:2]) // 2) | 1)
            out[y0:y1, x0:x1] = cv2.GaussianBlur(roi, (k, k), 0)
        elif style == "pixelate":
            bw, bh = max(1, (x1 - x0) // 12), max(1, (y1 - y0) // 12)
            small = cv2.resize(roi, (bw, bh), interpolation=cv2.INTER_LINEAR)
            out[y0:y1, x0:x1] = cv2.resize(small, (x1 - x0, y1 - y0), interpolation=cv2.INTER_NEAREST)
        else:
            out[y0:y1, x0:x1] = 0
        applied += 1
    return out, applied


def encode(image: np.ndarray, ext: str = ".png", quality: int = 92) -> bytes:
    params = [cv2.IMWRITE_JPEG_QUALITY, quality] if ext.lower() in (".jpg", ".jpeg") else []
    ok, buf = cv2.imencode(ext, image, params)
    if not ok:
        raise ValueError(f"Cannot encode image as {ext}")
    return buf.tobytes()
