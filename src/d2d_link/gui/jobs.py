"""Runs on worker processes, a queue the page polls, results cached by config.

A job is ``(kind, config, params)``:

- ``run``          -- ``run_link`` and the report (what the page is made of);
- ``sensitivity``  -- ``report.sensitivity`` (every model / survey knob
                      +-20 %, 1 + 2 x knobs runs, progress per run);
- ``rate_sweep``   -- the same config at every survey data rate;
- ``sweep``        -- the config along one axis (``params["axis"]``:
                      ``track_bw``, ``local_pll_fn`` or ``reach``), one run
                      per point plus the clock's closed-form residual.

Results are plain dicts (picklable, JSON-able) so the page never touches a
``LinkResult`` across the process boundary. ``JobManager(workers=0)`` runs
inline, for tests. Progress travels through a manager dict the workers
write ``(done, total)`` into.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import time
import uuid
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from ..config import LinkConfig
from ..config.loader import config_from_dict, config_to_dict

KINDS = ("run", "sensitivity", "rate_sweep", "sweep")

SWEEP_AXES = {
    "track_bw": ("clocking.track_bw_hz", "tracker bandwidth [Hz]",
                 [None, 1e5, 3e5, 1e6, 3e6, 1e7, 3e7, 1e8, 3e8, 1e9, 3e9, 1e10]),
    "local_pll_fn": ("clocking.local_pll_fn_hz", "local PLL natural frequency [Hz]",
                     [1e4, 3e4, 1e5, 3e5, 1e6, 3e6, 1e7, 3e7, 1e8, 3e8, 1e9]),
    "reach": ("channel.length_mm", "line length [mm]", [5.0 * k for k in range(1, 11)] + [60.0]),   # 5..50 by 5, then 60
}


def config_hash(cfg: LinkConfig) -> str:
    """A stable key for the frozen config (its YAML form, sorted)."""
    return hashlib.sha256(json.dumps(config_to_dict(cfg), sort_keys=True).encode()).hexdigest()[:16]


def _lane_rows(cfg, res) -> list[dict]:
    from ..engine.lanes import aggressors_of

    lm = res.lanes
    out = []
    for r in res.stat:
        phys = lm.logical_to_physical[r.lane]
        aggr = [int(q) for _, _, q in aggressors_of(cfg, lm, phys, res.skew_ps) if q < 10_000]
        out.append({
            "lane": r.lane, "physical": phys, "aggressors": aggr,
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
    return out


def execute(kind: str, cfg_dict: dict, params: dict | None = None, progress=None, key: str | None = None) -> dict:
    """The worker's body. Importable at module level so a process pool can
    pickle it; ``progress[key] = (done, total)`` reports where it is."""
    from ..clock.forwarded import ForwardedClock
    from ..config import apply_overrides
    from ..engine import run_link
    from ..report import report, sensitivity
    from ..spec import survey

    params = params or {}
    cfg = config_from_dict(cfg_dict)
    t0 = time.perf_counter()

    def tick(done: int, total: int) -> None:
        if progress is not None and key is not None:
            progress[key] = (done, total)

    if kind == "run":
        tick(0, 1)
        res = run_link(cfg)
        rep = report(cfg, res, ForwardedClock(cfg))
        tick(1, 1)
        worst = res.worst
        return {"kind": kind, "report": rep, "lanes": _lane_rows(cfg, res), "worst_lane": worst.lane,
                "passes": bool(res.passes), "elapsed_s": time.perf_counter() - t0,
                "unrepaired": list(res.lanes.unrepaired), "active": res.lanes.active_width,
                "requested": res.lanes.requested_width, "repair": res.lanes.mode,
                "failed": list(res.lanes.failed), "physical_count": cfg.lanes.physical_count,
                "swing_vpp": cfg.tx.swing_vpp}
    if kind == "sensitivity":
        sens = sensitivity(cfg, progress=tick)
        return {"kind": kind, "sensitivity": sens, "elapsed_s": time.perf_counter() - t0}
    if kind == "rate_sweep":
        rates = [float(r) for r in survey("data_rates_gtps").value]
        rows = []
        tick(0, len(rates))
        for i, rate in enumerate(rates):
            c = apply_overrides(cfg, {"data_rate_gtps": rate})
            res = run_link(c)
            w = res.worst
            rows.append({"rate_gtps": rate, "passes": bool(res.passes), "worst_lane": w.lane,
                         "eye_height_mv": 1e3 * res.eye_height_min_v, "eye_width_ui": res.eye_width_min_ui,
                         "log10_ber": float(w.log10_ber),
                         "il_db": float(res.stat[0].extras["insertion_loss_nyquist_db"]) if res.stat else None})
            tick(i + 1, len(rates))
        return {"kind": kind, "rows": rows, "package": cfg.package.kind, "length_mm": cfg.channel.length_mm,
                "elapsed_s": time.perf_counter() - t0}
    if kind == "sweep":
        axis = params.get("axis", "track_bw")
        path, _label, default_points = SWEEP_AXES[axis]
        points = params.get("points") or default_points
        rows = []
        tick(0, len(points))
        for i, value in enumerate(points):
            c = apply_overrides(cfg, {path: value})
            res = run_link(c)
            w = res.worst
            rows.append({"value": value, "passes": bool(res.passes), "worst_lane": w.lane,
                         "eye_height_mv": 1e3 * res.eye_height_min_v, "eye_width_ui": res.eye_width_min_ui,
                         "residual_fs": 1e15 * ForwardedClock(c).residual_sigma_s(),
                         "log10_ber": float(w.log10_ber)})
            tick(i + 1, len(points))
        return {"kind": kind, "axis": axis, "path": path, "rows": rows, "elapsed_s": time.perf_counter() - t0}
    raise ValueError(f"unknown job kind {kind!r}")


def default_cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "d2d_link" / "gui"


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
    progress: tuple[int, int] | None = None

    @property
    def elapsed_s(self) -> float | None:
        if self.started is None:
            return None
        return (self.finished or time.time()) - self.started


class JobManager:
    """A small queue over a process pool with a result cache.

    ``submit`` returns at once; a config already computed for the same kind
    and params comes back ``done`` with the cached result. ``poll`` moves
    futures to done/failed and must be called from the page's interval
    callback. ``workers=0`` executes inline (tests)."""

    def __init__(self, workers: int = 2, cache_dir: Path | str | None = None):
        self.workers = workers
        self.cache_dir = Path(cache_dir) if cache_dir else None     # None: memory only
        self._pool = ProcessPoolExecutor(max_workers=workers) if workers > 0 else None
        self._mgr = multiprocessing.Manager() if workers > 0 else None
        self._progress = self._mgr.dict() if self._mgr is not None else {}
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
        cached = self._cache.get(self._key(kind, h, params))
        if cached is None:
            cached = self._load_disk(kind, h, params)
        if cached is not None:
            job.status, job.result = "done", cached
            job.started = job.finished = time.time()
            self._jobs[job.id] = job
            self._order.append(job.id)
            return job
        if any(j.status in ("queued", "running") and self._key(j.kind, j.cfg_hash, j.params) == self._key(kind, h, params)
               for j in self._jobs.values()):
            return next(j for j in self._jobs.values()
                        if j.status in ("queued", "running") and self._key(j.kind, j.cfg_hash, j.params) == self._key(kind, h, params))
        self._jobs[job.id] = job
        self._order.append(job.id)
        if self._pool is None:
            job.status, job.started = "running", time.time()
            try:
                job.result = execute(kind, job.cfg_dict, job.params, self._progress, job.id)
                job.status = "done"
                self._remember(job)
            except Exception as exc:        # noqa: BLE001 -- the page shows the error
                job.status, job.error = "failed", f"{type(exc).__name__}: {exc}"
            job.finished = time.time()
            job.progress = self._progress.get(job.id)
            return job
        job.future = self._pool.submit(execute, kind, job.cfg_dict, job.params, self._progress, job.id)
        return job

    def _remember(self, job: Job) -> None:
        self._cache[self._key(job.kind, job.cfg_hash, job.params)] = job.result
        if job.started is not None and job.finished is not None:
            self._durations.setdefault(self._bucket(job), []).append(job.finished - job.started)
        self._save_disk(job)

    # ---------------------------------------------------------- disk cache
    def _disk_path(self, kind: str, cfg_hash: str, params: dict | None) -> Path | None:
        if self.cache_dir is None:
            return None
        ph = hashlib.sha256(json.dumps(params or {}, sort_keys=True).encode()).hexdigest()[:8]
        return self.cache_dir / f"{kind}-{cfg_hash}-{ph}.json"

    def _load_disk(self, kind: str, cfg_hash: str, params: dict | None) -> dict | None:
        p = self._disk_path(kind, cfg_hash, params)
        if p is None or not p.is_file():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if data.get("kind") != kind:
            return None
        self._cache[self._key(kind, cfg_hash, params)] = data
        return data

    def _save_disk(self, job: Job) -> None:
        p = self._disk_path(job.kind, job.cfg_hash, job.params)
        if p is None or job.result is None:
            return
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(job.result), encoding="utf-8")
            tmp.replace(p)
        except OSError:
            pass                                 # a cache that cannot be written is just no cache

    @staticmethod
    def _bucket(job: Job) -> str:
        return f"{job.kind}:{job.scope}"

    # -------------------------------------------------------------- poll
    def poll(self) -> list[Job]:
        """Advance states from the futures and progress; every job, oldest first."""
        for jid in self._order:
            job = self._jobs[jid]
            if job.future is None or job.status in ("done", "failed", "cancelled"):
                continue
            prog = self._progress.get(jid)
            if prog is not None:
                job.progress = tuple(prog)
                if job.status == "queued":
                    job.status, job.started = "running", time.time()
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
        """From the job's own progress when it reports one, else from earlier
        runs of the same kind and scope; None without either."""
        el = job.elapsed_s or 0.0
        if job.progress and job.progress[0] > 0:
            done, total = job.progress
            return max(0.0, el / done * (total - done))
        hist = self._durations.get(self._bucket(job))
        if not hist:
            return None
        est = sum(hist[-3:]) / len(hist[-3:])
        return max(0.0, est - el)

    def latest_done(self, cfg_hash: str, kind: str = "run") -> Job | None:
        for jid in reversed(self._order):
            job = self._jobs[jid]
            if job.cfg_hash == cfg_hash and job.kind == kind and job.status == "done":
                return job
        return None

    def pending(self, cfg_hash: str, kind: str = "run") -> Job | None:
        for jid in reversed(self._order):
            job = self._jobs[jid]
            if job.cfg_hash == cfg_hash and job.kind == kind and job.status in ("queued", "running"):
                return job
        return None

    def shutdown(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
        if self._mgr is not None:
            self._mgr.shutdown()


__all__ = ["JobManager", "Job", "execute", "config_hash", "KINDS", "SWEEP_AXES", "default_cache_dir"]
