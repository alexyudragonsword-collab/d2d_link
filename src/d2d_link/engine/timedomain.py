"""Time-domain engine: the cross-check at measurable BER (invariant #3).

It builds the waveform the pulse response implies for a PRBS, samples it
where the forwarded clock says (the per-symbol residual the clock model
synthesises, plus the sampling phase and the DDR duty-cycle offset), adds
the sampler's Gaussian noise and counts errors. Nothing is approximated
that the statistical engine assumes -- same pulse, same noise, same jitter
spectrum -- so under LTI + Gaussian the two must agree within 2x wherever
this one can count enough errors (1e-6..1e-9 with 10^7..10^9 symbols). It
also folds the waveform into an eye for the plots and reports the sampled
values' measured opening.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.signal import fftconvolve

from ..channel.model import LinkResponse, link_response
from ..clock.forwarded import ForwardedClock
from ..config.schema import LinkConfig
from ..core.prbs import PatternSource


@dataclass
class TimeResult:
    lane: int
    ber: float
    n_errors: int
    n_symbols: int
    phase_ui: float
    eye_height_sampled_v: float     # min(+1 samples) - max(-1 samples), noise included
    jitter_rms_s: float             # RMS of the residual timing the sampler saw
    eye_time_ui: np.ndarray         # fold grid, -0.5..0.5 UI around the sampling instant
    eye_traces: np.ndarray          # (n_traces, len(eye_time_ui)) waveform, no noise
    samples: np.ndarray             # first sampled values (with noise), for histograms
    sample_bits: np.ndarray
    extras: dict = field(default_factory=dict)

    @property
    def ber_ci95(self) -> tuple[float, float]:
        """Rough 95% interval on the BER from the error count (Poisson)."""
        n = max(self.n_errors, 0)
        lo = (n - 1.96 * np.sqrt(n)) / self.n_symbols if n else 0.0
        hi = (n + 1.96 * np.sqrt(n) + 3.0) / self.n_symbols
        return max(lo, 0.0), hi

    def summary(self) -> str:
        return (f"lane {self.lane}: BER {self.ber:.3e} ({self.n_errors} errors / {self.n_symbols} symbols) "
                f"at {self.phase_ui:+.4f} UI | sampled eye {1e3 * self.eye_height_sampled_v:.1f} mV | "
                f"jitter seen {1e15 * self.jitter_rms_s:.1f} fs")


def run_time(cfg: LinkConfig, resp: LinkResponse | None = None, lane: int = 0,
             phase_ui: float | None = None, skew_residual_ui: float = 0.0,
             jitter_s: np.ndarray | None = None, clock: ForwardedClock | None = None,
             n_eye_traces: int = 400, n_keep_samples: int = 50_000) -> TimeResult:
    """Run one lane. ``phase_ui`` None takes the statistical engine's sampling
    phase (the bathtub minimum); ``jitter_s`` lets a multi-lane run hand in
    the residual synthesised for this lane with the module's common clock."""
    from .statistical import run_statistical

    resp = resp if resp is not None else link_response(cfg)
    clock = clock if clock is not None else ForwardedClock(cfg)
    if phase_ui is None:
        phase_ui = run_statistical(cfg, resp, lane, skew_residual_ui, clock).phase_ui
    sim = cfg.sim
    osr = sim.osr
    n = sim.n_symbols
    rng = np.random.default_rng([sim.seed, lane, 0x5EED])
    if jitter_s is None:
        jitter_s = clock.synthesize(n, np.random.default_rng([sim.seed, 0xC10C]), 1)[0]
    pattern = PatternSource(sim.pattern, rng)
    pulse = resp.pulse.y
    i0 = resp.main_index
    n_tail = int(np.ceil(pulse.size / osr)) + 1
    dcd = cfg.clocking.dcd_ui
    vref = cfg.rx.vref_offset_v
    sigma = cfg.rx.noise_rms_v

    n_pre = int(np.ceil(i0 / osr)) + 1          # future symbols whose precursors reach the chunk
    n_err = 0
    hist = np.zeros(n_tail)                      # symbols before the chunk, oldest first
    pending = np.zeros(0)                        # generated symbols not yet consumed
    kept_s, kept_b = [], []
    traces = None
    eye_t = (np.arange(osr + 1) - osr // 2) / osr
    pos = 0
    while pos < n:
        m = min(sim.chunk_symbols, n - pos)
        need = m + n_pre - pending.size
        if need > 0:
            pending = np.concatenate([pending, pattern.next(need)])
        b, fut = pending[:m], pending[m:m + n_pre]
        pending = pending[m:]
        # past symbols for the postcursors, future ones for the precursors, so
        # every symbol of the chunk sees its whole ISI and its sampling instant
        # (main cursor i0 samples in) lies inside the waveform
        seq = np.concatenate([hist, b, fut])
        x = np.zeros(seq.size * osr)
        x[::osr] = seq
        y = fftconvolve(x, pulse)[: x.size]
        k = np.arange(m)
        # the sampling instant of symbol k: its main cursor plus phase, DDR
        # duty-cycle offset (odd symbols) and the forwarded clock's residual
        offs = (phase_ui + skew_residual_ui) + dcd * 0.5 * (2 * ((pos + k) & 1) - 1)
        idx = (n_tail + k) * osr + i0 + offs * osr + jitter_s[pos:pos + m] / cfg.dt
        s = np.interp(idx, np.arange(y.size), y) + rng.normal(0.0, sigma, m) if sigma > 0.0 \
            else np.interp(idx, np.arange(y.size), y)
        dec = np.where(s > vref, 1.0, -1.0)
        n_err += int(np.count_nonzero(dec != b))
        if len(kept_s) * sim.chunk_symbols < n_keep_samples:
            kept_s.append(s[: n_keep_samples])
            kept_b.append(b[: n_keep_samples])
        if traces is None:
            n_tr = min(n_eye_traces, m)
            centre = ((n_tail + k[:n_tr]) * osr + i0 + (phase_ui + skew_residual_ui) * osr
                      + jitter_s[pos:pos + n_tr] / cfg.dt)
            grid = centre[:, None] + (eye_t * osr)[None, :]
            traces = np.interp(grid.ravel(), np.arange(y.size), y).reshape(grid.shape)
        hist = seq[n_tail + m - n_tail: n_tail + m]
        pos += m

    s_all = np.concatenate(kept_s)[:n_keep_samples]
    b_all = np.concatenate(kept_b)[:n_keep_samples]
    hi, lo = s_all[b_all > 0], s_all[b_all < 0]
    eye_s = float(hi.min() - lo.max()) if hi.size and lo.size else float("nan")
    return TimeResult(lane=lane, ber=n_err / n, n_errors=n_err, n_symbols=n, phase_ui=phase_ui + skew_residual_ui,
                      eye_height_sampled_v=eye_s, jitter_rms_s=float(np.std(jitter_s[:n])),
                      eye_time_ui=eye_t, eye_traces=traces, samples=s_all, sample_bits=b_all,
                      extras={"main_cursor_v": resp.main_amplitude})


__all__ = ["run_time", "TimeResult"]
