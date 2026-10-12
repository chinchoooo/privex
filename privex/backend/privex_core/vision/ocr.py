"""
OCR (RapidOCR = PaddleOCR models on ONNX Runtime; no Paddle/Torch install needed)
plus layout utilities that turn OCR lines into one document string and map
character spans in that string back to pixel regions.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass

import numpy as np

from privex_core.config import settings

log = logging.getLogger(__name__)

_engine = None
_lock = threading.Lock()


@dataclass
class OcrLine:
    text: str
    quad: np.ndarray        # 4x2 float: top-left, top-right, bottom-right, bottom-left
    score: float
    start: int = 0          # offset of this line inside the assembled document text
    end: int = 0

    @property
    def cy(self) -> float:
        return float(self.quad[:, 1].mean())

    @property
    def height(self) -> float:
        return float(np.linalg.norm(self.quad[3] - self.quad[0]))

    @property
    def x0(self) -> float:
        return float(self.quad[:, 0].min())


def _ocr():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR(intra_op_num_threads=settings.ocr_threads, inter_op_num_threads=1)
        log.info("Loaded RapidOCR (ONNX Runtime)")
    return _engine


def run_ocr(image: np.ndarray) -> list[OcrLine]:
    with _lock:
        result, _ = _ocr()(image)
    lines = []
    for quad, text, score in result or []:
        score = float(score)
        if text.strip() and score >= settings.ocr_min_score:
            lines.append(OcrLine(text.strip(), np.asarray(quad, dtype=np.float32), score))
    return lines


def _read_score(image: np.ndarray) -> float:
    """Recognition confidence × characters, without the 180° line classifier (so upside-down reads badly)."""
    import cv2
    scale = 800 / max(image.shape[:2])
    if scale < 1:      # only a direction vote — a smaller copy is enough and much faster
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    with _lock:
        result, _ = _ocr()(image, use_cls=False)
    return sum(float(s) * len(t) for _, t, s in result or [])


def detect_orientation(image: np.ndarray, lines: list[OcrLine]) -> int:
    """
    Clockwise rotation (0/90/270) that makes the text upright. Only probes when most OCR lines
    are vertical — i.e. the photo is sideways — so upright documents cost nothing extra.
    """
    if not lines:
        return 0
    vertical = 0
    for l in lines:
        w = float(l.quad[:, 0].max() - l.quad[:, 0].min())
        h = float(l.quad[:, 1].max() - l.quad[:, 1].min())
        vertical += h > 1.5 * w
    if vertical * 2 <= len(lines):
        return 0
    from privex_core.vision.geometry import rotate
    scores = {k: _read_score(rotate(image, k)) for k in (90, 270)}
    return max(scores, key=scores.get)


def build_document(lines: list[OcrLine]) -> str:
    """
    Arrange OCR lines in reading order (rows top→bottom, items left→right),
    join items on a row with a space and rows with newlines. Sets line.start/end.
    """
    if not lines:
        return ""
    med_h = float(np.median([l.height for l in lines])) or 10.0
    rows: list[list[OcrLine]] = []
    for line in sorted(lines, key=lambda l: l.cy):
        if rows and abs(line.cy - np.mean([l.cy for l in rows[-1]])) < med_h * 0.5:
            rows[-1].append(line)
        else:
            rows.append([line])

    parts, pos = [], 0
    for r, row in enumerate(rows):
        if r:
            parts.append("\n"); pos += 1
        for i, line in enumerate(sorted(row, key=lambda l: l.x0)):
            if i:
                parts.append(" "); pos += 1
            line.start, line.end = pos, pos + len(line.text)
            parts.append(line.text); pos = line.end
    lines.sort(key=lambda l: l.start)
    return "".join(parts)


_FIELD_PREFIX = re.compile(r"(?m)(?<![A-Za-z0-9])\d{1,2}[a-d]?(?=[A-Z]{2})")


def normalize_for_analysis(doc: str) -> str:
    """
    Length-preserving cleanup of OCR artefacts so offsets still map to pixels.
    ID cards (AAMVA) prefix fields with numbers that OCR glues on: "3DOB:", "4dDLN:", "2ANDREW".
    """
    return _FIELD_PREFIX.sub(lambda m: " " * len(m.group(0)), doc)


def span_to_boxes(lines: list[OcrLine], start: int, end: int, pad: int = 3) -> list[dict]:
    """
    Pixel boxes covering document characters [start, end). For each overlapping
    OCR line the sub-region is interpolated along the line's quad by character
    position, so only the sensitive part of a line is covered.
    """
    boxes = []
    for line in lines:
        s, e = max(start, line.start), min(end, line.end)
        if s >= e:
            continue
        n = max(1, len(line.text))
        # widen by half a character each side: glyph widths vary, proportional placement is approximate
        f0 = max(0.0, (s - line.start - 0.5) / n)
        f1 = min(1.0, (e - line.start + 0.5) / n)
        tl, tr, br, bl = line.quad
        pts = np.array([
            tl + (tr - tl) * f0, tl + (tr - tl) * f1,
            bl + (br - bl) * f1, bl + (br - bl) * f0,
        ])
        x0, y0 = pts.min(axis=0) - pad
        x1, y1 = pts.max(axis=0) + pad
        boxes.append({"x": max(0, int(x0)), "y": max(0, int(y0)),
                      "w": int(x1 - max(0, x0)), "h": int(y1 - max(0, y0))})
    return boxes


def is_loaded() -> bool:
    return _engine is not None
