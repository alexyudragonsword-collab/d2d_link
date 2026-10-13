"""Bit patterns for the time engine: PRBS15 / PRBS31 (Fibonacci LFSR) or random.

The PRBS recurrence b[i] = b[i-n] ^ b[i-t] is advanced ``t`` bits at a time
(every index a block needs is older than the block), so a 10^7-bit run is a
few hundred thousand numpy steps rather than ten million Python ones.
"""

from __future__ import annotations

import numpy as np

_TAPS = {"prbs15": (15, 14), "prbs31": (31, 28)}


class PatternSource:
    """Yields ``n`` symbols in {-1, +1} per call, continuing the sequence."""

    def __init__(self, kind: str, rng: np.random.Generator):
        self.kind = kind
        self.rng = rng
        if kind in _TAPS:
            self.n, self.t = _TAPS[kind]
            hist = rng.integers(0, 2, self.n).astype(np.int8)
            if not hist.any():
                hist[0] = 1
            self.hist = hist          # the last n bits, oldest first
        elif kind != "random":
            raise ValueError(f"unknown pattern {kind!r}")

    def next(self, n: int) -> np.ndarray:
        if self.kind == "random":
            return 2.0 * self.rng.integers(0, 2, n) - 1.0
        nb, t = self.n, self.t
        buf = np.empty(nb + n, dtype=np.int8)
        buf[:nb] = self.hist
        pos = nb
        end = nb + n
        while pos < end:
            m = min(t, end - pos)
            buf[pos:pos + m] = buf[pos - nb:pos - nb + m] ^ buf[pos - t:pos - t + m]
            pos += m
        self.hist = buf[-nb:].copy()
        return 2.0 * buf[nb:].astype(np.float64) - 1.0


__all__ = ["PatternSource"]
