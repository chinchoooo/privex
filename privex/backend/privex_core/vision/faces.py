"""
Face detection.

Primary: YuNet (OpenCV Zoo, 230 KB ONNX) — handles small/rotated faces well.
Fallback: ResNet10-SSD Caffe model (the original detector).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import cv2
import numpy as np

from privex_core.config import settings

log = logging.getLogger(__name__)

YUNET_FILE = "face_detection_yunet_2023mar.onnx"
RES10_MODEL = "res10_300x300_ssd_iter_140000.caffemodel"
RES10_CONFIG = "deploy.prototxt"
MAX_SIDE = 1280          # detection runs on a downscaled copy for speed


@dataclass
class Face:
    x: int
    y: int
    w: int
    h: int
    score: float

    def bbox(self) -> dict:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}


class FaceDetector:
    def __init__(self):
        self._lock = threading.Lock()
        self._yunet = None
        self._res10 = None
        self.backend = None
        yunet = settings.models_dir / YUNET_FILE
        res10 = settings.models_dir / RES10_MODEL
        if yunet.exists():
            self._yunet = cv2.FaceDetectorYN.create(str(yunet), "", (320, 320),
                                                    score_threshold=settings.face_threshold)
            self.backend = "yunet"
        elif res10.exists():
            self._res10 = cv2.dnn.readNetFromCaffe(str(settings.models_dir / RES10_CONFIG), str(res10))
            self.backend = "res10-ssd"
        else:
            log.warning("No face model found in %s; face detection disabled", settings.models_dir)
        log.info("Face detector: %s", self.backend)

    def detect(self, image: np.ndarray, pad: float = 0.25) -> list[Face]:
        if self.backend is None:
            return []
        h, w = image.shape[:2]
        scale = min(1.0, MAX_SIDE / max(h, w))
        small = cv2.resize(image, (int(w * scale), int(h * scale))) if scale < 1 else image

        with self._lock:      # cv2 detectors are not thread-safe
            raw = self._detect_yunet(small) if self._yunet is not None else self._detect_res10(small)

        faces = []
        for x, y, fw, fh, s in raw:
            x, y, fw, fh = x / scale, y / scale, fw / scale, fh / scale
            px, py = fw * pad, fh * pad
            x0, y0 = max(0, int(x - px)), max(0, int(y - py))
            x1, y1 = min(w, int(x + fw + px)), min(h, int(y + fh + py))
            if x1 > x0 and y1 > y0:
                faces.append(Face(x0, y0, x1 - x0, y1 - y0, round(float(s), 3)))
        return faces

    def detect_any_orientation(self, image: np.ndarray, pad: float = 0.25) -> list[Face]:
        """
        Detect faces in all four right-angle orientations (phone photos of ID cards are often
        sideways; the detectors only find upright faces) and merge overlapping hits.
        """
        from privex_core.vision.geometry import iou, rotate, unrotate_box
        H, W = image.shape[:2]
        found: list[Face] = []
        for k in (0, 90, 180, 270):
            for f in self.detect(rotate(image, k), pad):
                b = unrotate_box(f.bbox(), k, W, H)
                found.append(Face(b["x"], b["y"], b["w"], b["h"], f.score))
        kept: list[Face] = []
        for f in sorted(found, key=lambda f: -f.score):
            if all(iou(f.bbox(), g.bbox()) < 0.3 for g in kept):
                kept.append(f)
        return kept

    def _detect_yunet(self, img):
        self._yunet.setInputSize((img.shape[1], img.shape[0]))
        _, dets = self._yunet.detect(img)
        if dets is None:
            return []
        return [(d[0], d[1], d[2], d[3], d[-1]) for d in dets]

    def _detect_res10(self, img):
        h, w = img.shape[:2]
        blob = cv2.dnn.blobFromImage(cv2.resize(img, (300, 300)), 1.0, (300, 300), (104.0, 177.0, 123.0))
        self._res10.setInput(blob)
        dets = self._res10.forward()
        out = []
        for i in range(dets.shape[2]):
            conf = float(dets[0, 0, i, 2])
            if conf >= settings.face_threshold:
                x0, y0, x1, y1 = dets[0, 0, i, 3:7] * np.array([w, h, w, h])
                out.append((x0, y0, x1 - x0, y1 - y0, conf))
        return out


_detector: FaceDetector | None = None
_init_lock = threading.Lock()


def detector() -> FaceDetector:
    global _detector
    with _init_lock:
        if _detector is None:
            _detector = FaceDetector()
    return _detector
