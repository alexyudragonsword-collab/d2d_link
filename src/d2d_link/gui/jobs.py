"""Runs on worker processes, a queue the page polls, results cached by config.

A job is ``(kind, config, params)``. ``run`` calls ``run_link`` and builds
the report; later kinds (sensitivity, sweeps) follow the same shape. The
result is a plain dict (picklable, JSON-able) so the page never touches a
``LinkResult`` object across the process boundary. ``JobManager(workers=0)``
runs inline, for tests.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import dataclass, field

from ..config import LinkConfig
from ..config.loader import config_from_dict, config_to_dict

KINDS = ("run",)


def config_hash(cfg: LinkConfig) -> str:
    """A stable key for the frozen config (its YAML form, sorted)."""
    return hashlib.sha256(json.dumps(config_to_dict(cfg), sort_keys=True).encode()).hexdigest()[:16]


def execute(kind: str, cfg_dict: dict, params: dict | None = None) -> dict:
    """The worker's body: a report dict plus what the page draws per lane.
    Importable at module level so a process pool can pickle it."""
    from ..clock.forwarded import ForwardedClock
    from ..engine import run_link
    from ..report import report

    cfg = config_from_dict(cfg_dict)
    t0 = time.perf_counter()
    if kind == "run":
        res = run_link(cfg)
        rep = report(cfg, res, ForwardedClock(cfg))
        lanes = []
        for r in res.stat:
            lanes.append({
                "lane": r.lane, "physical": res.lanes.logical_to_physical[r.lane],
                "bathtub_phase_ui": [float(x) for x in r.bathtub_phase_ui],
                "bathtub_log10_ber": [float(x) for x in r.bathtub_log10_ber],
                "phase_ui": float(r.phase_ui), "eye_height_v": float(r.eye_height_v),
                "eye_width_ui": float(r.eye_width_ui), "log10_ber": float(r.log10_ber),
                "margin": float(r.margin), "passes": bool(r.passes),
                "eye_height_margin_mv": float(r.eye_height_margin_mv),
                "eye_width_margin_ui": float(r.eye_width_margin_ui),
                "skew_residual_ui": float(r.skew_residual_ui),
                "n_aggressors": int(r.extras["n_aggressors"]), "xtalk_rms_v": float(r.extras["xtalk_rms_v"]),
                "sigma_jitter_s": float(r.sigma_jitter_s), "sigma_noise_v": float(r.sigma_noise_v),
                "main_cursor_v": float(r.main_cursor_v), "n_cursors": int(r.extras["n_cursors"]),
                "centre_offset_ui": float(r.extras.get("centre_offset_ui", 0.0)),
            })
        worst = res.worst
        return {"kind": kind, "report": rep, "lanes": lanes, "worst_lane": worst.lane,
                "passes": bool(res.passes), "elapsed_s": time.perf_counter() - t0,
                "unrepaired": list(res.lanes.unrepaired), "active": res.lanes.active_width,
                "requested": res.lanes.requested_width, "repair": res.lanes.mode,
                "failed": list(res.lanes.failed)}
    raise ValueError(f"unknown job kind {kind!r}")


@dataclass
class Job:
    id: str
    kind: str
    label: str
    cfg_hash: str
    cfg_dict: dict
    params: dict = field(default_factory=dict)
    status: str = "queued"           # queued | running | done | failed | cancelled
    submitted: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    result: dict | None = None
    error: str | None = None
    future: Future | None = field(default=None, repr=False)
    scope: str = ""                  # "8 / 16 lanes" etc., for the queue panel

    @property
    def elapsed_s(self) -> float | None:
        if self.started is None:
            return None
        return (self.finished or time.time()) - self.started

    def to_row(self) -> dict:
        return {"id": self.id, "kind": self.kind, "label": self.label, "status": self.status,
                "scope": self.scope, "elapsed_s": self.elapsed_s, "error": self.error,
                "cfg_hash": self.cfg_hash}


class JobManager:
    """A small queue over a process pool with a result cache.

    ``submit`` returns at once; a config already computed for the same kind
    and params comes back ``done`` with the cached result (the page then
    reopens it instantly). ``poll`` moves futures to done/failed and must be
    called from the page's interval callback. ``workers=0`` executes inline
    (tests, or a machine where a second process is unwelcome)."""

    def __init__(self, workers: int = 2):
        self.workers = workers
        self._pool = ProcessPoolExecutor(max_workers=workers) if workers > 0 else None
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._cache: dict[tuple, dict] = {}
        self._durations: dict[str, list[float]] = {}

    # ------------------------------------------------------------ submit
    @staticmethod
    def _key(kind: str, cfg_hash: str, params: dict | None) -> tuple:
        return (kind, cfg_hash, json.dumps(params or {}, sort_keys=True))

    def submit(self, kind: str, cfg: LinkConfig, params: dict | None = None, label: str = "",
               scope: str = "") -> Job:
        if kind not in KINDS:
            raise ValueError(f"unknown job kind {kind!r}")
        h = config_hash(cfg)
        job = Job(id=uuid.uuid4().hex[:8], kind=kind, label=label or kind, cfg_hash=h,
                  cfg_dict=config_to_dict(cfg), params=dict(params or {}), scope=scope)
        self._jobs[job.id] = job
        self._order.append(job.id)
        cached = self._cache.get(self._key(kind, h, params))
        if cached is not None:
            job.status, job.result = "done", cached
            job.started = job.finished = time.time()
            return job
        if self._pool is None:
            job.status, job.started = "running", time.time()
            try:
                job.result = execute(kind, job.cfg_dict, job.params)
                job.status = "done"
                self._remember(job)
            except Exception as exc:        # noqa: BLE001 -- the page shows the error
                job.status, job.error = "failed", f"{type(exc).__name__}: {exc}"
            job.finished = time.time()
            return job
        job.future = self._pool.submit(execute, kind, job.cfg_dict, job.params)
        job.future.add_done_callback(lambda _f, jid=job.id: self._mark_started(jid))
        if job.future.running():
            job.status, job.started = "running", time.time()
        return job

    def _mark_started(self, jid: str) -> None:
        job = self._jobs.get(jid)
        if job is not None and job.started is None:
            job.started = time.time()

    def _remember(self, job: Job) -> None:
        self._cache[self._key(job.kind, job.cfg_hash, job.params)] = job.result
        if job.started is not None and job.finished is not None:
            self._durations.setdefault(self._bucket(job), []).append(job.finished - job.started)

    @staticmethod
    def _bucket(job: Job) -> str:
        return f"{job.kind}:{job.scope}"

    # -------------------------------------------------------------- poll
    def poll(self) -> list[Job]:
        """Advance states from the futures; returns every job, oldest first."""
        for jid in self._order:
            job = self._jobs[jid]
            if job.future is None or job.status in ("done", "failed", "cancelled"):
                continue
            if job.future.running() and job.status == "queued":
                job.status, job.started = "running", time.time()
            if job.future.done():
                job.finished = time.time()
                if job.started is None:
                    job.started = job.finished
                if job.future.cancelled():
                    job.status = "cancelled"
                    continue
                exc = job.future.exception()
                if exc is not None:
                    job.status, job.error = "failed", f"{type(exc).__name__}: {exc}"
                else:
                    job.status, job.result = "done", job.future.result()
                    self._remember(job)
        return [self._jobs[j] for j in self._order]

    def cancel(self, jid: str) -> bool:
        job = self._jobs.get(jid)
        if job is None or job.future is None:
            return False
        ok = job.future.cancel()
        if ok:
            job.status, job.finished = "cancelled", time.time()
        return ok

    def get(self, jid: str) -> Job | None:
        return self._jobs.get(jid)

    def eta_s(self, job: Job) -> float | None:
        """A guess from earlier runs of the same kind and scope; None without one."""
        hist = self._durations.get(self._bucket(job))
        if not hist:
            return None
        est = sum(hist[-3:]) / len(hist[-3:])
        return max(0.0, est - (job.elapsed_s or 0.0))

    def latest_done(self, cfg_hash: str, kind: str = "run") -> Job | None:
        for jid in reversed(self._order):
            job = self._jobs[jid]
            if job.cfg_hash == cfg_hash and job.kind == kind and job.status == "done":
                return job
        return None

    def shutdown(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)


__all__ = ["JobManager", "Job", "execute", "config_hash", "KINDS"]
