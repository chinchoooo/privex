"""
Audio redaction: faster-whisper (CTranslate2, int8 CPU) word timestamps →
text analyzer → mute the time ranges of sensitive words.
"""

from __future__ import annotations

import logging
import re
import shutil
import threading
from dataclasses import dataclass
from typing import Callable

from privex_core import media
from privex_core.config import settings
from privex_core.text.analyzer import default_analyzer

log = logging.getLogger(__name__)

_model = None
_lock = threading.Lock()

PAD_S = 0.08            # padding around muted words


@dataclass
class Word:
    text: str
    start: float
    end: float
    norm: str = ""      # analysis form (spoken digits → numerals)
    cstart: int = 0     # char offsets in the analysis text
    cend: int = 0


def model():
    global _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel
            src = settings.asr_model
            local = settings.models_dir / "asr" / src
            if local.exists():
                src = str(local)
            log.info("Loading faster-whisper model %s (%s)", src, settings.asr_compute_type)
            _model = WhisperModel(src, device="cpu", compute_type=settings.asr_compute_type,
                                  download_root=str(settings.asr_cache_dir))
    return _model


def is_loaded() -> bool:
    return _model is not None


def transcribe(path: str, progress: Callable[[float], None] | None = None) -> tuple[str, list[Word], float]:
    segments, info = model().transcribe(
        path, language="en", word_timestamps=True, beam_size=5, temperature=0,
        condition_on_previous_text=False, vad_filter=True,
    )
    words, texts = [], []
    for seg in segments:
        texts.append(seg.text.strip())
        for w in seg.words or []:
            words.append(Word(w.word.strip(), float(w.start), float(w.end)))
        if progress and info.duration:
            progress(min(1.0, seg.end / info.duration))
    return " ".join(texts), words, float(info.duration or 0)


# ── spoken-number normalisation ────────────────────────────────────────────────

_NUM = {"zero": "0", "oh": "0", "o": "0", "one": "1", "two": "2", "three": "3", "four": "4",
        "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9"}
_REPEAT = {"double": 2, "triple": 3}


def _normalise(words: list[Word]) -> str:
    """
    Build the analysis string. Spoken digits become numerals ("nine eight seven" → "987"),
    "double five" → "55", and consecutive short digit groups are joined so phone/card/account
    numbers dictated in chunks are recognised. Each word keeps its character span.
    """
    keys = [re.sub(r"[^\w@.\-/+]", "", w.text).lower() for w in words]
    for i, w in enumerate(words):
        k = keys[i]
        if i and keys[i - 1] in _REPEAT and k in _NUM:
            w.norm = _NUM[k] * _REPEAT[keys[i - 1]]
        elif k in _REPEAT and i + 1 < len(keys) and keys[i + 1] in _NUM:
            w.norm = ""          # merged into the next word
        elif k in _NUM and (k not in ("oh", "o") or _digitish(keys, i)):
            w.norm = _NUM[k]
        else:
            w.norm = w.text

    parts, pos, prev_digit = [], 0, False
    for w in words:
        if w.norm == "" and w.text:
            w.cstart = w.cend = pos
            continue
        token = w.norm
        # Only bare digit groups are glued ("987 654 3210" → "9876543210");
        # punctuation marks a boundary ("January 7, 1973" stays intact).
        is_digit = bool(re.fullmatch(r"\d{1,4}", token))
        sep = "" if (prev_digit and is_digit) or not parts else " "
        parts.append(sep + token)
        pos += len(sep)
        w.cstart, w.cend = pos, pos + len(token)
        pos = w.cend
        prev_digit = is_digit
    return "".join(parts)


def _digitish(keys: list[str], i: int) -> bool:
    near = keys[max(0, i - 1):i] + keys[i + 1:i + 2]
    return any(k in _NUM or k.isdigit() for k in near)


def _merge(ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for s, e in sorted(ranges):
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def find_sensitive(words: list[Word]) -> tuple[str, list[dict], list[tuple[float, float]]]:
    analyzer = default_analyzer()
    text = _normalise(words)
    entities = analyzer.analyze(text)
    ranges, ents = [], []
    for e in entities:
        hit = [w for w in words if w.cstart < e.end and e.start < w.cend]
        d = e.to_dict(analyzer.threshold)
        if hit:
            d["start_s"], d["end_s"] = round(hit[0].start, 2), round(hit[-1].end, 2)
        ents.append(d)
        if e.score >= analyzer.threshold and hit:
            ranges.append((max(0.0, hit[0].start - PAD_S), hit[-1].end + PAD_S))
    return text, ents, _merge(ranges)


def redact_audio(input_path: str, output_path: str,
                 progress: Callable[[float, str], None] | None = None) -> dict:
    p = progress or (lambda f, m: None)
    p(0.05, "loading speech model")
    model()
    p(0.1, "transcribing")
    transcript, words, duration = transcribe(input_path, lambda f: p(0.1 + 0.75 * f, "transcribing"))
    p(0.85, "detecting sensitive speech")
    analysis_text, entities, ranges = find_sensitive(words)

    p(0.9, "muting")
    filt = media.mute_filter(ranges)
    if filt:
        media.run(["-i", input_path, "-af", filt, output_path])
    else:
        shutil.copyfile(input_path, output_path)

    sensitive = [e for e in entities if e["sensitive"]]
    return {
        "sensitive": bool(sensitive),
        "entity_count": len(sensitive),
        "entities": entities,
        "transcript": transcript,
        "analysis_text": analysis_text,
        "duration_seconds": round(duration, 2),
        "muted_segments": [{"start": round(s, 3), "end": round(e, 3)} for s, e in ranges],
        "muted_count": len(ranges),
    }
