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
    error_bursts: int               # error clusters (errors closer than 64 symbols belong to one)
    eye_time_ui: np.ndarray         # fold grid, -0.5..0.5 UI around the sampling instant
    eye_traces: np.ndarray          # (n_traces, len(eye_time_ui)) waveform, no noise
    samples: np.ndarray             # first sampled values (with noise), for histograms
    sample_bits: np.ndarray
    extras: dict = field(default_factory=dict)

    @property
    def ber_ci95(self) -> tuple[float, float]:
        """Rough 95% interval on the BER from the error count (Poisson). It
        assumes independent errors: when ``error_bursts`` is far below
        ``n_errors`` the errors came in clusters (slow wander carrying the
        sampler across the eye's edge for thousands of symbols at a time) and
        the interval is far too narrow -- the bursts are the sample size."""
        n = max(self.n_errors, 0)
        lo = (n - 1.96 * np.sqrt(n)) / self.n_symbols if n else 0.0
        hi = (n + 1.96 * np.sqrt(n) + 3.0) / self.n_symbols
        return max(lo, 0.0), hi

    def summary(self) -> str:
        return (f"lane {self.lane}: BER {self.ber:.3e} ({self.n_errors} errors in {self.error_bursts} bursts / "
                f"{self.n_symbols} symbols) "
                f"at {self.phase_ui:+.4f} UI | sampled eye {1e3 * self.eye_height_sampled_v:.1f} mV | "
                f"jitter seen {1e15 * self.jitter_rms_s:.1f} fs")


class SymbolStream:
    """One lane's symbols, handed out chunk by chunk with the past symbols the
    postcursors need and the future ones the precursors need, so every symbol
    of a chunk sees its whole ISI and its sampling instant lies inside the
    chunk's waveform."""

    def __init__(self, kind: str, rng: np.random.Generator, n_tail: int, n_pre: int):
        self.pattern = PatternSource(kind, rng)
        self.n_tail, self.n_pre = n_tail, n_pre
        self.hist = np.zeros(n_tail)
        self.pending = np.zeros(0)

    def next(self, m: int) -> tuple[np.ndarray, np.ndarray]:
        """``(seq, b)``: the chunk's ``m`` symbols ``b`` and the padded sequence
        ``seq`` = past ``n_tail`` + ``b`` + future ``n_pre``."""
        need = m + self.n_pre - self.pending.size
        if need > 0:
            self.pending = np.concatenate([self.pending, self.pattern.next(need)])
        b, fut = self.pending[:m], self.pending[m:m + self.n_pre]
        self.pending = self.pending[m:]
        seq = np.concatenate([self.hist, b, fut])
        self.hist = seq[m: m + self.n_tail]
        return seq, b


def shifted_pulse(pulse: np.ndarray, shift_samples: float) -> np.ndarray:
    """``pulse`` delayed by a fractional number of samples (linear
    interpolation, the same reading the statistical engine does)."""
    if shift_samples == 0.0:
        return pulse
    idx = np.arange(pulse.size) - shift_samples
    return np.interp(idx, np.arange(pulse.size), pulse, left=0.0, right=0.0)


def run_time(cfg: LinkConfig, resp: LinkResponse | None = None, lane: int = 0,
             phase_ui: float | None = None, skew_residual_ui: float = 0.0,
             jitter_s: np.ndarray | None = None, clock: ForwardedClock | None = None,
             aggressors: tuple = (), n_eye_traces: int = 400, n_keep_samples: int = 50_000) -> TimeResult:
    """Run one lane. ``phase_ui`` None takes the statistical engine's sampling
    phase (the bathtub minimum); ``jitter_s`` lets a multi-lane run hand in
    the residual synthesised for this lane with the module's common clock;
    ``aggressors`` are ``(neighbour distance, relative skew [UI], seed)`` for
    the neighbour lanes whose crosstalk lands on this one (their own PRBS,
    their symbols arriving ``rel skew`` later)."""
    from .statistical import run_statistical

    resp = resp if resp is not None else link_response(cfg)
    clock = clock if clock is not None else ForwardedClock(cfg)
    if phase_ui is None:
        stat_aggr = tuple((d, sk) for d, sk, _ in aggressors)
        phase_ui = run_statistical(cfg, resp, lane, skew_residual_ui, clock, stat_aggr).phase_ui
    sim = cfg.sim
    osr = sim.osr
    n = sim.n_symbols
    rng = np.random.default_rng([sim.seed, lane, 0x5EED])
    if jitter_s is None:
        jitter_s = clock.synthesize(n, np.random.default_rng([sim.seed, 0xC10C]), 1)[0]
    pulse = resp.pulse.y
    i0 = resp.main_index
    dcd = cfg.clocking.sampling_dcd_ui
    # past symbols whose postcursors reach the chunk, and future ones whose
    # precursors do, each with one more UI of slack; a sampling instant that
    # the phase, the skew, the duty-cycle offset and the jitter carry further
    # than that slack needs more padding on both ends (an eye read from a
    # window extended to +-1 UI sits up to a whole symbol away)
    reach_ui = abs(phase_ui + skew_residual_ui) + 0.5 * dcd + float(np.max(np.abs(jitter_s[:n]))) / cfg.ui
    margin = max(0, int(np.ceil(reach_ui)) - 1)
    n_tail = int(np.ceil(pulse.size / osr)) + 1 + margin
    n_pre = int(np.ceil(i0 / osr)) + 1 + margin
    vref = cfg.rx.vref_offset_v
    sigma = cfg.rx.noise_rms_v
    victim = SymbolStream(sim.pattern, rng, n_tail, n_pre)
    xt = []
    for d, rel_skew_ui, seed in aggressors:
        px = (resp.xtalk_pulses or {}).get(d)
        if px is None:
            continue
        xt.append((SymbolStream(sim.pattern, np.random.default_rng([sim.seed, int(seed), 0xA66]), n_tail, n_pre),
                   shifted_pulse(px.y, rel_skew_ui * osr)))

    n_err = 0
    n_bursts = 0
    last_err = -10 ** 9
    kept_s, kept_b = [], []
    traces = None
    eye_t = (np.arange(osr + 1) - osr // 2) / osr
    pos = 0
    while pos < n:
        m = min(sim.chunk_symbols, n - pos)
        seq, b = victim.next(m)
        x = np.zeros(seq.size * osr)
        x[::osr] = seq
        y = fftconvolve(x, pulse)[: x.size]
        for stream, px in xt:
            seq_a, _ = stream.next(m)
            xa = np.zeros(seq_a.size * osr)
            xa[::osr] = seq_a
            y += fftconvolve(xa, px)[: x.size]
        k = np.arange(m)
        # the sampling instant of symbol k: its main cursor plus phase, DDR
        # duty-cycle offset (odd symbols) and the forwarded clock's residual
        offs = (phase_ui + skew_residual_ui) + dcd * 0.5 * (2 * ((pos + k) & 1) - 1)
        idx = (n_tail + k) * osr + i0 + offs * osr + jitter_s[pos:pos + m] / cfg.dt
        if not (idx.min() >= 0.0 and idx.max() <= y.size - 1):   # np.interp would clamp silently
            raise AssertionError(f"sampling instant outside the chunk's waveform: idx {idx.min():.1f}..{idx.max():.1f} "
                                 f"of {y.size} samples (phase {phase_ui:+.3f} UI)")
        s = np.interp(idx, np.arange(y.size), y) + rng.normal(0.0, sigma, m) if sigma > 0.0 \
            else np.interp(idx, np.arange(y.size), y)
        dec = np.where(s > vref, 1.0, -1.0)
        err_at = np.flatnonzero(dec != b)
        n_err += int(err_at.size)
        if err_at.size:
            pos_err = err_at + pos
            gaps = np.diff(np.concatenate([[last_err], pos_err]))
            n_bursts += int(np.count_nonzero(gaps > 64))
            last_err = int(pos_err[-1])
        if len(kept_s) * sim.chunk_symbols < n_keep_samples:
            kept_s.append(s[: n_keep_samples])
            kept_b.append(b[: n_keep_samples])
        if traces is None:
            n_tr = min(n_eye_traces, m)
            centre = ((n_tail + k[:n_tr]) * osr + i0 + (phase_ui + skew_residual_ui) * osr
                      + jitter_s[pos:pos + n_tr] / cfg.dt)
            grid = centre[:, None] + (eye_t * osr)[None, :]
            traces = np.interp(grid.ravel(), np.arange(y.size), y).reshape(grid.shape)
        pos += m

    s_all = np.concatenate(kept_s)[:n_keep_samples]
    b_all = np.concatenate(kept_b)[:n_keep_samples]
    hi, lo = s_all[b_all > 0], s_all[b_all < 0]
    eye_s = float(hi.min() - lo.max()) if hi.size and lo.size else float("nan")
    return TimeResult(lane=lane, ber=n_err / n, n_errors=n_err, n_symbols=n, phase_ui=phase_ui + skew_residual_ui,
                      eye_height_sampled_v=eye_s, jitter_rms_s=float(np.std(jitter_s[:n])),
                      error_bursts=n_bursts, eye_time_ui=eye_t, eye_traces=traces, samples=s_all, sample_bits=b_all,
                      extras={"main_cursor_v": resp.main_amplitude, "n_aggressors": len(xt),
                              "block_step_ratio": clock.block_step_ratio})


__all__ = ["run_time", "TimeResult", "SymbolStream", "shifted_pulse"]
