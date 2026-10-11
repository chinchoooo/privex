"""
Download every model PRIVEX needs into backend/models so the app runs fully offline
(and so the PyInstaller build can bundle them).

    python scripts/fetch_models.py               # YuNet face model + faster-whisper base.en
    python scripts/fetch_models.py --asr small.en

The spaCy model is a pip package (see requirements.txt); RapidOCR ships its ONNX models in its wheel.
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

MODELS = Path(__file__).resolve().parent.parent / "models"
YUNET_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"


def _trust_system_certs():
    # Corporate proxies / AV HTTPS scanning inject their own root CA into the OS store.
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass


def fetch_yunet():
    dest = MODELS / "face_detection_yunet_2023mar.onnx"
    if dest.exists():
        print(f"ok {dest.name} already present")
        return
    print(f"get {YUNET_URL}")
    urllib.request.urlretrieve(YUNET_URL, dest)
    if dest.stat().st_size < 100_000:
        dest.unlink()
        sys.exit("YuNet download looks wrong (git-lfs pointer?). Download it manually from opencv_zoo.")
    print(f"ok {dest.name}")


def fetch_asr(name: str):
    from huggingface_hub import snapshot_download
    dest = MODELS / "asr" / name
    if (dest / "model.bin").exists():
        print(f"ok asr/{name} already present")
        return
    repo = f"Systran/faster-whisper-{name}"
    print(f"get {repo}")
    snapshot_download(repo, local_dir=dest, allow_patterns=["*.bin", "*.json", "*.txt"])
    print(f"ok asr/{name}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--asr", default="base.en", help="faster-whisper model to bundle (tiny.en, base.en, small.en…)")
    ap.add_argument("--skip-asr", action="store_true")
    a = ap.parse_args()
    MODELS.mkdir(exist_ok=True)
    _trust_system_certs()
    fetch_yunet()
    if not a.skip_asr:
        fetch_asr(a.asr)
