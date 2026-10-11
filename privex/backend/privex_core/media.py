"""ffmpeg helpers. Uses the static ffmpeg shipped in the imageio-ffmpeg wheel — no system install."""

from __future__ import annotations

import subprocess
import sys
from functools import lru_cache


@lru_cache(maxsize=1)
def ffmpeg_exe() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _no_window() -> dict:
    # Don't flash a console window from the packaged (windowless) app on Windows.
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def run(args: list[str]) -> None:
    proc = subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", *args],
                          capture_output=True, **_no_window())
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.decode(errors='replace')[-800:]}")


def popen(args: list[str]) -> subprocess.Popen:
    return subprocess.Popen([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", *args],
                            stdin=subprocess.PIPE, stderr=subprocess.PIPE, **_no_window())


def mute_filter(ranges: list[tuple[float, float]]) -> str | None:
    if not ranges:
        return None
    return ",".join(f"volume=enable='between(t,{s:.3f},{e:.3f})':volume=0" for s, e in ranges)


def has_audio(path: str) -> bool:
    try:
        import av
        with av.open(path) as c:
            return len(c.streams.audio) > 0
    except Exception:
        return False
