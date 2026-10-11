"""
In-process job queue for long-running work (audio/video).

A single worker thread: the models are CPU-bound and not thread-safe, so
running jobs one at a time is both simpler and faster than contention.
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)


@dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"          # queued | running | done | error
    progress: float = 0.0
    message: str = "queued"
    result: dict | None = None
    error: str | None = None
    created: float = field(default_factory=time.time)

    def public(self) -> dict:
        return {"id": self.id, "kind": self.kind, "status": self.status,
                "progress": round(self.progress, 3), "message": self.message,
                "result": self.result, "error": self.error}


class JobQueue:
    def __init__(self, max_jobs: int = 200):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="privex-job")
        self._max = max_jobs

    def submit(self, kind: str, fn: Callable[[Callable[[float, str], None]], dict],
               on_done: Callable[[Job], Any] | None = None) -> Job:
        job = Job(uuid.uuid4().hex, kind)
        with self._lock:
            self._jobs[job.id] = job
            if len(self._jobs) > self._max:
                for old in sorted(self._jobs.values(), key=lambda j: j.created)[: len(self._jobs) - self._max]:
                    if old.status in ("done", "error"):
                        self._jobs.pop(old.id, None)

        def progress(frac: float, msg: str):
            job.progress, job.message = max(job.progress, min(1.0, frac)), msg

        def run():
            job.status, job.message = "running", "starting"
            try:
                job.result = fn(progress)
                job.status, job.progress, job.message = "done", 1.0, "done"
            except Exception as e:
                log.error("Job %s failed: %s\n%s", job.id, e, traceback.format_exc())
                job.status, job.error, job.message = "error", str(e), "failed"
            finally:
                if on_done:
                    on_done(job)

        self._pool.submit(run)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)
