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
import warnings
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
        if cfg.channel.skin_inductance:
            # the skin effect's surface impedance is (1 + j) r_skin sqrt(f):
            # the resistance the vendored RLGC carries comes with an equal
            # internal reactance, an inductance r_skin / (2 pi sqrt(f)) that
            # falls with frequency. Without it H(f) is not causal (R rises
            # with f while the phase is pure LC delay) and the pulse carries
            # energy before the line's delay -- 6.5 % of the main cursor on
            # the 25 mm standard line, 1 % with it; the lossy line's group
            # delay dispersion, most of its post-cursor ISI, was missing too
            # (second health check, 2026-11-02). At DC the reactance is zero
            # whatever L is, so the 1 / sqrt(0) point needs no value.
            l_int = np.zeros_like(f)
            np.divide(p["r_skin"], 2.0 * np.pi * np.sqrt(f), out=l_int, where=f > 0.0)
            l = l + l_int
        if cfg.channel.dielectric == "djordjevic_sarkar" and p["loss_tangent"] > 0.0:
            # a constant tan d on a constant C is not causal either (the
            # dielectric side of what 9b fixed for the skin effect): the loss
            # comes with a permittivity that falls with frequency. Wideband
            # Debye (Djordjevic-Sarkar, poles 1e3..1e12 rad/s), matched to the
            # preset C (eps_eff) and tan d at loss_tangent_ref_hz; the DC
            # conductance g_s_m stays. x1: 209.7 mV / 0.761 UI -> see LOG (phase 15)
            eps = djordjevic_sarkar(f, p["loss_tangent"], cfg.channel.loss_tangent_ref_hz)
            g = np.full_like(f, p["g_s_m"])
            c = p["c_f_m"] * eps
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
        return cls(fill_dc(extend_band(H, f, float(sdd.f[-1])), f), f, name=path)

    # ------------------------------------------------------------ metrics
    def insertion_loss_db(self, f_hz: float) -> float:
        """|H| at ``f_hz`` in dB (0 dB = matched lossless)."""
        return float(20.0 * np.log10(max(abs(np.interp(f_hz, self.f, np.abs(self.H))), 1e-300)))

    def xtalk_db(self, f_hz: float, neighbour: int = 1) -> float | None:
        """A Touchstone file's far-end coupling from the lane ``neighbour``
        places away relative to the through path, |X / H| at ``f_hz`` in dB;
        None when the model carries no such term."""
        hx = (self.xtalk_H or {}).get(neighbour)
        if hx is None:
            return None
        x = abs(np.interp(f_hz, self.f, np.abs(hx)))
        h = abs(np.interp(f_hz, self.f, np.abs(self.H)))
        return float(20.0 * np.log10(max(x, 1e-300) / max(h, 1e-300)))


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


def djordjevic_sarkar(f: np.ndarray, tan_d: float, f_ref: float, m1: float = 3.0, m2: float = 12.0) -> np.ndarray:
    """Relative complex permittivity eps(f) / eps'(f_ref) of a wideband Debye
    dielectric (Djordjevic & Sarkar, IEEE Trans. EMC 2001): a flat loss
    tangent between 10^m1 and 10^m2 rad/s with the dispersion Kramers-Kronig
    requires, scaled so eps'(f_ref) = 1 and -eps''/eps' = ``tan_d`` there.
    Multiplying a line's C by it gives jwC eps = jwC eps' + wC(-eps''): the
    capacitance and the dielectric conductance of one causal material."""
    w = 2.0 * np.pi * np.asarray(f, dtype=np.float64)

    def shape(wv):
        return np.log10((10.0 ** m2 + 1j * wv) / (10.0 ** m1 + 1j * wv)) / (m2 - m1)

    s_ref = shape(np.array([2.0 * np.pi * f_ref]))[0]
    de = tan_d / (-s_ref.imag)                 # -eps''(f_ref) = tan_d with eps'(f_ref) = 1
    e_inf = 1.0 - de * s_ref.real
    return e_inf + de * shape(w)


def extend_band(H: np.ndarray, f: np.ndarray, f_edge: float) -> np.ndarray:
    """A measured network ends at ``f_edge`` and the vendored interpolation
    fills transmission beyond it with 0: a brick wall on this grid, which
    runs to osr x f_Nyquist (512 GHz at 32 GT/s on the 32x grid). The wall
    rings the pulse (Gibbs) and throws away the attenuation the line goes on
    having: the 25 mm standard line written to a file that stops at 50 GHz
    read 0.016 UI less eye width than the same line in closed form (two
    thirds of x1's margin; second health check). Beyond the edge log|H| is
    continued linearly in f with the slope fitted over the file's last
    decade [f_edge / 10, f_edge] (dielectric loss grows as f and dominates
    there, conductor loss as sqrt f; the fit sits between), never rising;
    the phase continues with that decade's mean group delay. The through
    path only -- a coupling term can rise through the band edge, and 0 stays
    the conservative fill for it. A file covering the grid is left alone."""
    H = np.asarray(H, dtype=complex).copy()
    out = f > f_edge * (1.0 + 1e-9)
    if not out.any():
        return H
    band = (f >= f_edge / 10.0) & ~out & (np.abs(H) > 0.0)
    if np.count_nonzero(band) < 3:
        band = np.zeros_like(out)
        band[np.flatnonzero(~out & (np.abs(H) > 0.0))[-3:]] = True
    if np.count_nonzero(band) < 2:
        return H
    fb, hb = f[band], H[band]
    slope = min(float(np.polyfit(fb, np.log(np.abs(hb)), 1)[0]), 0.0)
    delay = float(np.polyfit(fb, np.unwrap(np.angle(hb)), 1)[0])        # d(phase)/df, negative for a delay
    df = f[out] - fb[-1]
    H[out] = abs(hb[-1]) * np.exp(slope * df) * np.exp(1j * (np.angle(hb[-1]) + delay * df))
    return H


def extend_band_like(X: np.ndarray, f: np.ndarray, f_edge: float, H: np.ndarray) -> np.ndarray:
    """A coupling term past the file's band: the through path ``H`` (already
    extended) sets the decay, X(f) = X(f_edge) H(f) / H(f_edge) beyond
    ``f_edge``. A coupled line's far-end term is the through path times a
    coupling shape that turns over at high frequency, so its own log|X|
    slope there says nothing about what follows, while the attenuation it
    shares with the through path does. On the 25 mm line written as a 3-lane
    file cut at 50 GHz the middle lane's eye read 3.5 mV / 0.010 UI off the
    full-band file with the 0 fill, 0.1 mV / 0.005 UI with this (the rest is
    the through path's own extension). A file covering the grid is left alone."""
    X = np.asarray(X, dtype=complex).copy()
    out = f > f_edge * (1.0 + 1e-9)
    if not out.any():
        return X
    i_edge = int(np.flatnonzero(~out)[-1])
    if H[i_edge] == 0.0:
        return X
    X[out] = X[i_edge] * (H[out] / H[i_edge])
    return X


#: |H_total(f_max)| / |H_total(0)| above which link_response warns: a grid whose
#: top still passes a fifth of the signal is a brick-wall filter of its own
GRID_TOP_WARN = 0.2


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
    through response. A weakly coupled pair carries an even and an odd mode
    whose delays differ by 2 tau; relative to the mean-delay through path the
    victim's far end sees ``X/H = j sin(2 pi f tau)`` -- the derivative of
    the aggressor (j 2 pi f tau, the coupled-line estimate of
    ``channel.coupled``) while 2 pi f tau << 1, never above 1. tau is set so
    that ``|X/H|`` at the Nyquist frequency is the configured (``fext``) or
    estimated (``coupled``) level.

    Until 0.13.5 the shape was ``k sqrt(2) u / (1 + u)``, u = jf/f_N: the same
    level at f_N, but 3 dB above the derivative below it and flat above it
    (third health check: the x5 middle lane read 60 mV apart between the two).
    Zero when crosstalk is off or the neighbour is further than two lanes."""
    f = np.asarray(f, dtype=np.float64)
    if cfg.channel.xtalk in ("none", "touchstone") or neighbour not in (1, 2):
        return np.zeros_like(f, dtype=complex)
    adj, sec = cfg.xtalk_db()          # configured level, or the coupled-line estimate
    level = min(10.0 ** ((adj if neighbour == 1 else sec) / 20.0), 1.0)
    tau = math.asin(level) / (2.0 * math.pi * cfg.f_nyquist)
    return 1j * np.sin(2.0 * math.pi * f * tau)


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
                 keep_centre: bool = True, floor: float = 1e-6, peak: float | None = None) -> tuple[np.ndarray, int]:
    """Baud-spaced samples of ``pulse`` around sample ``position`` (linear
    interpolation): ``(c, i_centre)``. Cursors below ``floor`` of the pulse's
    peak at both ends are dropped (a 0.2 uV cursor on a 200 mV pulse is
    nothing next to the 50 uV ISI bin; the 1e-9 of earlier versions kept
    the crosstalk pulses' 1e-8 tails and tripled a module's run time once
    the window grew to 512 UI); the centre is kept when ``keep_centre``.
    ``peak`` is max|pulse| when the caller has it (perf round III: scanning
    the 16k-sample pulse for it on every call was most of this function).
    The interpolation is np.interp's arithmetic, (y1 - y0) (x - x0) + y0 on
    the unit grid, by direct indexing (bit for bit the same, no search)."""
    ks = np.arange(-n_max, n_max + 1)
    x = position + ks * osr
    n = pulse.size
    i = np.floor(x).astype(np.int64)
    inside = (i >= 0) & (i < n - 1)
    ii = np.clip(i, 0, n - 2)
    c = (pulse[ii + 1] - pulse[ii]) * (x - i) + pulse[ii]
    c = np.where(inside, c, 0.0)
    last = x == n - 1
    if last.any():
        c = np.where(last, pulse[-1], c)
    top = float(np.max(np.abs(pulse))) if peak is None else peak
    keep = np.abs(c) > floor * max(top, 1e-300)
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
    cursor_reach: int = 64      # cursors read on each side of the main one (sim.stat_cursor_reach)
    cursor_floor: float = 1e-6  # end cursors below this fraction of the pulse's peak are dropped (sim.stat_cursor_floor)
    grid_top_response: float = 0.0   # |H_total| at the grid's top frequency osr x f_N, relative to its DC value: what the
                                     # brick wall there cuts off (0.58 at 4 GT/s on the 32x grid rang the pulse, phase 12)

    def __post_init__(self):
        # the peaks the cursor floor is measured against, once per pulse
        object.__setattr__(self, "_peak", float(np.max(np.abs(self.pulse.y))))
        object.__setattr__(self, "_xt_peak", {k: float(np.max(np.abs(w.y))) for k, w in (self.xtalk_pulses or {}).items()})

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

    def cursors(self, phase_ui: float, n_max: int | None = None) -> tuple[np.ndarray, int]:
        """Baud-spaced cursors of the pulse at ``phase_ui`` from the peak
        (linear interpolation between waveform samples): ``(c, i_main)`` with
        ``c[i_main]`` the main cursor. Cursors below 1e-9 of the peak at both
        ends are dropped (``cursor_floor`` of the peak); at most ``n_max``
        (default ``cursor_reach``) on each side."""
        n_max = self.cursor_reach if n_max is None else n_max
        return read_cursors(self.pulse.y, self.main_index + phase_ui * self.osr, self.osr, n_max, floor=self.cursor_floor,
                            peak=self._peak)

    def xtalk_cursors(self, neighbour, phase_ui: float, rel_skew_ui: float = 0.0,
                      n_max: int | None = None) -> np.ndarray:
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
        n_max = self.cursor_reach if n_max is None else n_max
        c, _ = read_cursors(pulses[neighbour].y, pos, self.osr, n_max, keep_centre=False, floor=self.cursor_floor,
                            peak=self._xt_peak.get(neighbour))
        return c


def link_response(cfg: LinkConfig, channel: ChannelModel | None = None) -> LinkResponse:
    ch = channel if channel is not None else ChannelModel.from_config(cfg)
    f = ch.f
    rx_front = rx_response(cfg, f) * ctle_response(cfg, f)
    H = ch.H * tx_response(cfg, f) * rx_front
    top = float(abs(H[-1]) / max(abs(H[0]), 1e-300))
    if top > GRID_TOP_WARN:
        warnings.warn(f"the waveform grid's top frequency {f[-1] / 1e9:.0f} GHz (sim.osr x f_Nyquist) still passes "
                      f"{top:.0%} of the response: the brick wall there rings the pulse. Raise sim.osr (config.with_data_rate "
                      f"keeps the grid's top when the rate changes).", stacklevel=2)
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
    return LinkResponse(Waveform(pulse, h.dt), h, ch, H, osr, xt, noise_h,
                        cursor_reach=cfg.sim.stat_cursor_reach, cursor_floor=cfg.sim.stat_cursor_floor,
                        grid_top_response=top)


__all__ = ["ChannelModel", "LinkResponse", "link_response", "tx_response", "rx_response", "ctle_response",
           "noise_shaping_gain", "sampler_noise_rms_v", "xtalk_response", "next_response", "read_cursors",
           "fill_dc"]
