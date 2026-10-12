"""
QR codes. On identity documents they usually encode the holder's details (Aadhaar's secure QR
carries name, date of birth, address and photo), so they are proposed for redaction by default.
"""

from __future__ import annotations

import logging
import threading

import cv2
import numpy as np

log = logging.getLogger(__name__)
_lock = threading.Lock()
_qr = None


def qr_boxes(image: np.ndarray, pad: int = 6) -> list[dict]:
    global _qr
    with _lock:
        if _qr is None:
            # The ArUco-based detector finds dense / low-quality codes the classic one misses.
            _qr = cv2.QRCodeDetectorAruco() if hasattr(cv2, "QRCodeDetectorAruco") else cv2.QRCodeDetector()
        try:
            ok, pts = _qr.detectMulti(image)
        except cv2.error as e:
            log.debug("QR detection failed: %s", e)
            return []
    if not ok or pts is None:
        return []
    H, W = image.shape[:2]
    boxes = []
    for quad in pts:
        x0, y0 = np.floor(quad.min(axis=0)).astype(int) - pad
        x1, y1 = np.ceil(quad.max(axis=0)).astype(int) + pad
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
        if x1 > x0 and y1 > y0:
            boxes.append({"x": int(x0), "y": int(y0), "w": int(x1 - x0), "h": int(y1 - y0)})
    return boxes
