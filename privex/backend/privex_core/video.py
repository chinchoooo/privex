"""
Video redaction (streaming; memory use is independent of clip length).

  1. Audio: faster-whisper on the container's audio track → mute ranges.
  2. Pass 1: OCR + text analysis on sampled frames (every `video_ocr_interval_s`).
     Values confirmed sensitive in any sample are treated as sensitive in all samples.
  3. Pass 2: face detection on every frame (held for one extra frame to avoid flicker);
     text boxes for frame i = union of the samples before and after i, so text that moves
     between samples stays covered. Frames are piped straight into ffmpeg (H.264 + AAC).
"""

from __future__ import annotations

import logging
import re
from typing import Callable

import cv2

from privex_core import audio, media
from privex_core.config import settings
from privex_core.entities import LABELS
from privex_core.text.analyzer import default_analyzer
from privex_core.vision import image as img_mod
from privex_core.vision import ocr
from privex_core.vision.faces import detector

log = logging.getLogger(__name__)

STATIC_DIFF = 2.0        # mean abs grey-level change below which a frame is considered unchanged


def _probe(path: str) -> tuple[float, int, int, int]:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise ValueError("Cannot open video")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return fps, w, h, n


def _center(b: dict) -> tuple[float, float]:
    return b["x"] + b["w"] / 2, b["y"] + b["h"] / 2


def _motion_cover(a: list[dict], b: list[dict], max_shift: float) -> list[dict]:
    """
    Boxes for a frame between samples A and B. Each box in A is paired with the nearest
    similar-sized box in B; the pair is replaced by their bounding rectangle so the text
    stays covered along its whole path. Unpaired boxes are kept as-is.
    """
    out, used = [], set()
    for x in a:
        cx, cy = _center(x)
        best, best_d = None, max_shift
        for j, y in enumerate(b):
            if j in used or not (0.5 < (y["w"] + 1) / (x["w"] + 1) < 2 and 0.5 < (y["h"] + 1) / (x["h"] + 1) < 2):
                continue
            yx, yy = _center(y)
            d = ((cx - yx) ** 2 + (cy - yy) ** 2) ** 0.5
            if d < best_d:
                best, best_d = j, d
        if best is None:
            out.append(x)
        else:
            used.add(best)
            out.append(img_mod.union([x, b[best]]))
    out += [y for j, y in enumerate(b) if j not in used]
    return out


def redact_video(input_path: str, output_path: str,
                 progress: Callable[[float, str], None] | None = None) -> dict:
    p = progress or (lambda f, m: None)
    analyzer = default_analyzer()
    fps, W, H, n_frames = _probe(input_path)
    duration = n_frames / fps if n_frames else 0
    if duration > settings.max_video_seconds:
        raise ValueError(f"Video is {duration:.0f}s; limit is {settings.max_video_seconds:.0f}s "
                         "(set PRIVEX_MAX_VIDEO_SECONDS to change)")

    # ── 1. audio ──────────────────────────────────────────────────────────────
    audio_result, mute_ranges, with_audio = None, [], media.has_audio(input_path)
    if with_audio:
        p(0.02, "transcribing audio")
        _, words, _ = audio.transcribe(input_path, lambda f: p(0.02 + 0.2 * f, "transcribing audio"))
        analysis_text, a_ents, mute_ranges = audio.find_sensitive(words)
        audio_result = {"transcript": analysis_text, "entities": a_ents}

    # ── 2. pass 1: OCR on samples ─────────────────────────────────────────────
    step = max(1, round(fps * settings.video_ocr_interval_s))
    samples: dict[int, tuple[list[ocr.OcrLine], str, list]] = {}
    cap = cv2.VideoCapture(input_path)
    idx, last_small, ocr_runs = 0, None, 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if idx % step == 0:
            _, frame = cap.retrieve()
            small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (160, 90))
            if last_small is not None and cv2.absdiff(small, last_small).mean() < STATIC_DIFF:
                samples[idx] = samples[max(samples)]          # static scene: reuse the last OCR
            else:
                lines = ocr.run_ocr(frame)
                doc = ocr.build_document(lines)
                ents = analyzer.analyze(ocr.normalize_for_analysis(doc)) if doc else []
                for e in ents:
                    e.text = doc[e.start:e.end]
                samples[idx] = (lines, doc, ents)
                last_small, ocr_runs = small, ocr_runs + 1
            p(0.22 + 0.38 * (idx / max(1, n_frames)), f"reading text in frame {idx}")
        idx += 1
    cap.release()
    total = idx

    sensitive_values: dict[str, str] = {}
    for _, _, ents in samples.values():
        for e in ents:
            if e.score >= analyzer.threshold:
                sensitive_values.setdefault(e.text, e.type)

    sample_boxes: dict[int, list[dict]] = {}
    for i, (lines, doc, ents) in samples.items():
        boxes = []
        for e in ents:
            if e.score >= analyzer.threshold:
                boxes += ocr.span_to_boxes(lines, e.start, e.end)
        for value in sensitive_values:           # values confirmed in any sample are boxed everywhere
            for m in re.finditer(re.escape(value), doc):
                boxes += ocr.span_to_boxes(lines, m.start(), m.end())
        sample_boxes[i] = boxes

    max_shift = 0.25 * max(W, H)

    def text_boxes(i: int) -> list[dict]:
        prev = (i // step) * step
        a, b = sample_boxes.get(prev, []), sample_boxes.get(prev + step, [])
        return _motion_cover(a, b, max_shift)

    # ── 3. pass 2: faces + write ──────────────────────────────────────────────
    args = ["-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", f"{fps:.6f}", "-i", "-"]
    if with_audio:
        args += ["-i", input_path, "-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-b:a", "160k"]
        filt = media.mute_filter(mute_ranges)
        if filt:
            args += ["-af", filt]
    args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
             "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-movflags", "+faststart", output_path]
    proc = media.popen(args)

    cap = cv2.VideoCapture(input_path)
    face_hits, prev_faces, thumb, i = 0, [], None, 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            faces = [f.bbox() for f in detector().detect(frame)]
            face_hits += len(faces)
            red, _ = img_mod.apply(frame, faces + prev_faces + text_boxes(i))
            prev_faces = faces
            if thumb is None:
                thumb = red
            proc.stdin.write(red.tobytes())
            i += 1
            if i % 10 == 0:
                p(0.6 + 0.38 * (i / max(1, total)), f"redacting frame {i}/{total}")
    finally:
        cap.release()
        proc.stdin.close()
        err = proc.stderr.read().decode(errors="replace")
        proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {err[-800:]}")

    entities = [{"type": t, "label": LABELS.get(t, t), "text": v, "sensitive": True,
                 "source": "ocr+analyzer"} for v, t in sensitive_values.items()]
    if audio_result:
        entities += [dict(e, source="audio") for e in audio_result["entities"] if e["sensitive"]]
    return {
        "sensitive": bool(entities) or face_hits > 0,
        "entity_count": len(entities),
        "entities": entities,
        "face_detections": face_hits,
        "frames_processed": total,
        "ocr_samples": len(samples),
        "ocr_runs": ocr_runs,
        "duration_seconds": round(duration, 2),
        "sensitive_values": list(sensitive_values),
        "transcript": audio_result["transcript"] if audio_result else "",
        "muted_segments": [{"start": round(s, 3), "end": round(e, 3)} for s, e in mute_ranges],
        "muted_count": len(mute_ranges),
        "thumbnail_jpg": img_mod.encode(thumb, ".jpg", 80) if thumb is not None else None,
    }
