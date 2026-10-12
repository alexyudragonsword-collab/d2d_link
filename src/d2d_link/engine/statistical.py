"""Statistical BER engine -- the primary engine (invariant #3).

A raw BER of 1e-27 is one error in 10^27 bits; no time-domain run reaches
it. Under LTI + stationary Gaussian noise the sampled-value distribution is
exact without one: for a sent +1 the sample is

    main cursor + sum_k c_k b_k + noise,      b_k in {-1, +1} equiprobable

so the error probability at threshold v is an average of Gaussian tails over
the ISI patterns. The ``sim.stat_enumerate_cursors`` largest cursors are
enumerated exactly (2^M patterns); the remaining, small ones become Gaussian
variance. Tails are evaluated analytically (``erfc``), never through an FFT
convolution, which cannot see below ~1e-16 of its peak -- the reason this
engine can report 1e-27 and a binned StatEye cannot.

Sampling jitter enters on the phase axis: the residual the forwarded-clock
model leaves (``clock/forwarded.py``, closed form) is a Gaussian on the
sampling instant, so the BER at a phase is the Gauss-Hermite average of the
jitter-free BER over neighbouring phases, cursors re-read from the pulse
there. A DDR duty-cycle error is two sampling phases averaged. Both are
exactly what the time engine does with its per-symbol timing offsets.

Outputs per lane: the bathtub, the sampling phase (the bathtub minimum
unless the config fixes one -- the per-lane tracker centres the eye), the
BER there, and the eye height and width at the target BER by bisection on
the same tail sums.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field

import numpy as np
from scipy.special import erfc

from ..channel.model import LinkResponse, link_response
from ..clock.forwarded import ForwardedClock, JitterBudget
from ..config.schema import LinkConfig
from ..spec import survey

SQRT2 = math.sqrt(2.0)


def qfunc(x):
    return 0.5 * erfc(np.asarray(x, dtype=np.float64) / SQRT2)


def resolved_targets(cfg: LinkConfig) -> dict:
    """The BER / eye targets: the config's own values where set, else the
    survey table's for this package, each with its source."""
    t = cfg.target
    out = {}
    for name, key in (("ber", "raw_ber_target"), ("eye_height_mv", "rx_eye_height_mv"),
                      ("eye_width_ui", "rx_eye_width_ui")):
        v = getattr(t, name)
        if v is not None:
            out[name] = (float(v), "config")
        else:
            s = survey(key, cfg.package.kind)
            out[name] = (float(s.value), s.source)
    return out


@dataclass
class IsiModel:
    """The ISI of one phase: enumerated patterns and the Gaussian remainder."""

    main: float
    isi_values: np.ndarray      # 2^M enumerated ISI sums [V]
    sigma_rest: float           # RMS of the cursors not enumerated [V]
    n_enumerated: int
    n_cursors: int


def isi_model(cursors: np.ndarray, i_main: int, n_enum: int, extra: np.ndarray | None = None) -> IsiModel:
    """``extra`` are further interferers with independent +-1 symbols (the
    neighbour lanes' crosstalk cursors): they join the ISI cursors in the
    enumeration or the variance on the same footing."""
    c = np.delete(cursors, i_main)
    if extra is not None and extra.size:
        c = np.concatenate([c, extra])
    order = np.argsort(-np.abs(c))
    top = c[order[:n_enum]]
    rest = c[order[n_enum:]]
    if top.size:
        signs = 2.0 * ((np.arange(2 ** top.size)[:, None] >> np.arange(top.size)) & 1) - 1.0
        values = signs @ top
    else:
        values = np.zeros(1)
    return IsiModel(float(cursors[i_main]), values, float(np.sqrt(np.sum(rest ** 2))), top.size, c.size)


def tail_probability(m: IsiModel, sigma_noise: float, v: float) -> float:
    """P(sample < v | +1 sent) with Gaussian noise ``sigma_noise`` at the sampler."""
    sigma = math.sqrt(sigma_noise ** 2 + m.sigma_rest ** 2)
    if sigma <= 0.0:
        return float(np.mean(m.main + m.isi_values < v))
    return float(np.mean(qfunc((m.main + m.isi_values - v) / sigma)))


def jitter_quadrature(sigma_ui: float, phase_points: int, n_sigmas: float,
                      uniform_width_ui: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """Offsets [UI] and weights for E[f(phase + delta)], delta ~ N(0, sigma)
    convolved with a uniform of width ``uniform_width_ui`` (the phase
    interpolator's quantisation step; 0 = none).

    A trapezoid on a uniform grid rather than Gauss-Hermite: the integrand is
    the bathtub, a near step at the eye's edge, and a few Hermite nodes
    straddle it badly (2x on a jitter-dominated link). The step is a
    sub-multiple of the bathtub's grid, at most sigma/4, so the phases land
    on one fine grid and the ISI models are shared; the range is
    ``n_sigmas`` on each side, which must reach the target BER's tail
    (1e-27 is 10.8 sigma)."""
    if sigma_ui <= 0.0 and uniform_width_ui <= 0.0:
        return np.zeros(1), np.ones(1)
    base = 1.0 / phase_points
    finest = min([v for v in (sigma_ui / 4.0, uniform_width_ui / 8.0) if v > 0.0])
    q = max(1, int(math.ceil(base / finest)))
    h = base / q
    j = int(math.ceil((n_sigmas * sigma_ui + 0.5 * uniform_width_ui) / h))
    x = np.arange(-j, j + 1) * h
    w = np.exp(-0.5 * (x / sigma_ui) ** 2) if sigma_ui > 0.0 else (x == 0.0).astype(float)
    if uniform_width_ui > 0.0:
        m = int(round(0.5 * uniform_width_ui / h))
        box = np.ones(2 * m + 1)
        w = np.convolve(w, box, mode="same")
    return x, w / w.sum()


@dataclass
class StatResult:
    lane: int
    ber: float
    phase_ui: float
    bathtub_phase_ui: np.ndarray
    bathtub_ber: np.ndarray
    eye_height_v: float
    eye_width_ui: float
    target_ber: float
    sigma_noise_v: float
    sigma_jitter_s: float
    jitter: JitterBudget
    main_cursor_v: float
    cursors_v: np.ndarray
    i_main: int
    skew_residual_ui: float = 0.0
    targets: dict = field(default_factory=dict)
    extras: dict = field(default_factory=dict)

    @property
    def eye_height_margin_mv(self) -> float:
        return 1e3 * self.eye_height_v - self.targets["eye_height_mv"][0]

    @property
    def eye_width_margin_ui(self) -> float:
        return self.eye_width_ui - self.targets["eye_width_ui"][0]

    @property
    def passes(self) -> bool:
        return (self.ber <= self.target_ber and self.eye_height_margin_mv >= 0.0
                and self.eye_width_margin_ui >= 0.0)

    def summary(self) -> str:
        eh = self.targets["eye_height_mv"]
        ew = self.targets["eye_width_ui"]
        return (f"lane {self.lane}: BER {self.ber:.3e} at {self.phase_ui:+.4f} UI | "
                f"eye {1e3 * self.eye_height_v:.1f} mV / {self.eye_width_ui:.3f} UI at {self.target_ber:.0e} "
                f"(targets {eh[0]:g} mV source: {eh[1]}, {ew[0]:g} UI source: {ew[1]}) | "
                f"jitter {1e15 * self.sigma_jitter_s:.1f} fs, noise {1e3 * self.sigma_noise_v:.2f} mV")


class StatisticalEngine:
    """The engine bound to one config and one pulse response."""

    def __init__(self, cfg: LinkConfig, resp: LinkResponse | None = None,
                 clock: ForwardedClock | None = None, aggressors: tuple = ()):
        """``aggressors`` are ``(neighbour distance, relative skew [UI])`` pairs
        for the active lanes whose crosstalk lands on this one."""
        self.cfg = cfg
        self.resp = resp if resp is not None else link_response(cfg)
        self.clock = clock if clock is not None else ForwardedClock(cfg)
        self.aggressors = tuple(aggressors)
        self.budget = self.clock.budget()
        self.sigma_j_ui = self.budget.total_s / cfg.ui
        self.quant_ui = cfg.clocking.pi_step_ui if self.clock.alpha > 0.0 else 0.0
        self.nodes, self.weights = jitter_quadrature(self.sigma_j_ui, cfg.sim.stat_phase_points,
                                                     cfg.sim.stat_jitter_sigmas, self.quant_ui)
        self.n_enum = cfg.sim.stat_enumerate_cursors
        self.sigma_n = cfg.rx.noise_rms_v
        self.vref = cfg.rx.vref_offset_v
        self._models: dict[float, IsiModel] = {}

    # ----------------------------------------------------------- pieces
    def model_at(self, phase_ui: float) -> IsiModel:
        key = round(phase_ui * 1e9)
        m = self._models.get(key)
        if m is None:
            c, i_main = self.resp.cursors(phase_ui)
            extra = [self.resp.xtalk_cursors(d, phase_ui, skew) for d, skew in self.aggressors]
            extra = np.concatenate(extra) if extra else None
            m = self._models[key] = isi_model(c, i_main, self.n_enum, extra)
        return m

    def sampling_phases(self, phase_ui: float) -> list[tuple[float, float]]:
        """``(phase, weight)`` pairs the sampler really lands on: the jitter
        quadrature's offsets, split again by the DDR duty-cycle error."""
        dcd = self.cfg.clocking.dcd_ui
        offs = (-0.5 * dcd, 0.5 * dcd) if dcd > 0.0 else (0.0,)
        out = []
        for x, w in zip(self.nodes, self.weights):
            for d in offs:
                out.append((phase_ui + x + d, w / len(offs)))
        return out

    def error_probability(self, phase_ui: float, v_threshold: float | None = None) -> float:
        """BER at ``phase_ui`` (relative to the pulse peak), both symbols averaged."""
        v = self.vref if v_threshold is None else v_threshold
        p = 0.0
        for ph, w in self.sampling_phases(phase_ui):
            m = self.model_at(ph)
            # +1 sent and read below v; -1 sent and read above v (mirror: +1 below -v)
            p += w * 0.5 * (tail_probability(m, self.sigma_n, v) + tail_probability(m, self.sigma_n, -v))
        return p

    def half_eye(self, phase_ui: float, target: float, side: int) -> float:
        """Half eye height on one side of the threshold at the target BER:
        the h with P(+1 sample < vref + h) = target (side +1) or
        P(-1 sample > vref - h) = target (side -1), by bisection."""
        def tail(h):
            v = side * self.vref + h   # the -1 side mirrors onto the +1 distribution
            return sum(w * tail_probability(self.model_at(ph), self.sigma_n, v)
                       for ph, w in self.sampling_phases(phase_ui))
        lo, hi = 0.0, abs(self.model_at(phase_ui).main) * 1.5 + 10 * self.sigma_n
        if tail(lo) > target:
            return 0.0
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            if tail(mid) > target:
                hi = mid
            else:
                lo = mid
        return lo

    def bathtub(self) -> tuple[np.ndarray, np.ndarray]:
        n = self.cfg.sim.stat_phase_points
        phases = np.linspace(-0.5, 0.5, n + 1)
        ber = np.array([self.error_probability(p) for p in phases])
        return phases, ber

    @staticmethod
    def eye_width(phases: np.ndarray, ber: np.ndarray, target: float, i_center: int) -> float:
        left, right = StatisticalEngine.eye_edges(phases, ber, target, i_center)
        return right - left

    @staticmethod
    def eye_edges(phases: np.ndarray, ber: np.ndarray, target: float, i_center: int) -> tuple[float, float]:
        """Edges of the contiguous region around ``i_center`` with BER <= target,
        interpolated in log BER; ``(p, p)`` when the eye is closed there."""
        if ber[i_center] > target:
            return float(phases[i_center]), float(phases[i_center])
        lt = np.log10(np.maximum(target, 1e-300))
        lb = np.log10(np.maximum(ber, 1e-300))
        i = i_center
        while i > 0 and ber[i - 1] <= target:
            i -= 1
        left = phases[i] if i == 0 else np.interp(lt, [lb[i], lb[i - 1]], [phases[i], phases[i - 1]])
        j = i_center
        while j < ber.size - 1 and ber[j + 1] <= target:
            j += 1
        right = phases[j] if j == ber.size - 1 else np.interp(lt, [lb[j], lb[j + 1]], [phases[j], phases[j + 1]])
        return float(left), float(right)

    # ------------------------------------------------------------ run
    def run(self, lane: int = 0, skew_residual_ui: float = 0.0) -> StatResult:
        cfg = self.cfg
        targets = resolved_targets(cfg)
        target_ber = targets["ber"][0]
        phases, ber = self.bathtub()
        i_min = int(np.argmin(ber))
        left, right = self.eye_edges(phases, ber, target_ber, i_min)
        ew = right - left
        if cfg.rx.sampling_phase_ui is not None:
            center = cfg.rx.sampling_phase_ui
        elif ew > 0.0:
            # the eye-centring tracker: the middle of the opening at the target
            # BER, not the bathtub's argmin (which is the first index wherever
            # the BER underflows to exactly zero)
            center = 0.5 * (left + right)
        else:
            center = float(phases[i_min])
        phase = center + skew_residual_ui
        ber_at = self.error_probability(phase)
        eh = self.half_eye(phase, target_ber, +1) + self.half_eye(phase, target_ber, -1)
        m = self.model_at(phase)
        c, i_main = self.resp.cursors(phase)
        return StatResult(
            lane=lane, ber=ber_at, phase_ui=phase, bathtub_phase_ui=phases, bathtub_ber=ber,
            eye_height_v=eh, eye_width_ui=ew, target_ber=target_ber,
            sigma_noise_v=self.sigma_n, sigma_jitter_s=self.budget.total_s, jitter=self.budget,
            main_cursor_v=m.main, cursors_v=c, i_main=i_main, skew_residual_ui=skew_residual_ui,
            targets=targets,
            extras={"sigma_isi_rest_v": m.sigma_rest, "n_enumerated": m.n_enumerated,
                    "n_cursors": m.n_cursors, "n_aggressors": len(self.aggressors),
                    "xtalk_rms_v": float(math.sqrt(sum(float(np.sum(self.resp.xtalk_cursors(d, phase, sk) ** 2))
                                                      for d, sk in self.aggressors))),
                    "quantisation_ui": self.quant_ui, "ber_min": float(ber[i_min]),
                    "phase_min_ui": float(phases[i_min]),
                    "insertion_loss_nyquist_db": self.resp.channel.insertion_loss_db(cfg.f_nyquist)})


def run_statistical(cfg: LinkConfig, resp: LinkResponse | None = None, lane: int = 0,
                    skew_residual_ui: float = 0.0, clock: ForwardedClock | None = None,
                    aggressors: tuple = ()) -> StatResult:
    return StatisticalEngine(cfg, resp, clock, aggressors).run(lane, skew_residual_ui)


def with_phase(cfg: LinkConfig, phase_ui: float) -> LinkConfig:
    return dataclasses.replace(cfg, rx=dataclasses.replace(cfg.rx, sampling_phase_ui=phase_ui))


__all__ = ["run_statistical", "StatisticalEngine", "StatResult", "IsiModel", "isi_model",
           "tail_probability", "qfunc", "resolved_targets", "jitter_quadrature"]
