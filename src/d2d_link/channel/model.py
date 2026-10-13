"""The lane's channel and the pulse it delivers to the sampler.

``ChannelModel`` holds the terminated voltage transfer H(f) on a uniform
DC-inclusive grid, built either from the analytic lossy line (vendored
Halo_Serdes ``analytic``: RLGC with skin and dielectric loss, ABCD cascade,
terminations) or from a Touchstone file (vendored ``touchstone`` reader).
H is normalised so a lossless matched line has H = 1: ``tx.swing_vpp`` is
then the swing a matched load would see and the receiver gets ``swing * |H|``.

``link_response`` adds the transmitter's bandwidth, the receiver front end's
(``rx.bw_hz``, phase 7) and the optional CTLE and turns H into the pulse
response on the waveform grid (``sim.osr`` samples per UI); both engines read
their cursors off that one pulse. ``noise_shaping_gain`` is what the same
front end and CTLE do to white input noise (``rx.noise_at: input``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..config.schema import LinkConfig
from ..vendor.halo import analytic
from ..vendor.halo.response import freq2impulse
from ..vendor.halo.waveform import Waveform


class ChannelModel:
    def __init__(self, H: np.ndarray, f: np.ndarray, name: str = "",
                 xtalk_H: dict[int, np.ndarray] | None = None):
        self.H = np.asarray(H, dtype=complex)
        self.f = np.asarray(f, dtype=np.float64)
        self.name = name
        self.xtalk_H = xtalk_H        # aggressor -> this lane's receiver, by neighbour distance (Touchstone files)
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
            if ch.touchstone_mode == "single_ended":
                return cls.from_touchstone_single_ended(ch.file, f, ch.zs_ohm, ch.zl_ohm, ch.lane, ch.touchstone_lanes)
            return cls.from_touchstone(ch.file, f, ch.zs_ohm, ch.zl_ohm, ch.renumber, ch.lane)
        return cls.from_rlgc(cfg, f)

    @classmethod
    def from_touchstone_single_ended(cls, path: str, f: np.ndarray, zs: float, zl: float, lane: int = 0,
                                     n_lanes: int | None = None) -> "ChannelModel":
        """A single-ended 2N-port file (``channel/touchstone_se.py``): the
        lane's through path, with the file's far-end coupling from the
        neighbours kept on ``xtalk_H`` for ``channel.xtalk: touchstone``."""
        from .touchstone_se import read_single_ended

        H, xt = read_single_ended(path, f, zs, zl, lane, n_lanes)
        return cls(H, f, name=f"{path}[lane {lane}]", xtalk_H=xt)

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
        return cls(fill_dc(H, f), f, name=path)

    # ------------------------------------------------------------ metrics
    def insertion_loss_db(self, f_hz: float) -> float:
        """|H| at ``f_hz`` in dB (0 dB = matched lossless)."""
        return float(20.0 * np.log10(max(abs(np.interp(f_hz, self.f, np.abs(self.H))), 1e-300)))


def fill_dc(H: np.ndarray, f: np.ndarray) -> np.ndarray:
    """A measured network rarely holds a DC point, and the vendored
    interpolation fills transmission terms outside the file's band with 0 --
    below it too, so on this DC-inclusive grid the through path came out with
    H(0) = 0: a notch that put a long negative tail on every pulse (phase 6
    found it with a synthetic file: a 182 mV eye read 60 mV). The DC value
    extrapolates the two lowest in-band magnitudes in sqrt(f) (conductor loss
    goes as sqrt(f) at low frequency: log|H| = -a sqrt(f) - b), capped at 1 and
    never below the lowest point; real (a line has no phase at DC)."""
    H = np.asarray(H, dtype=complex).copy()
    if f.size > 2 and f[0] == 0.0 and H[0] == 0.0:
        h1, h2 = abs(H[1]), abs(H[2])
        if 0.0 < h2 < h1 <= 1.0:
            a = (math.log(h1) - math.log(h2)) / (math.sqrt(f[2]) - math.sqrt(f[1]))
            b = -math.log(h1) - a * math.sqrt(f[1])
            H[0] = min(1.0, max(h1, math.exp(-b)))
        else:
            H[0] = min(1.0, h1)
    elif f.size > 1 and f[0] == 0.0 and H[0] == 0.0:
        H[0] = abs(H[1])
    return H


def tx_response(cfg: LinkConfig, f: np.ndarray) -> np.ndarray:
    """The driver's first-order pole at ``cfg.tx_bw_hz`` (twice the Nyquist
    frequency unless the config says otherwise); ``inf`` is the ideal edge."""
    bw = cfg.tx_bw_hz
    return np.ones_like(f, dtype=complex) if not np.isfinite(bw) else 1.0 / (1.0 + 1j * f / bw)


def rx_response(cfg: LinkConfig, f: np.ndarray) -> np.ndarray:
    """The receiver front end's first-order pole at ``rx.bw_hz`` on the data
    path (pads, ESD, input amplifier); flat when the config leaves it None.
    The clock tree has its own bandwidth (``clocking.tree_bw_hz``) on the
    clock's phase -- this is the data edges' counterpart."""
    bw = cfg.rx.bw_hz
    return np.ones_like(f, dtype=complex) if bw is None else 1.0 / (1.0 + 1j * f / bw)


def noise_shaping_gain(cfg: LinkConfig) -> float:
    """sigma at the sampler / sigma at the input for white input noise
    (``rx.noise_at: input``): sqrt(integral_0^inf |H_fe(f) H_ctle(f)|^2 df / f_N),
    the input RMS being referred to the Nyquist band (an ideal integrating
    receiver's noise bandwidth is exactly f_N). The integral runs to
    infinity -- the sampler's noise is physics, not a waveform-grid number;
    the time engine's filtered noise is band-limited to osr / (2 UI) and
    sees a little less (3 % of the variance for a 24 GHz front end on the
    32x grid of 32 GT/s). 1.0 when the noise is referred at the sampler."""
    if cfg.rx.noise_at != "input":
        return 1.0
    from scipy.integrate import quad

    def h2(f: float) -> float:
        x = np.array([f])
        return float(np.abs(rx_response(cfg, x) * ctle_response(cfg, x))[0] ** 2)

    bw = cfg.rx.bw_hz
    # f = bw tan(theta) folds [0, inf) onto [0, pi/2): the integrand stays
    # bounded (|H|^2 falls at least as 1/f^2, sec^2 grows as f^2) and the
    # one quad resolves the pole region and the tail alike
    total = quad(lambda th: h2(bw * math.tan(th)) * bw / math.cos(th) ** 2, 0.0, 0.5 * math.pi - 1e-9,
                 limit=200, epsabs=0.0, epsrel=1e-10)[0]
    return math.sqrt(total / cfg.f_nyquist)


def sampler_noise_rms_v(cfg: LinkConfig) -> float:
    """The Gaussian noise RMS at the decision point both engines use."""
    return cfg.rx.noise_rms_v * noise_shaping_gain(cfg)


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


def xtalk_response(cfg: LinkConfig, f: np.ndarray, neighbour: int) -> np.ndarray:
    """Far-end crosstalk from a lane ``neighbour`` places away, relative to the
    through response: coupled lines couple the *derivative* of the aggressor
    at low frequency and saturate near the band edge, so X/H = k (jf/fn) /
    (1 + jf/fn) with k set by the configured level at the Nyquist frequency
    fn. Zero when crosstalk is off or the neighbour is further than two lanes."""
    f = np.asarray(f, dtype=np.float64)
    if cfg.channel.xtalk in ("none", "touchstone") or neighbour not in (1, 2):
        return np.zeros_like(f, dtype=complex)
    adj, sec = cfg.xtalk_db()          # configured level, or the coupled-line estimate
    level = 10.0 ** ((adj if neighbour == 1 else sec) / 20.0)
    u = 1j * f / cfg.f_nyquist
    return level * math.sqrt(2.0) * u / (1.0 + u)


def next_response(cfg: LinkConfig, f: np.ndarray) -> np.ndarray:
    """Near-end crosstalk a reverse-direction neighbour launches at this
    lane's receiving die: the backward-coupled wave of a weakly coupled pair
    is K_b times the aggressor's signal minus the same signal delayed by the
    round trip of the coupled length, 2 tau_c (Johnson & Graham: a step
    couples back as a pulse of height K_b and length 2 tau_c). It never
    travels the lossy line, so there is no channel H in it; the aggressor's
    driver edge and this receiver's CTLE apply."""
    f = np.asarray(f, dtype=np.float64)
    kb = cfg.next_ratio()
    if kb == 0.0:
        return np.zeros_like(f, dtype=complex)
    tau = cfg.coupled_delay_s()
    return kb * (1.0 - np.exp(-2j * math.pi * f * 2.0 * tau))


def read_cursors(pulse: np.ndarray, position: float, osr: int, n_max: int = 64,
                 keep_centre: bool = True) -> tuple[np.ndarray, int]:
    """Baud-spaced samples of ``pulse`` around sample ``position`` (linear
    interpolation): ``(c, i_centre)``. Cursors below 1e-9 of the pulse's peak
    at both ends are dropped; the centre is kept when ``keep_centre``."""
    ks = np.arange(-n_max, n_max + 1)
    c = np.interp(position + ks * osr, np.arange(pulse.size), pulse, left=0.0, right=0.0)
    keep = np.abs(c) > 1e-9 * max(float(np.max(np.abs(pulse))), 1e-300)
    if keep_centre:
        keep[n_max] = True
    if not keep.any():
        return np.zeros(0), 0
    lo, hi = int(np.argmax(keep)), int(keep.size - np.argmax(keep[::-1]))
    return c[lo:hi], n_max - lo


@dataclass(frozen=True)
class LinkResponse:
    """Pulse response at the sampler for a +1 symbol of amplitude swing/2, and
    the crosstalk pulses a neighbour lane's +1 symbol leaves on it."""

    pulse: Waveform          # [V], per sample of ``dt``
    impulse: Waveform        # per-sample weights (sum = H(0))
    channel: ChannelModel
    H_total: np.ndarray      # channel x Tx x CTLE on channel.f
    osr: int
    xtalk_pulses: dict = None   # {neighbour distance: Waveform [V]}; empty when crosstalk is off
    noise_impulse: Waveform | None = None   # front end x CTLE impulse (sum = 1) for rx.noise_at: input

    @property
    def main_index(self) -> int:
        """The symbol's reference sample: the midpoint of the pulse's
        half-amplitude span. A peaked pulse puts it close to the peak; a
        flat-topped pulse (a short, clean line has a 1-UI plateau, tilted a
        little by the driver's pole and rippled by the band edge) puts it at
        the plateau's centre, where the peak sample itself wandered to either
        end in earlier versions and the +-0.5 UI bathtub window saw half an
        eye. The eye centre is still searched for around it."""
        p = np.abs(self.pulse.y)
        above = np.flatnonzero(p >= 0.5 * p.max())
        return int(round(0.5 * float(above[0] + above[-1])))

    @property
    def main_amplitude(self) -> float:
        return float(self.pulse.y[self.main_index])

    def cursors(self, phase_ui: float, n_max: int = 64) -> tuple[np.ndarray, int]:
        """Baud-spaced cursors of the pulse at ``phase_ui`` from the peak
        (linear interpolation between waveform samples): ``(c, i_main)`` with
        ``c[i_main]`` the main cursor. Cursors below 1e-9 of the peak at both
        ends are dropped; at most ``n_max`` on each side."""
        return read_cursors(self.pulse.y, self.main_index + phase_ui * self.osr, self.osr, n_max)

    def xtalk_cursors(self, neighbour, phase_ui: float, rel_skew_ui: float = 0.0,
                      n_max: int = 64) -> np.ndarray:
        """Baud-spaced crosstalk cursors a neighbour ``neighbour`` lanes away
        leaves at this lane's sampling instant (``phase_ui`` from its own
        peak). The aggressor's symbols arrive ``rel_skew_ui`` later than the
        victim's, so its pulse is read that much earlier. ``neighbour`` is a
        distance (1, 2) or ``"next"`` for the reverse-direction neighbour's
        near-end pulse. Empty when there is no coupling of that kind."""
        pulses = self.xtalk_pulses or {}
        if neighbour not in pulses:
            return np.zeros(0)
        pos = self.main_index + (phase_ui - rel_skew_ui) * self.osr
        c, _ = read_cursors(pulses[neighbour].y, pos, self.osr, n_max, keep_centre=False)
        return c


def link_response(cfg: LinkConfig, channel: ChannelModel | None = None) -> LinkResponse:
    ch = channel if channel is not None else ChannelModel.from_config(cfg)
    f = ch.f
    rx_front = rx_response(cfg, f) * ctle_response(cfg, f)
    H = ch.H * tx_response(cfg, f) * rx_front
    h = freq2impulse(H, f)
    if not np.isclose(h.dt, cfg.dt, rtol=1e-6):
        raise ValueError(f"impulse dt {h.dt:.3e} does not match the waveform grid {cfg.dt:.3e}")
    osr = cfg.sim.osr
    amp = 0.5 * cfg.tx.swing_vpp
    pulse = np.convolve(h.y, np.ones(osr))[: h.y.size] * amp
    xt = {}
    front = tx_response(cfg, f) * rx_front
    if cfg.channel.xtalk == "touchstone":
        for k, hx_f in (ch.xtalk_H or {}).items():
            hx = freq2impulse(hx_f * front, f)
            xt[k] = Waveform(np.convolve(hx.y, np.ones(osr))[: hx.y.size] * amp, hx.dt)
    elif cfg.channel.xtalk != "none":
        for k in (1, 2):
            hx = freq2impulse(H * xtalk_response(cfg, f, k), f)
            xt[k] = Waveform(np.convolve(hx.y, np.ones(osr))[: hx.y.size] * amp, hx.dt)
    if cfg.channel.xtalk_next != "none":
        hn = freq2impulse(next_response(cfg, f) * front, f)
        xt["next"] = Waveform(np.convolve(hn.y, np.ones(osr))[: hn.y.size] * amp, hn.dt)
    noise_h = freq2impulse(rx_front, f) if cfg.rx.noise_at == "input" else None
    return LinkResponse(Waveform(pulse, h.dt), h, ch, H, osr, xt, noise_h)


__all__ = ["ChannelModel", "LinkResponse", "link_response", "tx_response", "rx_response", "ctle_response",
           "noise_shaping_gain", "sampler_noise_rms_v", "xtalk_response", "next_response", "read_cursors",
           "fill_dc"]
