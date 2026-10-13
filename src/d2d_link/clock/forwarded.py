"""The forwarded clock: how much of the transmit PLL's jitter the receiver sees.

This is the core mechanism of the library (invariant #2) and the one place
the clock path is modelled. One PLL on the transmit die makes both the clock
the data is launched on and the clock that is forwarded alongside it, so its
phase noise is *common* to the two. What reaches the sampler is the
difference between the data's timing and the forwarded clock's, after the
receiver's optional local PLL, its clock tree and a per-lane phase tracker::

    t_data[k]  = c[k] + n_d[k] + w_d[k]                                   (per lane)
    t_in[k]    = rho c[k] + sqrt(1 - rho^2) c'[k] + n_k[k] + w_k[k]      (one per module)
    t_pll      = h_pll * t_in + (1 - h_pll) * l                           (local PLL locked to t_in)
    t_rx[k]    = (h_tree * t_pll)[k - tau] + n_t[k]                       (tree: delay + first-order lowpass)
    delta[k]   = t_data[k] - t_rx[k]
    theta[k]   = theta[k-1] + alpha (delta[k - d] - theta[k-1-d])         (tracker: bandwidth f_track, latency d)
    eps[k]     = delta[k] - Q(theta[k])                                   (Q: phase-interpolator step)

``c`` is the PLL's timing jitter in seconds (profile or white), ``c'`` an
independent realisation of the same spectrum (``rho`` < 1 says a share of
the two paths' PLL noise is not common -- separate PLLs would be rho = 0),
``n_d``, ``n_k``, ``n_t`` the independent white jitters of the data path,
the clock path and the receive tree, ``w_d``, ``w_k`` the paths' slow wander
(first-order shaped), ``l`` the receiver's local PLL noise (profile or
white). The local PLL is a type-II second-order loop of natural frequency
``local_pll_fn_hz`` (its -3 dB bandwidth is 2.48x that at zeta = 1,
:meth:`ForwardedClock.local_pll_bw_3db_hz`): below it the forwarded phase
passes and the local noise is suppressed, above it the reverse -- the
classic clock-recovery trade-off, with the forwarded clock carrying the
*same* noise as the data. With rho = 1, an ideal tree, no local PLL and no
path noise the difference is identically zero: there is no shortcut that
could make the forwarded clock "an independent clock" with the same RMS,
and a local PLL is never free-running.

The tracker is the behavioural stand-in for a per-lane phase interpolator
loop: first-order on the difference, zero-latency by default so that with
``track_bw_hz`` -> infinity it removes everything; ``track_delay_ui`` is
the loop latency a real one has, in the feedback path too (the loop
corrects on the error it measured d UI ago), so a fast loop with latency
peaks and then goes unstable -- the constructor rejects an unstable pair
rather than synthesising a divergent tracker -- and ``pi_step_ui``
quantises its output. Everything but the quantiser is linear, so the
statistical engine gets the residual in closed form
(:meth:`ForwardedClock.budget`) from the same transfer functions the
synthesiser applies, on the same FFT grid.

A profile's spurs are deterministic sinusoidal phase terms, not noise: a
Tx PLL spur rides on data and forwarded clock alike and leaks through the
same ``|E (1 - rho G)|`` as the continuous common noise; a local PLL spur
leaks through ``|E H_tree (1 - H_pll)|``. The closed form carries them as
amplitudes (``JitterBudget.spur_s`` is their RMS, ``spur_amplitudes_s``
the list the statistical engine turns into arcsine-distributed sampling
offsets); the synthesiser adds the sinusoids with a phase continuous across
blocks.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.signal import lfilter

from ..config.schema import LinkConfig
from ..vendor.pllsim.colored import synth_from_psd
from .profile import ClockProfile

TWOPI = 2.0 * np.pi


PACKAGE_DIR = Path(__file__).resolve().parents[1]      # src/d2d_link -- the bundled data lives in data/ below it


def resolve_data_file(path: str, repo_root: Path | None = None) -> Path:
    """A data path as a config writes it (``data/clock_profiles/x.yaml``)
    made absolute: an absolute path as it is; otherwise the bundled copy
    inside the installed package (``d2d_link/data/...``, package data since
    the performance round, so a ``pip install`` works away from the
    checkout), then the checkout root (``repo_root``, default the one this
    file sits in), then the working directory."""
    p = Path(path)
    if p.is_absolute():
        return p
    root = repo_root or PACKAGE_DIR.parents[1]
    for cand in (PACKAGE_DIR / p, root / p, Path.cwd() / p):
        if cand.exists():
            return cand
    return p


@dataclass(frozen=True)
class JitterBudget:
    """The closed-form residual on one lane, in seconds RMS, by origin."""

    common_leak_s: float      # Tx PLL noise the tree, the local PLL and rho < 1 let through
    local_pll_s: float        # the local PLL's own noise above its loop bandwidth
    data_path_s: float        # n_d after the tracker
    data_wander_s: float      # w_d after the tracker
    clock_path_s: float       # n_k through local PLL, tree and tracker
    clock_wander_s: float     # w_k through the same
    tree_s: float             # n_t after the tracker
    f_lo_hz: float            # lowest offset in the band (1 / (block UI))
    f_hi_hz: float            # the edge-rate Nyquist
    spur_s: float = 0.0       # the profiles' spurs after the same leaks (RMS of sinusoids: sum A^2/2)

    @property
    def gaussian_s(self) -> float:
        """The Gaussian part of the residual (everything but the spurs)."""
        return math.sqrt(self.common_leak_s ** 2 + self.local_pll_s ** 2 + self.data_path_s ** 2
                         + self.data_wander_s ** 2 + self.clock_path_s ** 2 + self.clock_wander_s ** 2
                         + self.tree_s ** 2)

    @property
    def total_s(self) -> float:
        return math.sqrt(self.gaussian_s ** 2 + self.spur_s ** 2)


class ForwardedClock:
    """Everything about the clock path of one ``LinkConfig``."""

    def __init__(self, cfg: LinkConfig):
        self.cfg = cfg
        ck = cfg.clocking
        self.ui = cfg.ui
        self.fs = 1.0 / self.ui                     # edge rate: one data edge per UI
        self.profile: ClockProfile | None = None
        if ck.pll_profile is not None:
            prof = ClockProfile.load(resolve_data_file(ck.pll_profile), f0_hz=ck.pll_f0_hz)
            self.profile = prof.shifted(ck.pll_shift_db)
        self.local_profile: ClockProfile | None = None
        if ck.local_pll_profile is not None:
            prof = ClockProfile.load(resolve_data_file(ck.local_pll_profile), f0_hz=ck.local_pll_f0_hz)
            self.local_profile = prof.shifted(ck.local_pll_shift_db)
        self.rho = float(ck.correlation)
        self.alpha = self.tracker_alpha(ck.track_bw_hz, self.ui)
        self.delay = int(ck.track_delay_ui)
        self.tau = ck.tree_delay_ps * 1e-12
        margin = self.tracker_stability_margin(self.alpha, self.delay)
        if margin <= 0.0:
            raise ValueError(f"clocking: the tracker loop (track_bw_hz {ck.track_bw_hz!r}, alpha {self.alpha:.3g}, "
                             f"track_delay_ui {self.delay}) is unstable: with the latency in its feedback path a "
                             f"loop this fast diverges; lower track_bw_hz or track_delay_ui")
        self.block_step_ratio: float = float("nan")   # set by synthesize(): boundary step / inner step RMS

    # ------------------------------------------------------------- pieces
    @staticmethod
    def tracker_alpha(track_bw_hz: float | None, ui: float) -> float:
        """Loop gain of the first-order tracker updated once per UI; its
        continuous-time bandwidth is ``track_bw_hz``. None -> 0 (no tracker),
        inf -> 1 (tracks everything)."""
        if track_bw_hz is None:
            return 0.0
        if math.isinf(track_bw_hz):
            return 1.0
        return 1.0 - math.exp(-TWOPI * track_bw_hz * ui)

    @staticmethod
    def tracker_stability_margin(alpha: float, delay: int) -> float:
        """``1 - max |pole|`` of the tracker's closed loop
        1 - z^-1 + alpha z^-(d+1): positive is stable. The zero-latency loop
        has its single pole at 1 - alpha; with latency the characteristic
        polynomial z^(d+1) - z^d + alpha pushes poles outward as alpha grows."""
        if alpha <= 0.0:
            return 1.0
        if delay == 0:
            return 1.0 - abs(1.0 - alpha) if alpha < 2.0 else -1.0
        poly = np.zeros(delay + 2)
        poly[0], poly[1], poly[-1] = 1.0, -1.0, alpha
        return float(1.0 - np.max(np.abs(np.roots(poly))))

    def white_psd(self, sigma_s: float) -> float:
        """One-sided PSD [s^2/Hz] of a white per-edge sequence of RMS ``sigma_s``."""
        return 2.0 * sigma_s ** 2 / self.fs

    def _profile_plus_white(self, prof: ClockProfile | None, rj_s: float, f: np.ndarray) -> np.ndarray:
        s = np.zeros_like(f)
        if prof is not None:
            s += prof.s_timing(f)
        return s + self.white_psd(rj_s)

    def pll_timing_psd(self, f: np.ndarray) -> np.ndarray:
        """One-sided PSD [s^2/Hz] of the Tx PLL's timing jitter on ``f``: the
        profile (zero above its f0/2) plus the white part."""
        return self._profile_plus_white(self.profile, self.cfg.clocking.pll_rj_s, np.asarray(f, dtype=np.float64))

    def local_timing_psd(self, f: np.ndarray) -> np.ndarray:
        """The local PLL's own timing jitter [s^2/Hz] (zero without one)."""
        return self._profile_plus_white(self.local_profile, self.cfg.clocking.local_pll_rj_s,
                                        np.asarray(f, dtype=np.float64))

    @property
    def wander_floor_hz(self) -> float:
        """The low edge of the band the wander RMS is defined over: the
        config's ``wander_floor_hz``, else the lowest frequency the synthesis
        block represents (fs / block, the same edge the closed form starts at)."""
        floor = self.cfg.clocking.wander_floor_hz
        return float(floor) if floor is not None else self.fs / self.cfg.sim.jitter_block

    def wander_psd(self, sigma_s: float, f: np.ndarray) -> np.ndarray:
        """First-order shaped noise, S0 / (1 + (f/fc)^2), with S0 set so the
        analytic integral over [wander_floor_hz, fs/2] is ``sigma_s``^2 --
        a physical band, not the simulation grid (the grid sum differs from
        the integral by about half a bin at each end)."""
        f = np.asarray(f, dtype=np.float64)
        if sigma_s <= 0.0:
            return np.zeros_like(f)
        fc = self.cfg.clocking.wander_corner_hz
        band = fc * (math.atan(0.5 * self.fs / fc) - math.atan(self.wander_floor_hz / fc))
        s0 = sigma_s ** 2 / band
        return s0 / (1.0 + (f / fc) ** 2)

    @property
    def tree_wrap_fraction(self) -> float:
        """The share of each synthesis block the tree delay wraps around
        (the block-wise FFT filtering is circular): tau / (block UI). 30 ps
        on 2^18 UI of 31.25 ps is 3.7e-6 -- about one edge per block."""
        return self.tau / (self.cfg.sim.jitter_block * self.ui)

    def h_tree(self, f: np.ndarray) -> np.ndarray:
        """Clock tree: first-order lowpass (or flat) times the delay."""
        f = np.asarray(f, dtype=np.float64)
        h = np.exp(-1j * TWOPI * f * self.tau)
        bw = self.cfg.clocking.tree_bw_hz
        if bw is not None:
            h = h / (1.0 + 1j * f / bw)
        return h

    def h_pll(self, f: np.ndarray) -> np.ndarray:
        """Closed-loop response of the local PLL (type-II, second order): 1 without one."""
        f = np.asarray(f, dtype=np.float64)
        ck = self.cfg.clocking
        if not ck.has_local_pll:
            return np.ones_like(f, dtype=complex)
        wn = TWOPI * ck.local_pll_fn_hz
        z = ck.local_pll_damping
        s = 1j * TWOPI * f
        return (2.0 * z * wn * s + wn ** 2) / (s ** 2 + 2.0 * z * wn * s + wn ** 2)

    def local_pll_bw_3db_hz(self) -> float | None:
        """The local PLL's -3 dB bandwidth: f_n sqrt(1 + 2 zeta^2 + sqrt((1 + 2 zeta^2)^2 + 1))
        for the type-II second-order loop (2.48 f_n at zeta = 1); None without one."""
        ck = self.cfg.clocking
        if not ck.has_local_pll:
            return None
        a = 1.0 + 2.0 * ck.local_pll_damping ** 2
        return ck.local_pll_fn_hz * math.sqrt(a + math.sqrt(a * a + 1.0))

    def g_clock(self, f: np.ndarray) -> np.ndarray:
        """Forwarded-clock input to sampler clock: local PLL then tree."""
        return self.h_tree(f) * self.h_pll(f)

    def e_track(self, f: np.ndarray) -> np.ndarray:
        """1 - L(z) of the tracker at z = exp(j 2 pi f UI): what it leaves.
        L(z) = alpha z^-d / (1 - z^-1 + alpha z^-(d+1)) for the loop
        theta[k] = theta[k-1] + alpha (delta[k-d] - theta[k-1-d]); at d = 0
        this is the first-order alpha / (1 - (1 - alpha) z^-1)."""
        a = self.alpha
        f = np.asarray(f, dtype=np.float64)
        if a == 0.0:
            return np.ones_like(f, dtype=complex)
        z_inv = np.exp(-1j * TWOPI * f * self.ui)
        if self.delay == 0:
            return 1.0 - a / (1.0 - (1.0 - a) * z_inv)
        return 1.0 - a * z_inv ** self.delay / (1.0 - z_inv + a * z_inv ** (self.delay + 1))

    def _tracker_coefficients(self) -> tuple[np.ndarray, np.ndarray]:
        """``(b, a)`` of L(z) for ``scipy.signal.lfilter``."""
        al, d = self.alpha, self.delay
        b = np.concatenate([np.zeros(d), [al]])
        a = np.zeros(d + 2)
        a[0], a[1] = 1.0, -1.0
        a[d + 1] += al
        return b, a[: max(2, d + 2)] if d > 0 else np.array([1.0, -(1.0 - al)])

    # -------------------------------------------------------------- spurs
    def spur_terms(self, f: np.ndarray | None = None) -> list[tuple[float, float]]:
        """``(offset_hz, residual peak amplitude [s])`` of every deterministic
        sinusoidal term at the sampler: each Tx PLL spur through
        ``|E (1 - rho G)|`` (its common part) and, for rho < 1, a second
        sinusoid through ``|E sqrt(1 - rho^2) G|`` (the clock path's own
        copy, independent phase); each local PLL spur through
        ``|E H_tree (1 - H_pll)|``."""
        out: list[tuple[float, float]] = []
        for prof, kind in ((self.profile, "tx"), (self.local_profile, "local")):
            if prof is None or not prof.spurs:
                continue
            for fs_hz, amp_s in prof.spur_amplitudes_s():
                fa = np.array([fs_hz])
                e = abs(complex(self.e_track(fa)[0]))
                if kind == "tx":
                    g = complex(self.g_clock(fa)[0])
                    out.append((fs_hz, amp_s * e * abs(1.0 - self.rho * g)))
                    if self.rho < 1.0:
                        out.append((fs_hz, amp_s * e * math.sqrt(1.0 - self.rho ** 2) * abs(g)))
                else:
                    h = complex((self.h_tree(fa) * (1.0 - self.h_pll(fa)))[0])
                    out.append((fs_hz, amp_s * e * abs(h)))
        return [(f0, a) for f0, a in out if a > 0.0]

    def spur_amplitudes_s(self) -> list[float]:
        """The residual spur amplitudes [s] (peak), for the arcsine kernels."""
        return [a for _, a in self.spur_terms()]

    # -------------------------------------------------------- closed form
    def fft_grid(self, n: int | None = None) -> np.ndarray:
        """The positive-frequency FFT bins of an ``n``-edge block, the grid the
        synthesiser shapes noise on; the closed form integrates on the same
        grid so the two see the same band [fs/n, fs/2]."""
        n = self.cfg.sim.jitter_block if n is None else n
        return np.arange(1, n // 2 + 1) * (self.fs / n)

    def budget(self, n: int | None = None) -> JitterBudget:
        ck = self.cfg.clocking
        f = self.fft_grid(n)
        df = f[1] - f[0] if f.size > 1 else self.fs / 2
        e = np.abs(self.e_track(f)) ** 2
        g = self.g_clock(f)
        g2 = np.abs(g) ** 2
        s_c = self.pll_timing_psd(f)
        leak = np.abs(1.0 - self.rho * g) ** 2 + (1.0 - self.rho ** 2) * g2

        def rms(spectrum) -> float:
            return math.sqrt(float(np.sum(e * spectrum) * df))

        # the white terms factor out of the sum (and are summed that way so
        # the milestone-1 fingerprint stays bit-identical)
        e_sum, eg_sum = float(np.sum(e) * df), float(np.sum(e * g2) * df)
        return JitterBudget(
            common_leak_s=rms(leak * s_c),
            local_pll_s=(rms(np.abs(self.h_tree(f) * (1.0 - self.h_pll(f))) ** 2 * self.local_timing_psd(f))
                         if ck.has_local_pll else 0.0),
            data_path_s=math.sqrt(e_sum * self.white_psd(ck.data_path_rj_s)),
            data_wander_s=rms(self.wander_psd(ck.data_path_wander_s, f)) if ck.data_path_wander_s > 0.0 else 0.0,
            clock_path_s=math.sqrt(eg_sum * self.white_psd(ck.clock_path_rj_s)),
            clock_wander_s=rms(g2 * self.wander_psd(ck.clock_path_wander_s, f)) if ck.clock_path_wander_s > 0.0 else 0.0,
            tree_s=math.sqrt(e_sum * self.white_psd(ck.tree_rj_s)),
            f_lo_hz=float(f[0]), f_hi_hz=float(f[-1]),
            spur_s=math.sqrt(sum(0.5 * a * a for _, a in self.spur_terms())))

    def residual_sigma_s(self) -> float:
        return self.budget().total_s

    def quantisation_sigma_s(self) -> float:
        """What the phase-interpolator step adds (uniform, step^2/12), kept
        apart from the linear budget because it is not Gaussian."""
        return self.cfg.clocking.pi_step_ui * self.ui / math.sqrt(12.0) if self.alpha > 0.0 else 0.0

    def pll_rms_s(self, n: int | None = None) -> float:
        """The Tx PLL's own jitter over the same band (what an independent clock
        of this profile would put on the sampler)."""
        f = self.fft_grid(n)
        df = f[1] - f[0] if f.size > 1 else self.fs / 2
        return math.sqrt(float(np.sum(self.pll_timing_psd(f)) * df))

    def local_pll_rms_s(self, n: int | None = None) -> float:
        f = self.fft_grid(n)
        df = f[1] - f[0] if f.size > 1 else self.fs / 2
        return math.sqrt(float(np.sum(self.local_timing_psd(f)) * df))

    # ---------------------------------------------------------- synthesis
    def synthesize(self, n_edges: int, rng: np.random.Generator,
                   n_lanes: int | None = None) -> np.ndarray:
        """Per-lane residual sampling error [s], shape ``(n_lanes, n_edges)``.

        Synthesised block by block (``sim.jitter_block`` edges): the common
        PLL phase, the clock path, the local PLL and the tree once per block
        for the module, the data path once per lane; the tracker's state runs
        on across blocks. Below fs/block nothing is representable, which is
        where the closed form's band starts too. :meth:`synthesize_blocks`
        yields the same blocks one at a time for runs too long to hold.
        """
        n_lanes = self.cfg.lanes.count if n_lanes is None else n_lanes
        blocks = list(self.synthesize_blocks(n_edges, rng, n_lanes))
        out = np.concatenate(blocks, axis=1) if blocks else np.empty((n_lanes, 0))
        self.block_step_ratio = self._block_step_ratio(out[0], self.cfg.sim.jitter_block) if n_lanes else float("nan")
        return out

    def synthesize_blocks(self, n_edges: int, rng: np.random.Generator, n_lanes: int | None = None):
        """The blocks of :meth:`synthesize`, each ``(n_lanes, <= jitter_block)``,
        as a generator: a 2.5e9-symbol run never holds its jitter at once."""
        ck = self.cfg.clocking
        n_lanes = self.cfg.lanes.count if n_lanes is None else n_lanes
        block = self.cfg.sim.jitter_block
        a = self.alpha
        b_coef, a_coef = self._tracker_coefficients()
        zi = np.zeros((n_lanes, max(len(b_coef), len(a_coef)) - 1)) if a > 0.0 else None
        step_s = ck.pi_step_ui * self.ui
        # the spurs' starting phases: drawn once per run (only when there are
        # any, so a spur-free profile keeps its noise realisation bit for bit)
        tx_spurs = self.profile.spur_amplitudes_s() if self.profile is not None else []
        lo_spurs = self.local_profile.spur_amplitudes_s() if self.local_profile is not None else []
        ph_c = rng.uniform(0.0, TWOPI, len(tx_spurs)) if tx_spurs else None
        ph_c2 = rng.uniform(0.0, TWOPI, len(tx_spurs)) if tx_spurs and self.rho < 1.0 else None
        ph_l = rng.uniform(0.0, TWOPI, len(lo_spurs)) if lo_spurs else None
        pos = 0
        while pos < n_edges:
            n = min(block, n_edges - pos)
            n_fft = block if n < block else n   # a short tail keeps the block's grid
            out = np.empty((n_lanes, n))
            c = self._pll_block(n_fft, rng) + self._sinusoids(tx_spurs, ph_c, pos, n_fft)
            if self.rho == 1.0:
                clk = c
            else:
                clk = (self.rho * c + math.sqrt(1.0 - self.rho ** 2)
                       * (self._pll_block(n_fft, rng) + self._sinusoids(tx_spurs, ph_c2, pos, n_fft)))
            if ck.clock_path_rj_s > 0.0:
                clk = clk + rng.normal(0.0, ck.clock_path_rj_s, n_fft)
            if ck.clock_path_wander_s > 0.0:
                clk = clk + self._wander_block(ck.clock_path_wander_s, n_fft, rng)
            local = self._local_block(n_fft, rng)
            if local is not None and lo_spurs:
                local = local + self._sinusoids(lo_spurs, ph_l, pos, n_fft)
            clk = self._through_clock_path(clk, local)
            if ck.tree_rj_s > 0.0:
                clk = clk + rng.normal(0.0, ck.tree_rj_s, n_fft)
            for lane in range(n_lanes):
                data = c
                if ck.data_path_rj_s > 0.0:
                    data = data + rng.normal(0.0, ck.data_path_rj_s, n_fft)
                if ck.data_path_wander_s > 0.0:
                    data = data + self._wander_block(ck.data_path_wander_s, n_fft, rng)
                delta = (data - clk)[:n]
                if a > 0.0:
                    theta, zi[lane] = lfilter(b_coef, a_coef, delta, zi=zi[lane])
                    if step_s > 0.0:
                        theta = step_s * np.round(theta / step_s)
                    delta = delta - theta
                out[lane] = delta
            yield out
            pos += n

    @staticmethod
    def _block_step_ratio(x: np.ndarray, block: int) -> float:
        """RMS of the residual's step across block boundaries over the RMS of
        its step inside blocks: ~1 means the block-wise synthesis leaves no
        seam; NaN with a single block."""
        if x.size <= block or x.size < 2:
            return float("nan")
        steps = np.diff(x)
        inner = float(np.sqrt(np.mean(steps ** 2)))
        at = np.arange(block, x.size, block) - 1
        seam = float(np.sqrt(np.mean(steps[at] ** 2)))
        return seam / inner if inner > 0.0 else float("nan")

    def _sinusoids(self, spurs: list[tuple[float, float]], phases: np.ndarray | None, k0: int, n: int) -> np.ndarray:
        """Sum of the spurs' sinusoids over edges k0 .. k0 + n - 1 (phase
        continuous across blocks because k is the global edge index)."""
        if not spurs or phases is None:
            return np.zeros(n)
        k = np.arange(k0, k0 + n, dtype=np.float64) * self.ui
        return sum(a * np.cos(TWOPI * f0 * k + ph) for (f0, a), ph in zip(spurs, phases))

    def _pll_block(self, n: int, rng: np.random.Generator) -> np.ndarray:
        """One realisation of the Tx PLL timing jitter [s] over ``n`` edges."""
        if self.profile is None and self.cfg.clocking.pll_rj_s == 0.0:
            return np.zeros(n)
        return synth_from_psd(self.pll_timing_psd, self.fs, n, rng)

    def _local_block(self, n: int, rng: np.random.Generator) -> np.ndarray | None:
        if not self.cfg.clocking.has_local_pll:
            return None
        return synth_from_psd(self.local_timing_psd, self.fs, n, rng)

    def _wander_block(self, sigma_s: float, n: int, rng: np.random.Generator) -> np.ndarray:
        return synth_from_psd(lambda f: self.wander_psd(sigma_s, f), self.fs, n, rng)

    def _through_clock_path(self, x: np.ndarray, local: np.ndarray | None) -> np.ndarray:
        """Local PLL (forwarded phase through H, local noise through 1 - H),
        then the tree's delay and lowpass, in the FFT domain of the block
        (circular, like the synthesis itself)."""
        if local is None and self.tau == 0.0 and self.cfg.clocking.tree_bw_hz is None:
            return x
        n = x.size
        f = np.fft.rfftfreq(n, d=self.ui)
        spec = np.fft.rfft(x)
        if local is not None:
            h = self.h_pll(f)
            spec = spec * h + np.fft.rfft(local) * (1.0 - h)
        return np.fft.irfft(spec * self.h_tree(f), n=n)


def residual_vs_track_bw(cfg: LinkConfig, bandwidths_hz) -> np.ndarray:
    """Closed-form residual sigma [s] for each tracker bandwidth (None/0 = no tracker)."""
    import dataclasses

    out = []
    for bw in bandwidths_hz:
        bw = None if (bw is None or bw == 0.0) else float(bw)
        c = dataclasses.replace(cfg, clocking=dataclasses.replace(cfg.clocking, track_bw_hz=bw))
        out.append(ForwardedClock(c).residual_sigma_s())
    return np.asarray(out)


def residual_vs_local_pll_bw(cfg: LinkConfig, bandwidths_hz) -> list[JitterBudget]:
    """Closed-form budgets for each local-PLL loop bandwidth."""
    import dataclasses

    out = []
    for bw in bandwidths_hz:
        c = dataclasses.replace(cfg, clocking=dataclasses.replace(cfg.clocking, local_pll_fn_hz=float(bw)))
        out.append(ForwardedClock(c).budget())
    return out


__all__ = ["ForwardedClock", "JitterBudget", "residual_vs_track_bw", "residual_vs_local_pll_bw",
           "resolve_data_file"]
