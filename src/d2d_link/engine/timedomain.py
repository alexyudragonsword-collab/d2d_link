"""Time-domain engine: the cross-check at measurable BER (invariant #3).

It builds the waveform the pulse response implies for a PRBS, samples it
where the forwarded clock says (the per-symbol residual the clock model
synthesises, plus the sampling phase and the DDR duty-cycle offset), adds
the sampler's Gaussian noise and counts errors. Nothing is approximated
that the statistical engine assumes -- same pulse, same noise, same jitter
spectrum -- so under LTI + Gaussian the two must agree within 2x wherever
this one can count enough errors (1e-6 in the suite, 1e-8 in the weekly
run, 10^7..10^9 symbols). It also folds the waveform into an eye for the
plots and reports the sampled values' measured opening.

``sim.time_mode: samples`` computes only the sampled values: each symbol's
sample is the sum of the pulse's cursors read at that symbol's own sampling
instant (the same linear interpolation the waveform path's ``np.interp``
applies) times the symbols around it. It is the waveform path's arithmetic
without the 31 unsampled points per UI -- the same errors to floating-point
rounding, ~30x faster, no eye traces -- and the jitter is streamed block by
block, so 2.5e9 symbols (a 1e-8 point with 25 errors) fit in memory.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.signal import fftconvolve

from ..channel.model import LinkResponse, link_response, noise_shaping_gain
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


class _JitterFeed:
    """Hands the per-symbol residual out ``m`` edges at a time, from an array
    or from :meth:`ForwardedClock.synthesize_blocks`; keeps the running RMS
    and the seam statistic for the streamed case."""

    def __init__(self, cfg: LinkConfig, clock: ForwardedClock, jitter_s: np.ndarray | None, n: int):
        self.n = n
        self.array = jitter_s
        self._sum = 0.0
        self._sumsq = 0.0
        self._count = 0
        self._steps_sq = 0.0
        self._steps_n = 0
        self._seam_sq = 0.0
        self._seam_n = 0
        self._last = None
        if jitter_s is None:
            self.blocks = clock.synthesize_blocks(n, np.random.default_rng([cfg.sim.seed, 0xC10C]), 1)
            self.pending = np.zeros(0)
            # the sampling reach is bounded by the budget: 12 sigma of the Gaussian part plus the spurs' peaks
            b = clock.budget()
            self.max_abs_s = 12.0 * b.gaussian_s + sum(clock.spur_amplitudes_s())
        else:
            self.max_abs_s = float(np.max(np.abs(jitter_s[:n]))) if n else 0.0
        self.pos = 0

    def next(self, m: int) -> np.ndarray:
        if self.array is not None:
            out = self.array[self.pos:self.pos + m]
            self.pos += m
            return out
        while self.pending.size < m:
            blk = next(self.blocks)[0]
            if self._last is not None and blk.size:
                self._seam_sq += float((blk[0] - self._last) ** 2)
                self._seam_n += 1
            if blk.size:
                self._last = float(blk[-1])
            d = np.diff(blk)
            self._steps_sq += float(np.dot(d, d))
            self._steps_n += d.size
            self._sum += float(np.sum(blk))
            self._sumsq += float(np.dot(blk, blk))
            self._count += blk.size
            self.pending = np.concatenate([self.pending, blk])
        out, self.pending = self.pending[:m], self.pending[m:]
        self.pos += m
        return out

    def rms_s(self) -> float:
        if self.array is not None:
            return float(np.std(self.array[:self.n]))
        if self._count == 0:
            return 0.0
        mean = self._sum / self._count
        return math.sqrt(max(self._sumsq / self._count - mean * mean, 0.0))

    def block_step_ratio(self, clock: ForwardedClock) -> float:
        if self.array is not None:
            return clock.block_step_ratio
        if self._seam_n == 0 or self._steps_n == 0:
            return float("nan")
        inner = math.sqrt((self._steps_sq + self._seam_sq) / (self._steps_n + self._seam_n))
        return math.sqrt(self._seam_sq / self._seam_n) / inner if inner > 0.0 else float("nan")


def shifted_pulse(pulse: np.ndarray, shift_samples: float) -> np.ndarray:
    """``pulse`` delayed by a fractional number of samples (linear
    interpolation, the same reading the statistical engine does)."""
    if shift_samples == 0.0:
        return pulse
    idx = np.arange(pulse.size) - shift_samples
    return np.interp(idx, np.arange(pulse.size), pulse, left=0.0, right=0.0)


class _NoiseFeed:
    """Gaussian noise at the sampling instants. Referred at the sampler it is
    one white sample per symbol. Referred at the input (``rx.noise_at:
    input``) the waveform path really filters it: white noise on the
    waveform grid (per-sample sigma = sigma_in sqrt(osr), the PSD
    sigma_in^2 / f_N of the config's convention) through the front end x
    CTLE impulse, continuous across chunks (the raw tail is kept as filter
    state), read at each symbol's own fractional sampling instant -- an
    independent check of ``noise_shaping_gain``'s integral that also carries
    the noise's correlation between symbols. The samples mode has no
    waveform and takes the marginal sigma (the integral)."""

    def __init__(self, cfg: LinkConfig, resp: LinkResponse, rng: np.random.Generator, filtered: bool):
        self.rng = rng
        self.sigma_in = cfg.rx.noise_rms_v
        self.osr = cfg.sim.osr
        self.filtered = filtered and cfg.rx.noise_at == "input" and resp.noise_impulse is not None
        self.sigma_marginal = self.sigma_in * noise_shaping_gain(cfg)
        if self.filtered:
            self.h = resp.noise_impulse.y
            self.sigma_grid = self.sigma_in * math.sqrt(self.osr)
            self.tail = rng.normal(0.0, self.sigma_grid, self.h.size - 1) if self.h.size > 1 else np.zeros(0)

    def at(self, idx: np.ndarray) -> np.ndarray:
        """Noise at the sampling indices ``idx`` (waveform samples, monotonic,
        ~osr apart) of one chunk."""
        m = idx.size
        if self.sigma_in <= 0.0:
            return np.zeros(m)
        if not self.filtered:
            return self.rng.normal(0.0, self.sigma_marginal, m)
        # the noise process is independent of the signal's timing: the chunk's
        # instants are mapped onto a fresh stretch of the process, keeping
        # their fractional positions and spacing
        rel = idx - (math.floor(idx[0]) - self.osr)
        n_wave = int(math.ceil(rel.max())) + 2
        raw = np.concatenate([self.tail, self.rng.normal(0.0, self.sigma_grid, n_wave)])
        y = fftconvolve(raw, self.h)[self.tail.size: self.tail.size + n_wave]
        if self.tail.size:
            self.tail = raw[-self.tail.size:]
        return np.interp(rel, np.arange(n_wave), y)


def run_time(cfg: LinkConfig, resp: LinkResponse | None = None, lane: int = 0,
             phase_ui: float | None = None, skew_residual_ui: float = 0.0,
             jitter_s: np.ndarray | None = None, clock: ForwardedClock | None = None,
             aggressors: tuple = (), n_eye_traces: int = 400, n_keep_samples: int = 50_000,
             mode: str | None = None) -> TimeResult:
    """Run one lane. ``phase_ui`` None takes the statistical engine's sampling
    phase (the bathtub minimum); ``jitter_s`` lets a multi-lane run hand in
    the residual synthesised for this lane with the module's common clock
    (None synthesises it here, streamed for long runs); ``aggressors`` are
    ``(neighbour distance, relative skew [UI], seed)`` for the neighbour
    lanes whose crosstalk lands on this one (their own PRBS, their symbols
    arriving ``rel skew`` later); ``mode`` overrides ``sim.time_mode``."""
    from .statistical import run_statistical

    resp = resp if resp is not None else link_response(cfg)
    clock = clock if clock is not None else ForwardedClock(cfg)
    if phase_ui is None:
        stat_aggr = tuple((d, sk) for d, sk, _ in aggressors)
        phase_ui = run_statistical(cfg, resp, lane, skew_residual_ui, clock, stat_aggr).phase_ui
    sim = cfg.sim
    mode = sim.time_mode if mode is None else mode
    osr = sim.osr
    n = sim.n_symbols
    rng = np.random.default_rng([sim.seed, lane, 0x5EED])
    if jitter_s is None and n <= (1 << 24):
        jitter_s = clock.synthesize(n, np.random.default_rng([sim.seed, 0xC10C]), 1)[0]
    feed = _JitterFeed(cfg, clock, jitter_s, n)
    pulse = resp.pulse.y
    i0 = resp.main_index
    dcd = cfg.clocking.sampling_dcd_ui
    # past symbols whose postcursors reach the chunk, and future ones whose
    # precursors do, each with one more UI of slack; a sampling instant that
    # the phase, the skew, the duty-cycle offset and the jitter carry further
    # than that slack needs more padding on both ends (an eye read from a
    # window extended to +-1 UI sits up to a whole symbol away)
    reach_ui = abs(phase_ui + skew_residual_ui) + 0.5 * dcd + feed.max_abs_s / cfg.ui
    margin = max(0, int(np.ceil(reach_ui)) - 1)
    n_tail = int(np.ceil(pulse.size / osr)) + 1 + margin
    n_pre = int(np.ceil(i0 / osr)) + 1 + margin
    vref = cfg.rx.vref_offset_v
    victim = SymbolStream(sim.pattern, rng, n_tail, n_pre)
    # the same generator, drawn once per chunk after the symbols as before:
    # the sampler-referred stream is the phase 1-6 one, sample for sample
    noise = _NoiseFeed(cfg, resp, rng, filtered=(mode != "samples"))
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
    if mode == "samples":
        # cursor k multiplies the symbol k places back; the pulse is padded
        # so every cursor index of every sampling instant is inside it. Only
        # the cursors whose UI of the pulse (any of the aggressors' pulses
        # too) rises above sim.time_cursor_floor of the main cursor are kept:
        # the one approximation of this mode (1e-6 x 200 mV = 0.2 uV against
        # millivolts of noise), and the reason it is fast -- 130 UI of pulse
        # hold ~20 cursors that matter
        pad = (n_tail + n_pre + 2) * osr
        pulse_pad = np.concatenate([np.zeros(pad), pulse, np.zeros(pad)])
        xt_pad = [(stream, np.concatenate([np.zeros(pad), px, np.zeros(pad)])) for stream, px in xt]
        ks_all = np.arange(-n_pre, n_tail + 1)
        floor = sim.time_cursor_floor * resp.main_amplitude
        keep = np.zeros(ks_all.size, dtype=bool)
        for pp in [pulse_pad, *(px for _, px in xt_pad)]:
            for i, kk in enumerate(ks_all):
                lo = pad + i0 + kk * osr - osr
                keep[i] |= bool(np.max(np.abs(pp[max(lo, 0): lo + 2 * osr + 1])) >= floor)
        ks = ks_all[keep]
        chunk = max(1024, min(sim.chunk_symbols, 8_000_000 // max(ks.size, 1)))
        traces = np.empty((0, osr + 1))
    else:
        chunk = sim.chunk_symbols
    pos = 0
    while pos < n:
        m = min(chunk, n - pos)
        seq, b = victim.next(m)
        k = np.arange(m)
        # the sampling instant of symbol k: its main cursor plus phase, DDR
        # duty-cycle offset (odd symbols) and the forwarded clock's residual
        offs = (phase_ui + skew_residual_ui) + dcd * 0.5 * (2 * ((pos + k) & 1) - 1)
        jit = feed.next(m)
        if mode == "samples":
            pos_main = i0 + offs * osr + jit / cfg.dt            # fractional pulse index of the main cursor
            base = np.floor(pos_main).astype(np.int64)
            frac = pos_main - base
            idx = (base + pad)[:, None] + ks[None, :] * osr
            # symbol n - k for the kept cursors k: seq index (n_tail + n) - k
            sym_idx = (n_tail + k)[:, None] - ks[None, :]
            cur = (1.0 - frac)[:, None] * pulse_pad[idx] + frac[:, None] * pulse_pad[idx + 1]
            s = np.einsum("nk,nk->n", cur, seq[sym_idx])
            for stream, px_pad in xt_pad:
                seq_a, _ = stream.next(m)
                cur_a = (1.0 - frac)[:, None] * px_pad[idx] + frac[:, None] * px_pad[idx + 1]
                s = s + np.einsum("nk,nk->n", cur_a, seq_a[sym_idx])
            s = s + noise.at(pos_main)
        else:
            x = np.zeros(seq.size * osr)
            x[::osr] = seq
            y = fftconvolve(x, pulse)[: x.size]
            for stream, px in xt:
                seq_a, _ = stream.next(m)
                xa = np.zeros(seq_a.size * osr)
                xa[::osr] = seq_a
                y += fftconvolve(xa, px)[: x.size]
            idx = (n_tail + k) * osr + i0 + offs * osr + jit / cfg.dt
            if not (idx.min() >= 0.0 and idx.max() <= y.size - 1):   # np.interp would clamp silently
                raise AssertionError(f"sampling instant outside the chunk's waveform: idx {idx.min():.1f}.."
                                     f"{idx.max():.1f} of {y.size} samples (phase {phase_ui:+.3f} UI)")
            s = np.interp(idx, np.arange(y.size), y) + noise.at(idx)
        dec = np.where(s > vref, 1.0, -1.0)
        err_at = np.flatnonzero(dec != b)
        n_err += int(err_at.size)
        if err_at.size:
            pos_err = err_at + pos
            gaps = np.diff(np.concatenate([[last_err], pos_err]))
            n_bursts += int(np.count_nonzero(gaps > 64))
            last_err = int(pos_err[-1])
        if len(kept_s) * chunk < n_keep_samples:
            kept_s.append(s[: n_keep_samples])
            kept_b.append(b[: n_keep_samples])
        if traces is None:
            n_tr = min(n_eye_traces, m)
            centre = ((n_tail + k[:n_tr]) * osr + i0 + (phase_ui + skew_residual_ui) * osr
                      + jit[:n_tr] / cfg.dt)
            grid = centre[:, None] + (eye_t * osr)[None, :]
            traces = np.interp(grid.ravel(), np.arange(y.size), y).reshape(grid.shape)
        pos += m

    s_all = np.concatenate(kept_s)[:n_keep_samples]
    b_all = np.concatenate(kept_b)[:n_keep_samples]
    hi, lo = s_all[b_all > 0], s_all[b_all < 0]
    eye_s = float(hi.min() - lo.max()) if hi.size and lo.size else float("nan")
    return TimeResult(lane=lane, ber=n_err / n, n_errors=n_err, n_symbols=n, phase_ui=phase_ui + skew_residual_ui,
                      eye_height_sampled_v=eye_s, jitter_rms_s=feed.rms_s(),
                      error_bursts=n_bursts, eye_time_ui=eye_t, eye_traces=traces, samples=s_all, sample_bits=b_all,
                      extras={"main_cursor_v": resp.main_amplitude, "n_aggressors": len(xt),
                              "block_step_ratio": feed.block_step_ratio(clock), "mode": mode,
                              "sigma_noise_v": noise.sigma_marginal, "noise_filtered": noise.filtered,
                              "n_cursors_used": int(ks.size) if mode == "samples" else None})


__all__ = ["run_time", "TimeResult", "SymbolStream", "shifted_pulse"]
