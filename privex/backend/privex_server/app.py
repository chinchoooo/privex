"""
PRIVEX local API.

Binds to 127.0.0.1 only. Serves the web UI from the same origin, and accepts
cross-origin calls only from Chrome extensions.
"""

from __future__ import annotations

import base64
from contextlib import asynccontextmanager
import logging
import os
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from privex_core import __version__
from privex_core.config import BACKEND_ROOT, settings
from privex_core.text import ner
from privex_core.text.analyzer import Analyzer, default_analyzer
from privex_core.vision import image as img_mod
from privex_core.vision import ocr
from privex_core.vision.faces import detector
from privex_server.jobs import JobQueue

log = logging.getLogger("privex")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    threading.Thread(target=_cleanup_loop, daemon=True, name="privex-cleanup").start()
    # Warm the fast models in the background so the first request isn't slow.
    threading.Thread(target=lambda: (ner.load(), detector()), daemon=True, name="privex-warm").start()
    yield


app = FastAPI(title="PRIVEX", version=__version__, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^(chrome-extension|moz-extension)://[a-z0-9\-]+$|^http://(127\.0\.0\.1|localhost)(:\d+)?$",
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

jobs = JobQueue()
_sessions: dict[str, dict] = {}       # image review sessions: token → {path, created, proposal}
_sessions_lock = threading.Lock()

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac", ".opus", ".webm"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}


@app.middleware("http")
async def private_network_access(request: Request, call_next):
    # Chrome Private Network Access: allow pages/extensions to reach this loopback server
    response = await call_next(request)
    if request.headers.get("access-control-request-private-network") == "true":
        response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response


# ── helpers ────────────────────────────────────────────────────────────────────

def _token() -> str:
    return uuid.uuid4().hex


async def _save_upload(file: UploadFile, allowed: set[str], default_ext: str) -> Path:
    ext = Path(file.filename or "").suffix.lower() or default_ext
    if ext not in allowed:
        raise HTTPException(415, f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(allowed))}")
    path = settings.work_dir / f"in_{_token()}{ext}"
    limit = settings.max_upload_mb * 1024 * 1024
    size = 0
    with open(path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                f.close(); path.unlink(missing_ok=True)
                raise HTTPException(413, f"File exceeds {settings.max_upload_mb} MB")
            f.write(chunk)
    return path


def _output(name_ext: str) -> tuple[str, Path]:
    name = f"redacted_{_token()}{name_ext}"
    return name, settings.work_dir / name


def _cleanup_loop():
    """Delete uploads/outputs and review sessions older than the TTL."""
    while True:
        cutoff = time.time() - settings.file_ttl_minutes * 60
        for p in settings.work_dir.glob("*"):
            try:
                if p.is_file() and p.stat().st_mtime < cutoff:
                    p.unlink()
            except OSError:
                pass
        with _sessions_lock:
            for t in [t for t, s in _sessions.items() if s["created"] < cutoff]:
                _sessions.pop(t, None)
        time.sleep(300)


# ── status ─────────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    from privex_core import audio
    return {
        "status": "ok",
        "version": __version__,
        "llm": False,
        "engines": {
            "ner": settings.spacy_model if ner.is_available() else None,
            "face": detector().backend,
            "ocr": "rapidocr-onnx" + ("" if ocr.is_loaded() else " (lazy)"),
            "asr": f"faster-whisper:{settings.asr_model}" + ("" if audio.is_loaded() else " (lazy)"),
        },
        "threshold": settings.threshold,
        "max_upload_mb": settings.max_upload_mb,
    }


# ── text ───────────────────────────────────────────────────────────────────────

class TextIn(BaseModel):
    text: str = Field(max_length=500_000)
    threshold: float | None = Field(default=None, ge=0, le=1)
    style: str = Field(default="mask", pattern="^(mask|tag)$")


@app.post("/api/text/scan")
def scan_text(body: TextIn):
    analyzer = default_analyzer() if body.threshold is None else Analyzer(threshold=body.threshold)
    return analyzer.scan(body.text, style=body.style)


# ── image: propose → review → apply ────────────────────────────────────────────

def _propose(path: Path) -> dict:
    image = img_mod.decode(path.read_bytes())
    result = img_mod.propose(image)
    token = _token()
    with _sessions_lock:
        _sessions[token] = {"path": path, "created": time.time(), "proposal": result}
    result["session_token"] = token
    result["preview_jpg_b64"] = base64.b64encode(img_mod.encode(image, ".jpg", 88)).decode()
    return result


@app.post("/api/image/propose")
async def image_propose(file: UploadFile = File(...)):
    path = await _save_upload(file, IMAGE_EXT, ".jpg")
    try:
        return await run_in_threadpool(_propose, path)
    except ValueError as e:
        path.unlink(missing_ok=True)
        raise HTTPException(400, str(e))


@app.get("/api/image/session/{token}")
def image_session(token: str):
    """Re-open a review session (used when the extension hands an image to the app)."""
    with _sessions_lock:
        s = _sessions.get(token)
    if not s or not s["path"].exists():
        raise HTTPException(404, "Session not found or expired")
    image = img_mod.decode(s["path"].read_bytes())
    return dict(s["proposal"], session_token=token,
                preview_jpg_b64=base64.b64encode(img_mod.encode(image, ".jpg", 88)).decode())


class Box(BaseModel):
    x: int
    y: int
    w: int
    h: int


class ApplyIn(BaseModel):
    session_token: str
    boxes: list[Box]
    style: str = Field(default="black", pattern="^(black|blur|pixelate)$")


@app.post("/api/image/apply")
def image_apply(body: ApplyIn):
    with _sessions_lock:
        s = _sessions.get(body.session_token)
    if not s or not s["path"].exists():
        raise HTTPException(404, "Session not found or expired. Re-upload the image.")
    image = img_mod.decode(s["path"].read_bytes())
    out, applied = img_mod.apply(image, [b.model_dump() for b in body.boxes], body.style)
    ext = s["path"].suffix.lower()
    ext = ext if ext in (".png", ".jpg", ".jpeg", ".webp") else ".png"
    name, path = _output(ext)
    path.write_bytes(img_mod.encode(out, ext))
    return {"applied_count": applied, "redacted_file": name,
            "redacted_b64": base64.b64encode(img_mod.encode(out, ".jpg", 88)).decode()}


# ── audio / video (background jobs) ────────────────────────────────────────────

def _job_response(job):
    return JSONResponse(job.public(), status_code=202)


@app.post("/api/audio")
async def audio_job(file: UploadFile = File(...)):
    from privex_core.audio import redact_audio
    src = await _save_upload(file, AUDIO_EXT, ".wav")
    name, out = _output(src.suffix if src.suffix != ".webm" else ".wav")

    def work(progress):
        r = redact_audio(str(src), str(out), progress)
        r["redacted_file"] = name
        return r

    return _job_response(jobs.submit("audio", work, on_done=lambda j: src.unlink(missing_ok=True)))


@app.post("/api/video")
async def video_job(file: UploadFile = File(...)):
    from privex_core.video import redact_video
    src = await _save_upload(file, VIDEO_EXT, ".mp4")
    name, out = _output(".mp4")

    def work(progress):
        r = redact_video(str(src), str(out), progress)
        thumb = r.pop("thumbnail_jpg", None)
        r["thumbnail_b64"] = base64.b64encode(thumb).decode() if thumb else ""
        r["redacted_file"] = name
        return r

    return _job_response(jobs.submit("video", work, on_done=lambda j: src.unlink(missing_ok=True)))


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job.public()


# ── downloads ─────────────────────────────────────────────────────────────────

@app.get("/api/files/{name}")
def download(name: str):
    if not name.startswith("redacted_") or Path(name).name != name:
        raise HTTPException(404, "File not found")
    path = settings.work_dir / name
    if not path.exists():
        raise HTTPException(404, "File not found or expired")
    return FileResponse(path, filename=name)


# ── web UI ────────────────────────────────────────────────────────────────────

def _ui_dir() -> Path | None:
    for cand in (os.environ.get("PRIVEX_UI_DIR"), BACKEND_ROOT / "ui",
                 BACKEND_ROOT.parent / "frontend" / "dist"):
        if cand and Path(cand, "index.html").exists():
            return Path(cand)
    return None


if (ui := _ui_dir()) is not None:
    app.mount("/", StaticFiles(directory=ui, html=True), name="ui")
else:
    @app.get("/")
    def no_ui():
        return {"message": "PRIVEX API running. UI not built — run `npm run build` in frontend/.",
                "docs": "/docs"}
