"""Lanes, skew, repair and the link-level verdict (invariant #4).

A module is ``lanes.count`` data lanes plus ``lanes.spare_count`` spares on
one forwarded clock. :func:`lane_map` decides which physical lane carries
each logical one after the failures in ``lanes.failed`` are repaired the
way the config says (spares, width degradation, or not at all);
:func:`run_link` runs every active lane through the statistical engine --
and the time engine when asked -- with that lane's residual skew, and judges
the link by its worst lane. A single lane is the same code with count = 1.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..channel.model import LinkResponse, link_response
from ..clock.forwarded import ForwardedClock
from ..config.schema import LinkConfig
from ..spec import survey
from .statistical import StatResult, StatisticalEngine, resolved_targets
from .timedomain import TimeResult, run_time


@dataclass(frozen=True)
class LaneMap:
    logical_to_physical: tuple[int, ...]   # active logical lanes -> physical lane
    active_width: int
    requested_width: int
    failed: tuple[int, ...]
    unrepaired: tuple[int, ...]            # failed physical lanes still carrying a logical lane
    mode: str

    @property
    def link_up(self) -> bool:
        return not self.unrepaired and self.active_width > 0

    @property
    def degraded(self) -> bool:
        return self.active_width < self.requested_width


def lane_map(cfg: LinkConfig) -> LaneMap:
    lanes = cfg.lanes
    n, spare = lanes.count, lanes.spare_count
    failed = set(lanes.failed)
    if lanes.repair == "spare":
        working = [p for p in range(n + spare) if p not in failed]
        phys = tuple(working[:n])
        unrep = () if len(working) >= n else tuple(sorted(failed))[: n - len(working)]
        if len(working) < n:
            # not enough working lanes: fill with failed ones so the shortfall is visible
            phys = tuple(working + sorted(failed)[: n - len(working)])
        return LaneMap(phys, n, n, tuple(sorted(failed)), unrep, "spare")
    if lanes.repair == "width_degrade":
        w = n
        while w >= 1:
            for start in range(0, n - w + 1, w):
                block = range(start, start + w)
                if not any(p in failed for p in block):
                    return LaneMap(tuple(block), w, n, tuple(sorted(failed)), (), "width_degrade")
            w //= 2
        return LaneMap(tuple(range(n)), 0, n, tuple(sorted(failed)), tuple(sorted(failed)), "width_degrade")
    phys = tuple(range(n))
    unrep = tuple(sorted(p for p in failed if p < n))
    return LaneMap(phys, n, n, tuple(sorted(failed)), unrep, "none")


def physical_skews_ps(cfg: LinkConfig) -> np.ndarray:
    """Static skew of every physical lane against the forwarded clock [ps]."""
    lanes = cfg.lanes
    n_phys = lanes.physical_count
    out = np.zeros(n_phys)
    given = np.asarray(lanes.skew_ps, dtype=np.float64)
    out[: given.size] = given
    if given.size == 0 and lanes.skew_sigma_ps > 0.0:
        out = np.random.default_rng([lanes.skew_seed, 0x5C3]).normal(0.0, lanes.skew_sigma_ps, n_phys)
    return out


def residual_skew_ui(cfg: LinkConfig, skew_ps: float, tracked: bool | None = None) -> float:
    """What the lane's static skew leaves at the sampler.

    With a per-lane tracker (``clocking.track_bw_hz > 0``) the answer is 0:
    a static offset is DC to the tracking loop, which follows it exactly, and
    all that remains of the deskew is the phase interpolator's quantisation,
    which the engines already carry as a uniform jitter term. Without a
    tracker the one-time deskew leaves the skew modulo its step, centred.
    Earlier versions counted both at once. ``tracked`` overrides the config's
    own answer (tests)."""
    if tracked is None:
        tracked = (cfg.clocking.track_bw_hz or 0.0) > 0.0
    if tracked:
        return 0.0
    step = cfg.lanes.deskew_step_ps
    if step <= 0.0:
        return 0.0
    r = skew_ps - step * np.round(skew_ps / step)
    return float(r * 1e-12 / cfg.ui)


@dataclass
class LinkResult:
    cfg: LinkConfig
    lanes: LaneMap
    stat: list[StatResult]
    time: list[TimeResult] = field(default_factory=list)
    skew_ps: np.ndarray = field(default_factory=lambda: np.zeros(0))
    targets: dict = field(default_factory=dict)
    spec_rows: dict = field(default_factory=dict)

    @property
    def worst(self) -> StatResult:
        """The lane with the smallest eye margin relative to its target (eye
        height or width, whichever is tighter). Not the largest BER: at a
        1e-27 target every lane's BER at its own eye centre is far below
        float resolution, and ranking by it picked lane 0 every time."""
        return min(self.stat, key=lambda r: (r.margin, r.lane))

    @property
    def log10_ber_worst(self) -> float:
        return max(r.log10_ber for r in self.stat)

    @property
    def ber_worst(self) -> float:
        return float(10.0 ** self.log10_ber_worst)

    @property
    def eye_height_min_v(self) -> float:
        return min(r.eye_height_v for r in self.stat)

    @property
    def eye_width_min_ui(self) -> float:
        return min(r.eye_width_ui for r in self.stat)

    @property
    def passes(self) -> bool:
        return self.lanes.link_up and all(r.passes for r in self.stat)

    def consistency_ratios(self) -> list[float]:
        """Time BER / statistical BER per lane run through both (invariant #3)."""
        by_lane = {r.lane: r for r in self.stat}
        out = []
        for t in self.time:
            if t.ber <= 0.0:
                out.append(0.0)
                continue
            try:
                out.append(float(10.0 ** (math.log10(t.ber) - by_lane[t.lane].log10_ber)))
            except OverflowError:
                out.append(float("inf"))
        return out

    def summary(self) -> str:
        lm = self.lanes
        lines = [f"link: {lm.active_width}/{lm.requested_width} lanes active (repair {lm.mode}"
                 f"{', failed ' + str(list(lm.failed)) if lm.failed else ''}"
                 f"{', UNREPAIRED ' + str(list(lm.unrepaired)) if lm.unrepaired else ''}) -> "
                 f"{'PASS' if self.passes else 'FAIL'}"]
        for r in self.stat:
            lines.append("  " + r.summary())
        for t in self.time:
            lines.append("  time " + t.summary())
        return "\n".join(lines)


def aggressors_of(cfg: LinkConfig, lm: LaneMap, phys: int, skews_ps: np.ndarray) -> tuple:
    """``(neighbour distance, relative skew [UI], aggressor physical lane)`` for
    every *active* physical lane within two places of ``phys``. Failed lanes
    and unused spares are silent. The relative skew is the aggressor's static
    skew minus the victim's: its symbols arrive that much later."""
    if cfg.channel.xtalk == "none":
        return ()
    active = {p for p in lm.logical_to_physical if p not in lm.unrepaired}
    out = []
    for q in sorted(active):
        d = abs(q - phys)
        if 1 <= d <= 2:
            out.append((d, float((skews_ps[q] - skews_ps[phys]) * 1e-12 / cfg.ui), q))
    return tuple(out)


def run_link(cfg: LinkConfig, resp: LinkResponse | None = None) -> LinkResult:
    resp = resp if resp is not None else link_response(cfg)
    clock = ForwardedClock(cfg)
    lm = lane_map(cfg)
    skews = physical_skews_ps(cfg)
    active = [(lane, phys) for lane, phys in enumerate(lm.logical_to_physical) if phys not in lm.unrepaired]
    aggr = {phys: aggressors_of(cfg, lm, phys, skews) for _, phys in active}
    stat = []
    for lane, phys in active:
        engine = StatisticalEngine(cfg, resp, clock, tuple((d, sk) for d, sk, _ in aggr[phys]))
        stat.append(engine.run(lane, residual_skew_ui(cfg, skews[phys], clock.alpha > 0.0)))
    time: list[TimeResult] = []
    if cfg.sim.engine in ("time", "both"):
        n_active = len(stat)
        jit = clock.synthesize(cfg.sim.n_symbols, np.random.default_rng([cfg.sim.seed, 0xC10C]), n_active)
        for i, (r, (_, phys)) in enumerate(zip(stat, active)):
            time.append(run_time(cfg, resp, r.lane, r.phase_ui - r.skew_residual_ui, r.skew_residual_ui,
                                 jit[i], clock, aggr[phys]))
    rows = {k: survey(k, cfg.package.kind) for k in ("reach_mm", "module_width_lanes", "bump_pitch_um")}
    return LinkResult(cfg, lm, stat, time, skews, resolved_targets(cfg), rows)


__all__ = ["LaneMap", "lane_map", "physical_skews_ps", "residual_skew_ui", "aggressors_of", "LinkResult", "run_link"]
