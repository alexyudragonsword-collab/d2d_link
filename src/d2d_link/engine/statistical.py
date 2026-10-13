"""Statistical BER engine -- the primary engine (invariant #3).

A raw BER of 1e-27 is one error in 10^27 bits; no time-domain run reaches
it. Under LTI + stationary Gaussian noise the sampled-value distribution is
exact without one: for a sent +1 the sample is

    main cursor + sum_k c_k b_k + noise,      b_k in {-1, +1} equiprobable

so the error probability at threshold v is the ISI distribution averaged
against Gaussian tails. The ISI distribution is built *exactly* on a
voltage grid of bin ``sim.stat_isi_bin_v`` by shift-and-add: every cursor
(the lane's own and the neighbour lanes' crosstalk cursors alike) splits the
distribution into two half-weight copies shifted by +-c_k, a fractional
shift shared linearly between the two nearest bins. No cursor is dropped,
none is folded into a Gaussian variance: the earlier "enumerate the largest
M, Gaussian for the rest" never converged in M once hundreds of crosstalk
cursors competed for 12 places (eye width 0.613 / 0.671 / 0.683 UI at
M = 8 / 12 / 16). The only approximation is the bin, and halving it is the
convergence check (``tests/test_statistical.py``).

Tails are evaluated analytically in the log domain (``log_ndtr`` summed
with ``logsumexp``), never through an FFT convolution, which cannot see
below ~1e-16 of its peak -- the reason this engine reports 1e-27 and a
binned StatEye cannot -- and never through ``erfc`` in linear float, which
underflows to exactly 0.0 below 1e-308 and made every lane of a 1e-27 link
look equally perfect. ``log10_ber`` is the primary number; ``ber`` is its
antilog.

Sampling jitter enters on the phase axis: the residual the forwarded-clock
model leaves (``clock/forwarded.py``, closed form) is a Gaussian on the
sampling instant, so the BER at a phase is the quadrature average of the
jitter-free BER over neighbouring phases, cursors re-read from the pulse
there. A DDR duty-cycle error is two sampling phases averaged. Both are
exactly what the time engine does with its per-symbol timing offsets.

Outputs per lane: the bathtub, the sampling phase (the middle of the
opening at the target BER unless the config fixes one -- the per-lane
tracker centres the eye), the BER there, and the eye height and width at
the target BER by bisection on the same tail sums. The eye width is capped
at 1 UI (a symbol's eye cannot be wider than its symbol; a wider reading is
the band edge's Gibbs ripple on a short, unfiltered line) and the cap is
flagged in ``extras["eye_width_clipped"]``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.special import erfc, log_ndtr

from ..channel.model import LinkResponse, link_response
from ..clock.forwarded import ForwardedClock, JitterBudget
from ..config.schema import LinkConfig
from ..spec import survey

SQRT2 = math.sqrt(2.0)
LN10 = math.log(10.0)


def qfunc(x):
    return 0.5 * erfc(np.asarray(x, dtype=np.float64) / SQRT2)


def _logsumexp(a: np.ndarray, axis: int | None = None) -> np.ndarray | float:
    """log(sum(exp(a))) without scipy's per-call overhead (this engine calls
    it tens of thousands of times on short arrays); all-(-inf) rows give -inf."""
    a = np.asarray(a, dtype=np.float64)
    m = np.max(a, axis=axis, keepdims=True)
    m = np.where(np.isfinite(m), m, 0.0)
    with np.errstate(divide="ignore"):
        out = np.log(np.sum(np.exp(a - m), axis=axis, keepdims=True)) + m
    return out.reshape(-1) if axis is not None else float(out.reshape(()))


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
    """The ISI of one phase: its exact distribution on a voltage grid."""

    main: float
    grid_v: np.ndarray          # bin centres [V], symmetric about 0, step ``bin_v``
    pmf: np.ndarray             # probability of each bin (sums to 1)
    bin_v: float
    n_cursors: int
    sigma_isi_v: float          # exact RMS of the ISI, sqrt(sum c_k^2)

    def __post_init__(self):
        keep = self.pmf > 0.0
        self.values_v = self.grid_v[keep]
        self.log_pmf = np.log(self.pmf[keep])


def _shift_add(p: np.ndarray, s: float) -> np.ndarray:
    """``p`` (odd length, centred) split into half-weight copies shifted by
    ``+-s`` bins; a fractional shift is shared linearly between the two
    nearest bins (mean exact, variance over by at most f(1-f) bin^2)."""
    a = abs(s)
    j = int(math.floor(a))
    f = a - j
    m = j + 1
    n = p.size
    q = np.zeros(n + 2 * m)
    q[m + j: m + j + n] += 0.5 * (1.0 - f) * p
    q[m - j: m - j + n] += 0.5 * (1.0 - f) * p
    if f > 0.0:
        q[m + j + 1: m + j + 1 + n] += 0.5 * f * p
        q[m - j - 1: m - j - 1 + n] += 0.5 * f * p
    return q


def isi_model(cursors: np.ndarray, i_main: int, bin_v: float, extra: np.ndarray | None = None) -> IsiModel:
    """``extra`` are further interferers with independent +-1 symbols (the
    neighbour lanes' crosstalk cursors): they join the ISI cursors in the
    distribution on the same footing. Cursors are added largest first so the
    distribution's support grows as late as possible."""
    c = np.delete(np.asarray(cursors, dtype=np.float64), i_main)
    if extra is not None and np.asarray(extra).size:
        c = np.concatenate([c, np.asarray(extra, dtype=np.float64)])
    c = c[np.argsort(-np.abs(c), kind="stable")]
    p = np.ones(1)
    for ck in c:
        if ck != 0.0:
            p = _shift_add(p, ck / bin_v)
    half = (p.size - 1) // 2
    grid = (np.arange(p.size) - half) * bin_v
    return IsiModel(float(cursors[i_main]), grid, p, float(bin_v), int(c.size), float(math.sqrt(np.sum(c ** 2))))


def log10_tail(m: IsiModel, sigma_noise: float, v) -> np.ndarray | float:
    """log10 P(sample < v | +1 sent) with Gaussian noise ``sigma_noise`` at
    the sampler; ``v`` may be an array of thresholds."""
    v = np.asarray(v, dtype=np.float64)
    scalar = v.ndim == 0
    v = np.atleast_1d(v)
    x = v[:, None] - m.main - m.values_v[None, :]
    with np.errstate(divide="ignore"):
        if sigma_noise <= 0.0:
            terms = np.where(x > 0.0, m.log_pmf[None, :], -np.inf)
        else:
            terms = m.log_pmf[None, :] + log_ndtr(x / sigma_noise)
        out = _logsumexp(terms, axis=1) / LN10
    return float(out[0]) if scalar else out


def tail_probability(m: IsiModel, sigma_noise: float, v: float) -> float:
    """P(sample < v | +1 sent) in linear scale (0.0 below 1e-308; use
    :func:`log10_tail` where that matters)."""
    return float(10.0 ** log10_tail(m, sigma_noise, v))


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
    log10_ber: float
    phase_ui: float
    bathtub_phase_ui: np.ndarray
    bathtub_log10_ber: np.ndarray
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
    def ber(self) -> float:
        """The antilog of ``log10_ber``: 0.0 below 1e-308, so compare
        ``log10_ber`` where lanes are ranked."""
        return float(10.0 ** self.log10_ber)

    @property
    def bathtub_ber(self) -> np.ndarray:
        with np.errstate(over="ignore", under="ignore"):
            return 10.0 ** self.bathtub_log10_ber

    @property
    def eye_height_margin_mv(self) -> float:
        return 1e3 * self.eye_height_v - self.targets["eye_height_mv"][0]

    @property
    def eye_width_margin_ui(self) -> float:
        return self.eye_width_ui - self.targets["eye_width_ui"][0]

    @property
    def margin(self) -> float:
        """The smaller of the two eye margins relative to its target (the
        number a module's worst lane is picked by): negative fails."""
        return min(self.eye_height_margin_mv / self.targets["eye_height_mv"][0],
                   self.eye_width_margin_ui / self.targets["eye_width_ui"][0])

    @property
    def passes(self) -> bool:
        return (self.log10_ber <= math.log10(self.target_ber) and self.eye_height_margin_mv >= 0.0
                and self.eye_width_margin_ui >= 0.0)

    def summary(self) -> str:
        eh = self.targets["eye_height_mv"]
        ew = self.targets["eye_width_ui"]
        clipped = " (clipped)" if self.extras.get("eye_width_clipped") else ""
        return (f"lane {self.lane}: BER 10^{self.log10_ber:.1f} at {self.phase_ui:+.4f} UI | "
                f"eye {1e3 * self.eye_height_v:.1f} mV / {self.eye_width_ui:.3f} UI{clipped} at {self.target_ber:.0e} "
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
        self.bin_v = cfg.sim.stat_isi_bin_v
        self.sigma_n = cfg.rx.noise_rms_v
        self.vref = cfg.rx.vref_offset_v
        self._models: dict[float, IsiModel] = {}
        self._tails: dict[tuple[float, float, float], np.ndarray] = {}

    # ----------------------------------------------------------- pieces
    def model_at(self, phase_ui: float) -> IsiModel:
        key = round(phase_ui * 1e9)
        m = self._models.get(key)
        if m is None:
            c, i_main = self.resp.cursors(phase_ui)
            extra = [self.resp.xtalk_cursors(d, phase_ui, skew) for d, skew in self.aggressors]
            extra = np.concatenate(extra) if extra else None
            m = self._models[key] = isi_model(c, i_main, self.bin_v, extra)
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

    @staticmethod
    def _log10_mix(log10_terms: list[float], weights: list[float]) -> float:
        """log10 of sum_i w_i 10^t_i."""
        t = np.asarray(log10_terms, dtype=np.float64) * LN10
        with np.errstate(divide="ignore"):
            return float(_logsumexp(t + np.log(np.asarray(weights, dtype=np.float64))) / LN10)

    def log10_error_probability(self, phase_ui: float, v_threshold: float | None = None) -> float:
        """log10 BER at ``phase_ui`` (relative to the pulse's reference
        sample), both symbols averaged."""
        v = self.vref if v_threshold is None else v_threshold
        terms, weights = [], []
        for ph, w in self.sampling_phases(phase_ui):
            # +1 sent and read below v; -1 sent and read above v (mirror: +1
            # below -v). The jitter offsets of neighbouring bathtub phases
            # land on the same fine grid, so the pair is cached per model --
            # and per noise, which the examples' bisections change in place.
            key = (round(ph * 1e9), v, self.sigma_n)
            lt = self._tails.get(key)
            if lt is None:
                lt = self._tails[key] = log10_tail(self.model_at(ph), self.sigma_n, np.array([v, -v]))
            terms.extend(lt.tolist())
            weights.extend([0.5 * w, 0.5 * w])
        return self._log10_mix(terms, weights)

    def error_probability(self, phase_ui: float, v_threshold: float | None = None) -> float:
        """BER at ``phase_ui`` in linear scale (see :meth:`log10_error_probability`)."""
        return float(10.0 ** self.log10_error_probability(phase_ui, v_threshold))

    def half_eye(self, phase_ui: float, target: float, side: int) -> float:
        """Half eye height on one side of the threshold at the target BER:
        the h with P(+1 sample < vref + h) = target (side +1) or
        P(-1 sample > vref - h) = target (side -1), by bisection."""
        phases = self.sampling_phases(phase_ui)
        weights = [w for _, w in phases]
        lt = math.log10(target)

        def log_tail(h):
            v = side * self.vref + h   # the -1 side mirrors onto the +1 distribution
            return self._log10_mix([log10_tail(self.model_at(ph), self.sigma_n, v) for ph, _ in phases], weights)

        lo, hi = 0.0, abs(self.model_at(phase_ui).main) * 1.5 + 10 * self.sigma_n
        if log_tail(lo) > lt:
            return 0.0
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            if log_tail(mid) > lt:
                hi = mid
            else:
                lo = mid
        return lo

    def bathtub(self, lo: float = -0.5, hi: float = 0.5) -> tuple[np.ndarray, np.ndarray]:
        """``(phases, log10 BER)`` on ``sim.stat_phase_points`` phases per UI."""
        n = int(round(self.cfg.sim.stat_phase_points * (hi - lo)))
        phases = np.linspace(lo, hi, n + 1)
        ber = np.array([self.log10_error_probability(p) for p in phases])
        return phases, ber

    def bathtub_around_the_eye(self, target: float) -> tuple[np.ndarray, np.ndarray]:
        """The bathtub over [-0.5, 0.5] UI from the reference sample, extended
        by half a UI on a side where the opening at ``target`` reaches the
        window's edge. At most one extension per side."""
        lo, hi = -0.5, 0.5
        phases, ber = self.bathtub(lo, hi)
        for _ in range(2):
            region = self.eye_region(phases, ber, target)
            if region is None:
                break
            left, right = region
            grow_lo = left <= phases[0] + 1e-12
            grow_hi = right >= phases[-1] - 1e-12
            if not (grow_lo or grow_hi):
                break
            if grow_lo:
                lo -= 0.5
            if grow_hi:
                hi += 0.5
            phases, ber = self.bathtub(lo, hi)
        return phases, ber

    @staticmethod
    def eye_region(phases: np.ndarray, log10_ber: np.ndarray, target: float) -> tuple[float, float] | None:
        """The widest contiguous opening with BER <= target on the bathtub
        (given as log10), edges interpolated in log BER; ties go to the
        opening centred nearest zero; None when the eye is closed at the
        target. The BER is *not* periodic in the phase -- it is the error
        rate of deciding *this* symbol, 0.5 one UI away where the neighbour's
        cursor is sampled -- so there is one opening, around this symbol's
        main cursor."""
        n = log10_ber.size
        lt = math.log10(target)
        lb = np.asarray(log10_ber, dtype=np.float64)
        ok = lb <= lt
        if not ok.any():
            return None
        lb = np.maximum(lb, -300.0)
        best = None
        i = 0
        while i < n:
            if not ok[i]:
                i += 1
                continue
            j = i
            while j + 1 < n and ok[j + 1]:
                j += 1
            left = phases[i] if i == 0 else np.interp(lt, [lb[i], lb[i - 1]], [phases[i], phases[i - 1]])
            right = phases[j] if j == n - 1 else np.interp(lt, [lb[j], lb[j + 1]], [phases[j], phases[j + 1]])
            key = (-round(float(right - left), 12), abs(0.5 * float(left + right)))
            if best is None or key < best[0]:
                best = (key, float(left), float(right))
            i = j + 1
        return (best[1], best[2]) if best else None

    # ------------------------------------------------------------ run
    def run(self, lane: int = 0, skew_residual_ui: float = 0.0) -> StatResult:
        cfg = self.cfg
        targets = resolved_targets(cfg)
        target_ber = targets["ber"][0]
        phases, ber = self.bathtub_around_the_eye(target_ber)
        i_min = int(np.argmin(ber))
        region = self.eye_region(phases, ber, target_ber)
        if region is not None:
            left, right = region
            ew_raw = right - left
        else:
            left = right = float(phases[i_min])
            ew_raw = 0.0
        clipped = ew_raw > 1.0
        ew = 1.0 if clipped else ew_raw
        if ew > 0.0:
            # the eye-centring tracker: the middle of the opening at the target BER
            center = 0.5 * (left + right)
        else:
            center = float(phases[i_min])
        if cfg.rx.sampling_phase_ui is not None:
            center = cfg.rx.sampling_phase_ui
        phase = center + skew_residual_ui
        if ew > 0.0 and phase != center:
            # a lane sampled off the eye's centre (a deskew residual, a fixed
            # phase) has only the symmetric opening around its own sampling
            # instant to spend: the same bathtub, read from where it samples
            ew = max(0.0, min(2.0 * (right - phase), 2.0 * (phase - left), ew))
        log_ber = self.log10_error_probability(phase)
        eh = self.half_eye(phase, target_ber, +1) + self.half_eye(phase, target_ber, -1)
        m = self.model_at(phase)
        c, i_main = self.resp.cursors(phase)
        return StatResult(
            lane=lane, log10_ber=log_ber, phase_ui=phase, bathtub_phase_ui=phases, bathtub_log10_ber=ber,
            eye_height_v=eh, eye_width_ui=ew, target_ber=target_ber,
            sigma_noise_v=self.sigma_n, sigma_jitter_s=self.budget.total_s, jitter=self.budget,
            main_cursor_v=m.main, cursors_v=c, i_main=i_main, skew_residual_ui=skew_residual_ui,
            targets=targets,
            extras={"sigma_isi_v": m.sigma_isi_v, "isi_bins": int(m.pmf.size), "isi_bin_v": m.bin_v,
                    "n_cursors": m.n_cursors, "n_aggressors": len(self.aggressors),
                    "xtalk_rms_v": float(math.sqrt(sum(float(np.sum(self.resp.xtalk_cursors(d, phase, sk) ** 2))
                                                      for d, sk in self.aggressors))),
                    "quantisation_ui": self.quant_ui, "log10_ber_min": float(ber[i_min]),
                    "phase_min_ui": float(phases[i_min]),
                    "eye_width_raw_ui": float(ew_raw), "eye_width_clipped": bool(clipped),
                    "insertion_loss_nyquist_db": self.resp.channel.insertion_loss_db(cfg.f_nyquist)})


def run_statistical(cfg: LinkConfig, resp: LinkResponse | None = None, lane: int = 0,
                    skew_residual_ui: float = 0.0, clock: ForwardedClock | None = None,
                    aggressors: tuple = ()) -> StatResult:
    return StatisticalEngine(cfg, resp, clock, aggressors).run(lane, skew_residual_ui)


__all__ = ["run_statistical", "StatisticalEngine", "StatResult", "IsiModel", "isi_model",
           "tail_probability", "log10_tail", "qfunc", "resolved_targets", "jitter_quadrature"]
