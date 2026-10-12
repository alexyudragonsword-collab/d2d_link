"""The lane's channel and the pulse it delivers to the sampler.

``ChannelModel`` holds the terminated voltage transfer H(f) on a uniform
DC-inclusive grid, built either from the analytic lossy line (vendored
Halo_Serdes ``analytic``: RLGC with skin and dielectric loss, ABCD cascade,
terminations) or from a Touchstone file (vendored ``touchstone`` reader).
H is normalised so a lossless matched line has H = 1: ``tx.swing_vpp`` is
then the swing a matched load would see and the receiver gets ``swing * |H|``.

``link_response`` adds the transmitter's bandwidth and the optional CTLE and
turns H into the pulse response on the waveform grid (``sim.osr`` samples
per UI); both engines read their cursors off that one pulse.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..config.schema import LinkConfig
from ..vendor.halo import analytic
from ..vendor.halo.response import freq2impulse
from ..vendor.halo.waveform import Waveform


class ChannelModel:
    def __init__(self, H: np.ndarray, f: np.ndarray, name: str = ""):
        self.H = np.asarray(H, dtype=complex)
        self.f = np.asarray(f, dtype=np.float64)
        self.name = name
        if self.H.shape != self.f.shape:
            raise ValueError("H and f must have the same shape")
        if self.f[0] != 0.0:
            raise ValueError("the frequency grid must start at DC")

    @staticmethod
    def grid(cfg: LinkConfig) -> np.ndarray:
        """Uniform DC-inclusive grid whose IFFT lands exactly on ``cfg.dt``:
        f_max = osr / (2 UI), ``channel.n_freq`` points."""
        return np.linspace(0.0, 0.5 / cfg.dt, cfg.channel.n_freq)

    @classmethod
    def from_config(cls, cfg: LinkConfig) -> "ChannelModel":
        ch = cfg.channel
        f = cls.grid(cfg)
        if ch.kind == "touchstone":
            return cls.from_touchstone(ch.file, f, ch.zs_ohm, ch.zl_ohm, ch.renumber, ch.lane)
        return cls.from_rlgc(cfg, f)

    @classmethod
    def from_rlgc(cls, cfg: LinkConfig, f: np.ndarray) -> "ChannelModel":
        p = cfg.rlgc()
        zs, zl = cfg.channel.zs_ohm, cfg.channel.zl_ohm
        length = cfg.channel.length_mm * 1e-3
        r, l, g, c = analytic.skin_effect_rlgc(f, p["rdc_ohm_m"], p["r_skin"], p["l_h_m"], p["c_f_m"],
                                               loss_tangent=p["loss_tangent"], g_per_m=p["g_s_m"])
        abcd = analytic.tline_abcd(r, l, g, c, length, f)
        H = analytic.abcd_to_transfer(abcd, zs, zl) / (zl / (zs + zl))
        return cls(H, f, name=f"{cfg.package.kind}_rlgc_{cfg.channel.length_mm:g}mm")

    @classmethod
    def from_touchstone(cls, path: str, f: np.ndarray, zs: float, zl: float,
                        renumber: bool = True, lane: int = 0) -> "ChannelModel":
        """A Touchstone file through the vendored Halo reader (needs scikit-rf).
        Single-ended terminations are doubled for the differential 2-port the
        reader extracts; the same matched-line normalisation applies."""
        from ..vendor.halo.touchstone import import_diff_network, interp_s2p, terminate_renormalize

        sdd = import_diff_network(path, renumber=renumber, lane=lane)
        sdd_i = interp_s2p(sdd, f)
        H = terminate_renormalize(sdd_i, 2.0 * zs, 2.0 * zl) / (zl / (zs + zl))
        return cls(H, f, name=path)

    # ------------------------------------------------------------ metrics
    def insertion_loss_db(self, f_hz: float) -> float:
        """|H| at ``f_hz`` in dB (0 dB = matched lossless)."""
        return float(20.0 * np.log10(max(abs(np.interp(f_hz, self.f, np.abs(self.H))), 1e-300)))


def tx_response(cfg: LinkConfig, f: np.ndarray) -> np.ndarray:
    bw = cfg.tx.bw_hz
    return np.ones_like(f, dtype=complex) if bw is None else 1.0 / (1.0 + 1j * f / bw)


def ctle_response(cfg: LinkConfig, f: np.ndarray) -> np.ndarray:
    """One zero, two poles, unity DC gain; the zero sits ``peak_db`` below fp1."""
    c = cfg.rx.ctle
    if not c.enable or c.peak_db == 0.0:
        return np.ones_like(f, dtype=complex)
    fp1 = c.fp1_hz if c.fp1_hz is not None else cfg.f_nyquist
    fp2 = c.fp2_hz if c.fp2_hz is not None else 2.0 * fp1
    fz = fp1 / 10.0 ** (c.peak_db / 20.0)
    s = 1j * f
    return (1.0 + s / fz) / ((1.0 + s / fp1) * (1.0 + s / fp2))


@dataclass(frozen=True)
class LinkResponse:
    """Pulse response at the sampler for a +1 symbol of amplitude swing/2."""

    pulse: Waveform          # [V], per sample of ``dt``
    impulse: Waveform        # per-sample weights (sum = H(0))
    channel: ChannelModel
    H_total: np.ndarray      # channel x Tx x CTLE on channel.f
    osr: int

    @property
    def main_index(self) -> int:
        """Sample of the pulse peak. A flat-topped pulse (a short, clean line
        has a 1-UI plateau) takes the plateau's centre, not its first sample:
        the eye is centred there, and the bathtub is read +-0.5 UI around it."""
        p = np.abs(self.pulse.y)
        top = np.flatnonzero(p >= (1.0 - 1e-9) * p.max())
        return int(round(float(top.mean())))

    @property
    def main_amplitude(self) -> float:
        return float(self.pulse.y[self.main_index])

    def cursors(self, phase_ui: float, n_max: int = 64) -> tuple[np.ndarray, int]:
        """Baud-spaced cursors of the pulse at ``phase_ui`` from the peak
        (linear interpolation between waveform samples): ``(c, i_main)`` with
        ``c[i_main]`` the main cursor. Cursors below 1e-9 of the peak at both
        ends are dropped; at most ``n_max`` on each side."""
        p = self.pulse.y
        pos = self.main_index + phase_ui * self.osr
        ks = np.arange(-n_max, n_max + 1)
        idx = pos + ks * self.osr
        c = np.interp(idx, np.arange(p.size), p, left=0.0, right=0.0)
        keep = np.abs(c) > 1e-9 * np.max(np.abs(p))
        keep[n_max] = True
        lo, hi = int(np.argmax(keep)), int(keep.size - np.argmax(keep[::-1]))
        return c[lo:hi], n_max - lo


def link_response(cfg: LinkConfig, channel: ChannelModel | None = None) -> LinkResponse:
    ch = channel if channel is not None else ChannelModel.from_config(cfg)
    f = ch.f
    H = ch.H * tx_response(cfg, f) * ctle_response(cfg, f)
    h = freq2impulse(H, f)
    if not np.isclose(h.dt, cfg.dt, rtol=1e-6):
        raise ValueError(f"impulse dt {h.dt:.3e} does not match the waveform grid {cfg.dt:.3e}")
    osr = cfg.sim.osr
    pulse = np.convolve(h.y, np.ones(osr))[: h.y.size] * (0.5 * cfg.tx.swing_vpp)
    return LinkResponse(Waveform(pulse, h.dt), h, ch, H, osr)


__all__ = ["ChannelModel", "LinkResponse", "link_response", "tx_response", "ctle_response"]
