"""The forwarded clock: how much of the transmit PLL's jitter the receiver sees.

This is the core mechanism of the library (invariant #2) and the one place
the clock path is modelled. One PLL on the transmit die makes both the clock
the data is launched on and the clock that is forwarded alongside it, so its
phase noise is *common* to the two. What reaches the sampler is the
difference between the data's timing and the forwarded clock's, after the
receiver's clock tree and a per-lane phase tracker::

    t_data[k]  = c[k]              + n_d[k]                      (per lane)
    t_clk[k]   = rho c[k] + sqrt(1 - rho^2) c'[k] + n_k[k]      (one per module)
    t_rx[k]    = (h_tree * t_clk)[k - tau]  + n_t[k]             (tree: delay + first-order lowpass)
    delta[k]   = t_data[k] - t_rx[k]
    theta[k]   = theta[k-1] + alpha (delta[k] - theta[k-1])      (tracker, bandwidth f_track)
    eps[k]     = delta[k] - theta[k]                             (what lands on the sampler)

``c`` is the PLL's timing jitter in seconds (profile or white), ``c'`` an
independent realisation of the same spectrum (``rho`` < 1 says a share of
the two paths' PLL noise is not common -- separate PLLs would be rho = 0),
``n_d``, ``n_k``, ``n_t`` the independent white jitters of the data path,
the clock path and the receive tree. With rho = 1, an ideal tree and no
path noise the difference is identically zero -- there is no shortcut that
could make the forwarded clock "an independent clock" with the same RMS.

The tracker is the behavioural stand-in for a per-lane phase interpolator
loop: a first-order, zero-latency lowpass on the difference, so with
``track_bw_hz`` -> infinity it removes everything and with no tracker the
sampler sees the whole difference. Its latency is deliberately not modelled
(ROADMAP). Everything is linear, so the statistical engine gets the residual
in closed form (:meth:`ForwardedClock.budget`) from the same transfer
functions the synthesiser applies, on the same FFT grid: the two agree to
the sampling scatter of one realisation, which a test pins.
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


def resolve_data_file(path: str, repo_root: Path | None = None) -> Path:
    """A repo-relative data path (``data/clock_profiles/x.yaml``) made absolute
    against the checkout; an absolute path is returned as it is."""
    p = Path(path)
    if p.is_absolute():
        return p
    root = repo_root or Path(__file__).resolve().parents[3]
    cand = root / p
    return cand if cand.exists() else p


@dataclass(frozen=True)
class JitterBudget:
    """The closed-form residual on one lane, in seconds RMS, by origin."""

    common_leak_s: float      # PLL noise the tree's delay / bandwidth and rho < 1 let through
    data_path_s: float        # n_d after the tracker
    clock_path_s: float       # n_k through tree and tracker
    tree_s: float             # n_t after the tracker
    f_lo_hz: float            # lowest offset in the band (1 / (block UI))
    f_hi_hz: float            # the edge-rate Nyquist

    @property
    def total_s(self) -> float:
        return math.sqrt(self.common_leak_s ** 2 + self.data_path_s ** 2
                         + self.clock_path_s ** 2 + self.tree_s ** 2)


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
        self.rho = float(ck.correlation)
        self.alpha = self.tracker_alpha(ck.track_bw_hz, self.ui)
        self.tau = ck.tree_delay_ps * 1e-12

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

    def pll_timing_psd(self, f: np.ndarray) -> np.ndarray:
        """One-sided PSD [s^2/Hz] of the PLL's timing jitter on ``f``: the
        profile (zero above its f0/2) plus the white part, which as a per-edge
        sequence at rate fs has PSD 2 sigma^2 / fs over [0, fs/2]."""
        f = np.asarray(f, dtype=np.float64)
        s = np.zeros_like(f)
        if self.profile is not None:
            s += self.profile.s_timing(f)
        s += self.white_psd(self.cfg.clocking.pll_rj_s)
        return s

    def white_psd(self, sigma_s: float) -> float:
        return 2.0 * sigma_s ** 2 / self.fs

    def h_tree(self, f: np.ndarray) -> np.ndarray:
        """Clock tree: first-order lowpass (or flat) times the delay."""
        f = np.asarray(f, dtype=np.float64)
        h = np.exp(-1j * TWOPI * f * self.tau)
        bw = self.cfg.clocking.tree_bw_hz
        if bw is not None:
            h = h / (1.0 + 1j * f / bw)
        return h

    def e_track(self, f: np.ndarray) -> np.ndarray:
        """1 - L(z) of the tracker at z = exp(j 2 pi f UI): what it leaves."""
        a = self.alpha
        if a == 0.0:
            return np.ones_like(np.asarray(f, dtype=np.float64), dtype=complex)
        z_inv = np.exp(-1j * TWOPI * np.asarray(f, dtype=np.float64) * self.ui)
        return 1.0 - a / (1.0 - (1.0 - a) * z_inv)

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
        h = self.h_tree(f)
        s_c = self.pll_timing_psd(f)
        leak = np.abs(1.0 - self.rho * h) ** 2 + (1.0 - self.rho ** 2) * np.abs(h) ** 2
        var_common = float(np.sum(e * leak * s_c) * df)
        var_data = float(np.sum(e) * df) * self.white_psd(ck.data_path_rj_s)
        var_clock = float(np.sum(e * np.abs(h) ** 2) * df) * self.white_psd(ck.clock_path_rj_s)
        var_tree = float(np.sum(e) * df) * self.white_psd(ck.tree_rj_s)
        return JitterBudget(math.sqrt(var_common), math.sqrt(var_data), math.sqrt(var_clock),
                            math.sqrt(var_tree), float(f[0]), float(f[-1]))

    def residual_sigma_s(self) -> float:
        return self.budget().total_s

    def pll_rms_s(self, n: int | None = None) -> float:
        """The PLL's own jitter over the same band (what an independent clock
        of this profile would put on the sampler)."""
        f = self.fft_grid(n)
        df = f[1] - f[0] if f.size > 1 else self.fs / 2
        return math.sqrt(float(np.sum(self.pll_timing_psd(f)) * df))

    # ---------------------------------------------------------- synthesis
    def synthesize(self, n_edges: int, rng: np.random.Generator,
                   n_lanes: int | None = None) -> np.ndarray:
        """Per-lane residual sampling error [s], shape ``(n_lanes, n_edges)``.

        Synthesised block by block (``sim.jitter_block`` edges): the common
        PLL phase and the clock path once per block for the module, the data
        path once per lane; the tracker's state runs on across blocks. Below
        fs/block nothing is representable, which is where the closed form's
        band starts too.
        """
        ck = self.cfg.clocking
        n_lanes = self.cfg.lanes.count if n_lanes is None else n_lanes
        block = self.cfg.sim.jitter_block
        out = np.empty((n_lanes, n_edges))
        a = self.alpha
        zi = np.zeros((n_lanes, 1)) if a > 0.0 else None
        pos = 0
        while pos < n_edges:
            n = min(block, n_edges - pos)
            n_fft = block if n < block else n   # a short tail keeps the block's grid
            c = self._pll_block(n_fft, rng)
            clk = c if self.rho == 1.0 else self.rho * c + math.sqrt(1.0 - self.rho ** 2) * self._pll_block(n_fft, rng)
            if ck.clock_path_rj_s > 0.0:
                clk = clk + rng.normal(0.0, ck.clock_path_rj_s, n_fft)
            clk = self._through_tree(clk)
            if ck.tree_rj_s > 0.0:
                clk = clk + rng.normal(0.0, ck.tree_rj_s, n_fft)
            for lane in range(n_lanes):
                data = c if ck.data_path_rj_s == 0.0 else c + rng.normal(0.0, ck.data_path_rj_s, n_fft)
                delta = (data - clk)[:n]
                if a > 0.0:
                    theta, zi[lane] = lfilter([a], [1.0, -(1.0 - a)], delta, zi=zi[lane])
                    delta = delta - theta
                out[lane, pos:pos + n] = delta
            pos += n
        return out

    def _pll_block(self, n: int, rng: np.random.Generator) -> np.ndarray:
        """One realisation of the PLL timing jitter [s] over ``n`` edges."""
        if self.profile is None and self.cfg.clocking.pll_rj_s == 0.0:
            return np.zeros(n)
        return synth_from_psd(self.pll_timing_psd, self.fs, n, rng)

    def _through_tree(self, x: np.ndarray) -> np.ndarray:
        """Delay and first-order lowpass applied in the FFT domain of the block
        (circular, like the synthesis itself)."""
        if self.tau == 0.0 and self.cfg.clocking.tree_bw_hz is None:
            return x
        n = x.size
        f = np.fft.rfftfreq(n, d=self.ui)
        return np.fft.irfft(np.fft.rfft(x) * self.h_tree(f), n=n)


def residual_vs_track_bw(cfg: LinkConfig, bandwidths_hz) -> np.ndarray:
    """Closed-form residual sigma [s] for each tracker bandwidth (None/0 = no tracker)."""
    import dataclasses

    out = []
    for bw in bandwidths_hz:
        bw = None if (bw is None or bw == 0.0) else float(bw)
        c = dataclasses.replace(cfg, clocking=dataclasses.replace(cfg.clocking, track_bw_hz=bw))
        out.append(ForwardedClock(c).residual_sigma_s())
    return np.asarray(out)


__all__ = ["ForwardedClock", "JitterBudget", "residual_vs_track_bw", "resolve_data_file"]
