"""
Runtime configuration.

Everything is driven by environment variables so the same code runs from a
source checkout, a test run, or the frozen (PyInstaller) desktop build.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


def _frozen_root() -> Path | None:
    """Directory holding bundled data when running from a PyInstaller build."""
    return Path(getattr(sys, "_MEIPASS")) if getattr(sys, "frozen", False) else None


def _default_data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "Privex"


BACKEND_ROOT = _frozen_root() or Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    # Where bundled models live (face detectors, optional pre-fetched ASR model)
    models_dir: Path = field(default_factory=lambda: Path(
        os.environ.get("PRIVEX_MODELS_DIR", BACKEND_ROOT / "models")))
    # Where uploads / outputs / downloaded models are written
    data_dir: Path = field(default_factory=lambda: Path(
        os.environ.get("PRIVEX_DATA_DIR", _default_data_dir())))

    # Text detection
    threshold: float = float(os.environ.get("PRIVEX_THRESHOLD", "0.5"))
    spacy_model: str = os.environ.get("PRIVEX_SPACY_MODEL", "en_core_web_sm")
    use_ner: bool = os.environ.get("PRIVEX_USE_NER", "1") != "0"

    # Vision
    face_threshold: float = float(os.environ.get("PRIVEX_FACE_THRESHOLD", "0.6"))
    ocr_min_score: float = float(os.environ.get("PRIVEX_OCR_MIN_SCORE", "0.5"))
    # ONNX Runtime oversubscribes hybrid (P/E-core) CPUs with its default; 4 is ~3x faster on a 13900H
    ocr_threads: int = int(os.environ.get("PRIVEX_OCR_THREADS", "4"))

    # Audio: any faster-whisper model name ("tiny.en", "base.en", "small.en"…) or a local path
    asr_model: str = os.environ.get("PRIVEX_ASR_MODEL", "base.en")
    asr_compute_type: str = os.environ.get("PRIVEX_ASR_COMPUTE", "int8")

    # Video
    video_ocr_interval_s: float = float(os.environ.get("PRIVEX_VIDEO_OCR_INTERVAL", "0.5"))
    max_video_seconds: float = float(os.environ.get("PRIVEX_MAX_VIDEO_SECONDS", "300"))

    # Server
    host: str = os.environ.get("PRIVEX_HOST", "127.0.0.1")
    port: int = int(os.environ.get("PRIVEX_PORT", "8765"))
    max_upload_mb: int = int(os.environ.get("PRIVEX_MAX_UPLOAD_MB", "200"))
    file_ttl_minutes: int = int(os.environ.get("PRIVEX_FILE_TTL_MINUTES", "60"))

    @property
    def work_dir(self) -> Path:
        p = self.data_dir / "work"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def asr_cache_dir(self) -> Path:
        p = self.data_dir / "models"
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
