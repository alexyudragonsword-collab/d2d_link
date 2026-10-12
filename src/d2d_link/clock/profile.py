"""A clock phase-noise profile as pll_simulator exports it (docs/clock_profile.md).

The file is the only thing shared with pll_simulator: carrier ``f0_hz``, an
offset grid ``f_hz``, the total single-sideband L(f) ``l_dbc_hz`` on it, a
spur table and a provenance line. Two conventions it is easy to lose, both
pinned by tests: L(f) is single-sideband, so S_phi = 2 * 10^(L/10); and timing
is phase / (2 pi f0_hz) with the *file's* carrier -- a profile of a 10 GHz PLL
driving a 16 GHz forwarded clock through a multiplier still describes seconds
against 10 GHz, which is why nothing here derives f0 from the data rate.

The reader follows Halo_Serdes ``tx/clock.py`` (same file format, same
interpolation in (log f, dB), same zero above f0/2) with the primitives
vendored from pllsim.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..vendor.pllsim.jitter import integrate_pn, sphi_from_ldbc

TWOPI = 2.0 * np.pi
_REQUIRED = ("f0_hz", "f_hz", "l_dbc_hz")
_OPTIONAL = ("spurs", "source")


@dataclass(frozen=True)
class ClockProfile:
    f0_hz: float
    f_hz: np.ndarray
    l_dbc_hz: np.ndarray
    spurs: tuple[tuple[float, float], ...] = ()
    source: str = ""

    def __post_init__(self):
        f = np.asarray(self.f_hz, dtype=np.float64)
        l_dbc = np.asarray(self.l_dbc_hz, dtype=np.float64)
        if not (np.isfinite(self.f0_hz) and self.f0_hz > 0):
            raise ValueError(f"clock profile: f0_hz must be > 0, got {self.f0_hz!r}")
        if f.ndim != 1 or f.size < 2:
            raise ValueError("clock profile: f_hz needs at least two points")
        if l_dbc.shape != f.shape:
            raise ValueError(f"clock profile: l_dbc_hz has {l_dbc.size} points, f_hz has {f.size}")
        if np.any(f <= 0) or np.any(np.diff(f) <= 0):
            raise ValueError("clock profile: f_hz must be positive and strictly ascending")
        if not np.all(np.isfinite(l_dbc)):
            raise ValueError("clock profile: l_dbc_hz must be finite")
        for fs, dbc in self.spurs:
            if not (fs > 0 and np.isfinite(dbc)):
                raise ValueError(f"clock profile: bad spur ({fs!r}, {dbc!r})")
        object.__setattr__(self, "f_hz", f)
        object.__setattr__(self, "l_dbc_hz", l_dbc)
        object.__setattr__(self, "spurs", tuple((float(a), float(b)) for a, b in self.spurs))

    @classmethod
    def load(cls, path: str | Path, *, f0_hz: float | None = None) -> "ClockProfile":
        import yaml

        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"clock profile not found: {path}")
        with p.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{path}: a clock profile is a mapping")
        unknown = sorted(set(data) - set(_REQUIRED) - set(_OPTIONAL))
        if unknown:
            raise ValueError(f"{path}: unknown clock-profile key(s) {unknown}; see docs/clock_profile.md")
        missing = [k for k in _REQUIRED if k not in data]
        if missing:
            raise ValueError(f"{path}: clock profile is missing {missing}")
        spurs = []
        for row in data.get("spurs") or []:
            if not (isinstance(row, dict) and {"f_hz", "dbc"} <= set(row)):
                raise ValueError(f"{path}: each spur is {{f_hz, dbc}}, got {row!r}")
            spurs.append((float(row["f_hz"]), float(row["dbc"])))
        return cls(f0_hz=float(f0_hz if f0_hz is not None else data["f0_hz"]),
                   f_hz=np.asarray(data["f_hz"], dtype=np.float64),
                   l_dbc_hz=np.asarray(data["l_dbc_hz"], dtype=np.float64),
                   spurs=tuple(spurs), source=str(data.get("source") or ""))

    def save(self, path: str | Path) -> Path:
        import yaml

        p = Path(path)
        data = {"f0_hz": float(self.f0_hz), "f_hz": [float(x) for x in self.f_hz],
                "l_dbc_hz": [float(x) for x in self.l_dbc_hz],
                "spurs": [{"f_hz": a, "dbc": b} for a, b in self.spurs], "source": self.source}
        with p.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, sort_keys=False)
        return p

    # ------------------------------------------------------------ spectra
    def s_phi(self, f: np.ndarray) -> np.ndarray:
        """S_phi(f) [rad^2/Hz]: L(f) interpolated in (log f, dB); the first
        value held below the grid, zero above f0/2 (a clock's phase noise is
        defined to its own Nyquist and no further)."""
        f = np.asarray(f, dtype=np.float64)
        l_dbc = np.interp(np.log10(np.maximum(f, 1e-300)), np.log10(self.f_hz), self.l_dbc_hz)
        return np.where(f > self.f_hz[-1], 0.0, sphi_from_ldbc(l_dbc))

    def s_timing(self, f: np.ndarray) -> np.ndarray:
        """One-sided PSD of the timing jitter [s^2/Hz]: S_phi / (2 pi f0)^2."""
        return self.s_phi(f) / (TWOPI * self.f0_hz) ** 2

    def rms_jitter_s(self, f1: float, f2: float | None = None) -> float:
        """RMS timing jitter [s] of the continuous part over [f1, f2] (f2 default f0/2)."""
        f2 = 0.5 * self.f0_hz if f2 is None else f2
        return float(np.sqrt(integrate_pn(self.f_hz, sphi_from_ldbc(self.l_dbc_hz), f1, f2))
                     / (TWOPI * self.f0_hz))

    def spur_amplitudes_s(self) -> list[tuple[float, float]]:
        """``(offset_hz, peak amplitude [s])``: a single-sideband spur at ``dbc``
        is a sinusoidal phase modulation of peak 2 * 10^(dbc/20) rad."""
        return [(fs, 2.0 * 10.0 ** (dbc / 20.0) / (TWOPI * self.f0_hz)) for fs, dbc in self.spurs]

    def shifted(self, shift_db: float) -> "ClockProfile":
        """The same shape, every level moved by ``shift_db`` (spurs included)."""
        if shift_db == 0.0:
            return self
        return ClockProfile(self.f0_hz, self.f_hz, self.l_dbc_hz + shift_db,
                            tuple((a, b + shift_db) for a, b in self.spurs), self.source)

    def scaled_to_rms(self, rms_s: float, f1: float, f2: float | None = None) -> "ClockProfile":
        f2 = 0.5 * self.f0_hz if f2 is None else f2
        have = self.rms_jitter_s(f1, f2)
        if not (have > 0 and rms_s > 0):
            raise ValueError("scaled_to_rms needs a non-zero profile and target")
        return self.shifted(20.0 * np.log10(rms_s / have))


__all__ = ["ClockProfile"]
