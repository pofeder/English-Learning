"""Small in-process job queue for slow AI grading requests."""

import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import RLock


try:
    _MAX_WORKERS = max(1, int(os.getenv("AI_JOB_WORKERS", "2")))
except ValueError:
    _MAX_WORKERS = 2

_executor = ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix="ai-job")
_jobs = {}
_active_keys = {}
_lock = RLock()
_MAX_JOBS = 256
_JOB_TTL_SECONDS = 60 * 60


def _cleanup_locked():
    cutoff = time.time() - _JOB_TTL_SECONDS
    expired = [
        job_id for job_id, job in _jobs.items()
        if job.get("finished_at", job.get("created_at", 0)) < cutoff
    ]
    for job_id in expired:
        _jobs.pop(job_id, None)
    if len(_jobs) > _MAX_JOBS:
        oldest = sorted(_jobs.items(), key=lambda item: item[1].get("created_at", 0))
        for job_id, _ in oldest[: len(_jobs) - _MAX_JOBS]:
            _jobs.pop(job_id, None)


def submit_job(kind, function, dedupe_key=None):
    """Queue a callable and return its job id.

    A dedupe key prevents duplicate submissions for the same exercise while
    one grading request is already queued or running.
    """
    with _lock:
        _cleanup_locked()
        if dedupe_key:
            existing = _active_keys.get(dedupe_key)
            if existing and existing in _jobs:
                return existing

        job_id = uuid.uuid4().hex
        _jobs[job_id] = {
            "job_id": job_id,
            "kind": kind,
            "status": "queued",
            "created_at": time.time(),
        }
        if dedupe_key:
            _active_keys[dedupe_key] = job_id

    _executor.submit(_run_job, job_id, function, dedupe_key)
    return job_id


def _run_job(job_id, function, dedupe_key):
    with _lock:
        if job_id in _jobs:
            _jobs[job_id]["status"] = "running"
            _jobs[job_id]["started_at"] = time.time()
    try:
        result = function()
        with _lock:
            if job_id in _jobs:
                _jobs[job_id].update({
                    "status": "succeeded",
                    "result": result,
                    "finished_at": time.time(),
                })
    except Exception as exc:
        with _lock:
            if job_id in _jobs:
                _jobs[job_id].update({
                    "status": "failed",
                    "error": str(exc),
                    "finished_at": time.time(),
                })
    finally:
        with _lock:
            if dedupe_key and _active_keys.get(dedupe_key) == job_id:
                _active_keys.pop(dedupe_key, None)


def get_job(job_id):
    with _lock:
        job = _jobs.get(str(job_id))
        return deepcopy(job) if job else None
