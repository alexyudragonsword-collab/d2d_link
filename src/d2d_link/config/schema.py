"""Single-source-of-truth configuration schema (invariant #1).

Package type, data rate, lane count and clocking scheme all live here, in one
frozen ``LinkConfig``; examples, tools and any future GUI only read it. The
dataclasses are frozen: derive variants with ``dataclasses.replace`` or
``loader.apply_overrides``. Every field is validated at construction so a bad
value fails here with its name, not deep inside an engine as a NaN.

Numbers that come from the UCIe specification are *not* hard-coded here: the
``TargetConfig`` fields default to ``None``, which means "the value in
``data/spec/ucie_survey.yaml`` for this package and rate" (invariant #5: every
such number carries its ``source``). Setting a field overrides it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, Optional

SCHEMA_VERSION = 1


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ValueError(msg)


def _require_in(value, allowed, name: str) -> None:
    _require(value in allowed, f"{name} must be one of {sorted(allowed)}, got {value!r}")


def _finite_nonneg(value: float, name: str) -> None:
    _require(math.isfinite(value) and value >= 0.0, f"{name} must be finite and >= 0, got {value!r}")


def _finite_pos(value: float, name: str) -> None:
    _require(math.isfinite(value) and value > 0.0, f"{name} must be finite and > 0, got {value!r}")


# ---------------------------------------------------------------------------
# package / channel
# ---------------------------------------------------------------------------

#: Per-package *model* presets (``data/spec/model_presets.yaml``, every entry
#: ``source: model``): the analytic line's loss parameters and characteristic
#: impedance, the routing stack-up, and the behavioural crosstalk level, used
#: where ``ChannelConfig`` leaves a parameter ``None``. The line's L and C are
#: not preset: ``LinkConfig.rlgc`` derives them from ``z0_ohm`` and the
#: stack-up's effective permittivity (Hammerstad), so the channel's delay and
#: the coupled-line crosstalk estimate travel at one speed. Earlier versions
#: carried L and C as separate numbers whose implied eps_eff (3.94 / 5.75)
#: contradicted the stack-up's eps_r (3.5 / 3.3). The reach and pitch figures
#: the packages are known by live in ucie_survey.yaml with their own source.
C0 = 299_792_458.0
RLGC_PRESET_KEYS = ("rdc_ohm_m", "r_skin", "loss_tangent", "g_s_m", "z0_ohm")
STACKUP_KEYS = ("trace_width_um", "dielectric_height_um", "eps_r")


def _load_presets():
    from ..spec import preset_values

    values = preset_values()
    rlgc = {pkg: {k: float(v[k]) for k in RLGC_PRESET_KEYS} for pkg, v in values.items()}
    stack = {pkg: {k: float(v[k]) for k in STACKUP_KEYS} for pkg, v in values.items()}
    xt = {pkg: float(v["xtalk_adjacent_db"]) for pkg, v in values.items()}
    return rlgc, stack, xt


PACKAGE_RLGC: dict[str, dict[str, float]]
PACKAGE_STACKUP: dict[str, dict[str, float]]
PACKAGE_XTALK_DB: dict[str, float]
PACKAGE_RLGC, PACKAGE_STACKUP, PACKAGE_XTALK_DB = _load_presets()


def eps_eff_microstrip(eps_r: float, w_um: float, h_um: float) -> float:
    """Hammerstad's effective permittivity of a microstrip of width w over
    height h -- the one speed the channel delay and the crosstalk estimate share."""
    return 0.5 * (eps_r + 1.0) + 0.5 * (eps_r - 1.0) / math.sqrt(1.0 + 12.0 * h_um / w_um)


@dataclass(frozen=True)
class PackageConfig:
    """Which package the link is built on. Selects the RLGC preset and the
    spec-survey rows (reach, bump pitch, module width)."""

    kind: Literal["standard", "advanced"] = "standard"

    def __post_init__(self):
        _require_in(self.kind, set(PACKAGE_RLGC), "package.kind")


@dataclass(frozen=True)
class ChannelConfig:
    """The lane's channel: an analytic lossy transmission line (length,
    dielectric and skin loss) or a Touchstone file through the vendored
    Halo_Serdes reader. Terminations are single-ended equivalents."""

    kind: Literal["analytic", "touchstone"] = "analytic"
    length_mm: float = 10.0            # analytic line length
    file: Optional[str] = None         # Touchstone path (s2p/s4p/...), kind == touchstone
    lane: int = 0                      # lane index inside an 8/12-port file
    renumber: bool = True              # auto-detect 1<->3 port ordering (PyBERT)
    zs_ohm: float = 50.0               # source termination
    zl_ohm: float = 50.0               # receiver termination
    n_freq: int = 2048                 # points on the uniform DC-inclusive grid
    # analytic RLGC, None -> PACKAGE_RLGC[package.kind] (source: model); L and
    # C default to the values z0_ohm and the stack-up's eps_eff imply
    rdc_ohm_m: Optional[float] = None
    r_skin: Optional[float] = None     # R(f) = rdc + r_skin sqrt(f)  [ohm/(m sqrt(Hz))]
    l_h_m: Optional[float] = None      # explicit L overrides the geometry
    c_f_m: Optional[float] = None      # explicit C overrides the geometry
    loss_tangent: Optional[float] = None
    g_s_m: Optional[float] = None
    z0_ohm: Optional[float] = None     # characteristic impedance the geometry is fitted to; None -> preset
    # lane-to-lane crosstalk (needs lanes.count > 1 to do anything)
    #   fext    : behavioural level, xtalk_adjacent_db / xtalk_second_db (None -> package preset)
    #   coupled : the level estimated from the routing geometry below (coupled microstrip, first order)
    xtalk: Literal["none", "fext", "coupled"] = "none"
    xtalk_adjacent_db: Optional[float] = None   # |X/H| at Nyquist, nearest neighbour; None -> package preset
    xtalk_second_db: Optional[float] = None     # second neighbour; None -> adjacent - 12 dB
    trace_pitch_um: Optional[float] = None      # centre-to-centre lane pitch; None -> the package's bump pitch (survey)
    trace_width_um: Optional[float] = None      # None -> PACKAGE_STACKUP (source: model)
    dielectric_height_um: Optional[float] = None
    eps_r: Optional[float] = None
    coupled_length_mm: Optional[float] = None   # length the coupled estimate integrates over; None -> length_mm
                                                # (required with a Touchstone channel, which has no length_mm)

    def __post_init__(self):
        _require_in(self.kind, {"analytic", "touchstone"}, "channel.kind")
        _require_in(self.xtalk, {"none", "fext", "coupled"}, "channel.xtalk")
        for name in ("xtalk_adjacent_db", "xtalk_second_db"):
            v = getattr(self, name)
            if v is not None:
                _require(math.isfinite(v) and v < 0.0, f"channel.{name} must be a negative dB figure, got {v!r}")
        for name in ("trace_pitch_um", "trace_width_um", "dielectric_height_um", "z0_ohm", "coupled_length_mm"):
            v = getattr(self, name)
            if v is not None:
                _finite_pos(v, f"channel.{name}")
        if self.xtalk == "coupled" and self.kind == "touchstone":
            _require(self.coupled_length_mm is not None,
                     "channel.xtalk 'coupled' with a Touchstone channel needs channel.coupled_length_mm: "
                     "the file carries no routed length for the estimate to integrate over")
        if self.eps_r is not None:
            _require(math.isfinite(self.eps_r) and self.eps_r >= 1.0, f"channel.eps_r must be >= 1, got {self.eps_r!r}")
        _finite_nonneg(self.length_mm, "channel.length_mm")
        _require(self.n_freq >= 16, f"channel.n_freq must be >= 16, got {self.n_freq}")
        _finite_pos(self.zs_ohm, "channel.zs_ohm")
        _finite_pos(self.zl_ohm, "channel.zl_ohm")
        _require(self.lane >= 0, f"channel.lane must be >= 0, got {self.lane}")
        if self.kind == "touchstone":
            _require(bool(self.file), "channel.kind is 'touchstone' but channel.file is unset")
        for name in ("rdc_ohm_m", "r_skin", "l_h_m", "c_f_m", "loss_tangent", "g_s_m"):
            v = getattr(self, name)
            if v is not None:
                _finite_nonneg(v, f"channel.{name}")


# ---------------------------------------------------------------------------
# lanes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LaneConfig:
    """The lanes of one module and how they are repaired (invariant #4).

    ``count`` data lanes share one forwarded clock. ``skew_ps`` gives each
    physical lane's static skew against the clock (padded with zeros; or drawn with
    ``skew_sigma_ps`` and ``skew_seed`` when empty). The receiver's per-lane
    deskew removes what it can resolve: the residual is the skew modulo
    ``deskew_step_ps`` (0 = perfect deskew).

    Repair: ``failed`` names physical lanes that do not work (open bump,
    short). ``repair`` is how the module copes -- ``spare`` remaps logical
    lanes onto ``spare_count`` extra physical lanes, ``width_degrade`` keeps
    the largest working power-of-two width, ``none`` reports the failure.
    A single lane is simply ``count = 1``.
    """

    count: int = 1
    skew_ps: tuple[float, ...] = ()
    skew_sigma_ps: float = 0.0
    skew_seed: int = 0
    deskew_step_ps: float = 0.0
    spare_count: int = 0
    failed: tuple[int, ...] = ()
    repair: Literal["none", "spare", "width_degrade"] = "none"

    def __post_init__(self):
        _require(self.count >= 1, f"lanes.count must be >= 1, got {self.count}")
        n_phys = self.count + self.spare_count
        _require(len(self.skew_ps) <= n_phys,
                 f"lanes.skew_ps has {len(self.skew_ps)} entries for {n_phys} physical lanes")
        _finite_nonneg(self.skew_sigma_ps, "lanes.skew_sigma_ps")
        _finite_nonneg(self.deskew_step_ps, "lanes.deskew_step_ps")
        _require(self.spare_count >= 0, f"lanes.spare_count must be >= 0, got {self.spare_count}")
        _require_in(self.repair, {"none", "spare", "width_degrade"}, "lanes.repair")
        for i in self.failed:
            _require(0 <= i < n_phys, f"lanes.failed names lane {i}, module has {n_phys} physical lanes")
        _require(len(set(self.failed)) == len(self.failed), "lanes.failed repeats a lane")
        if self.repair == "spare":
            _require(self.spare_count >= 1, "lanes.repair 'spare' needs lanes.spare_count >= 1")

    @property
    def physical_count(self) -> int:
        return self.count + self.spare_count


# ---------------------------------------------------------------------------
# clocking (invariant #2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClockingConfig:
    """The forwarded clock and what the receiver does with it.

    One PLL on the transmit die makes the clock the data is launched on *and*
    the clock that is forwarded; its phase noise is common to both
    (``correlation`` = 1). The receiver samples data with the forwarded clock
    after its distribution tree (``tree_delay_ps``, ``tree_bw_hz``) and a
    per-lane phase tracker of bandwidth ``track_bw_hz`` that follows the slow
    part of the data-to-clock difference. An optional local PLL
    (``local_pll_*``) sits between the pads and the tree and is *locked to
    the forwarded clock*: its loop passes the forwarded phase below its
    bandwidth and its own noise above. There is no field for a free-running
    receive clock on purpose.

    ``pll_profile`` is a pll_simulator clock phase-noise profile (YAML; see
    docs/clock_profile.md). Timing is phase / (2 pi f0) with the file's
    carrier, whatever the forwarded clock's own rate is (a divider keeps
    the seconds). ``pll_rj_s`` adds a white part to the common PLL phase.
    The ``*_rj_s`` path terms are the independent white jitters the data
    path, the clock path and the receiver tree add on top.
    """

    scheme: Literal["forwarded_ddr"] = "forwarded_ddr"
    pll_profile: Optional[str] = None     # clock profile file; None -> white PLL (pll_rj_s only)
    pll_f0_hz: Optional[float] = None     # carrier override for the profile's phase scale
    pll_shift_db: float = 0.0             # uniform dB shift of the profile (same shape, other RMS)
    pll_rj_s: float = 0.0                 # white part of the common PLL jitter [s RMS per edge]
    correlation: float = 1.0              # share of PLL phase common to data and clock paths
    data_path_rj_s: float = 0.0           # Tx serializer / driver jitter, data path only [s RMS]
    clock_path_rj_s: float = 0.0          # Tx clock driver jitter, forwarded clock only [s RMS]
    tree_delay_ps: float = 0.0            # Rx clock distribution delay
    tree_bw_hz: Optional[float] = None    # Rx clock tree bandwidth (first order on phase); None = flat
    tree_rj_s: float = 0.0                # jitter the Rx tree adds [s RMS]
    track_bw_hz: Optional[float] = None   # per-lane phase tracker bandwidth; None = no tracker
    track_delay_ui: int = 0               # tracker loop latency [UI]; 0 = the zero-latency abstraction
    pi_step_ui: float = 0.0               # phase-interpolator step the tracker's output is quantised to [UI]
    dcd_ui: float = 0.0                   # receiver-side DDR duty-cycle error: odd/even sampling offset [UI]
    tx_dcd_ui: float = 0.0                # Tx PLL duty-cycle error, common to data and forwarded clock [UI]:
                                          # cancels at a receiver that samples on the forwarded clock's own
                                          # edges, shows in full once a local PLL regenerates a 50 % clock
    # receiver local PLL, locked to the forwarded clock (never free-running):
    # output phase = H_loop * forwarded + (1 - H_loop) * own noise
    local_pll_profile: Optional[str] = None   # its phase-noise profile; None and local_pll_rj_s = 0 -> no local PLL
    local_pll_f0_hz: Optional[float] = None
    local_pll_shift_db: float = 0.0
    local_pll_rj_s: float = 0.0               # white part of the local PLL's own jitter [s RMS]
    local_pll_fn_hz: Optional[float] = None   # loop natural frequency f_n = omega_n / 2 pi; required with a
                                              # local PLL (the -3 dB bandwidth is 2.48 f_n at zeta = 1;
                                              # ForwardedClock.local_pll_bw_3db_hz reports it)
    local_pll_damping: float = 1.0            # type-II second-order loop damping zeta
    # low-frequency wander the two paths pick up separately (supply, thermal):
    # first-order shaped noise of the given RMS with corner wander_corner_hz,
    # the RMS taken over [wander_floor_hz, edge rate / 2]; None -> the lowest
    # frequency the synthesis block can represent, 1 / (sim.jitter_block UI)
    data_path_wander_s: float = 0.0
    clock_path_wander_s: float = 0.0
    wander_corner_hz: float = 1.0e6
    wander_floor_hz: Optional[float] = None

    @property
    def has_local_pll(self) -> bool:
        return self.local_pll_profile is not None or self.local_pll_rj_s > 0.0

    @property
    def sampling_dcd_ui(self) -> float:
        """The odd/even sampling offset the sampler sees: the receiver's own
        duty-cycle error, plus the Tx PLL's once a local PLL has regenerated
        the clock and so stopped the forwarded edges from carrying it along."""
        return self.dcd_ui + (self.tx_dcd_ui if self.has_local_pll else 0.0)

    def __post_init__(self):
        _require_in(self.scheme, {"forwarded_ddr"}, "clocking.scheme")
        _require(self.track_delay_ui >= 0, f"clocking.track_delay_ui must be >= 0, got {self.track_delay_ui}")
        _finite_nonneg(self.pi_step_ui, "clocking.pi_step_ui")
        _require(self.pi_step_ui < 0.5, f"clocking.pi_step_ui must be < 0.5 UI, got {self.pi_step_ui}")
        for name in ("local_pll_rj_s", "data_path_wander_s", "clock_path_wander_s"):
            _finite_nonneg(getattr(self, name), f"clocking.{name}")
        _finite_pos(self.wander_corner_hz, "clocking.wander_corner_hz")
        _require(math.isfinite(self.local_pll_shift_db), "clocking.local_pll_shift_db must be finite")
        _finite_pos(self.local_pll_damping, "clocking.local_pll_damping")
        if self.local_pll_f0_hz is not None:
            _finite_pos(self.local_pll_f0_hz, "clocking.local_pll_f0_hz")
        if self.local_pll_fn_hz is not None:
            _finite_pos(self.local_pll_fn_hz, "clocking.local_pll_fn_hz")
        if self.wander_floor_hz is not None:
            _finite_pos(self.wander_floor_hz, "clocking.wander_floor_hz")
        if self.has_local_pll:
            _require(self.local_pll_fn_hz is not None,
                     "clocking.local_pll_fn_hz is required with a local PLL: it is locked to the "
                     "forwarded clock, never free-running (invariant #2)")
        _require(0.0 <= self.correlation <= 1.0,
                 f"clocking.correlation must be in [0, 1], got {self.correlation!r}")
        for name in ("pll_rj_s", "data_path_rj_s", "clock_path_rj_s", "tree_rj_s",
                     "tree_delay_ps", "dcd_ui", "tx_dcd_ui"):
            _finite_nonneg(getattr(self, name), f"clocking.{name}")
        _require(math.isfinite(self.pll_shift_db), "clocking.pll_shift_db must be finite")
        if self.pll_f0_hz is not None:
            _finite_pos(self.pll_f0_hz, "clocking.pll_f0_hz")
        if self.tree_bw_hz is not None:
            _finite_pos(self.tree_bw_hz, "clocking.tree_bw_hz")
        if self.track_bw_hz is not None:
            _require(self.track_bw_hz > 0.0 and not math.isnan(self.track_bw_hz),
                     f"clocking.track_bw_hz must be > 0 (inf allowed) or null, got {self.track_bw_hz!r}")
        _require(self.dcd_ui < 0.5, f"clocking.dcd_ui must be < 0.5 UI, got {self.dcd_ui}")


# ---------------------------------------------------------------------------
# tx / rx
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TxConfig:
    swing_vpp: float = 0.4          # launched swing into a matched load [V pp]
    bw_hz: Optional[float] = None   # driver first-order bandwidth; None = twice the Nyquist frequency
                                    # (the data rate in Hz); inf = ideal brick-wall edges (rings at the
                                    # band edge: a short, clean line then reads an eye wider than 1 UI)

    def __post_init__(self):
        _finite_pos(self.swing_vpp, "tx.swing_vpp")
        if self.bw_hz is not None:
            _require(self.bw_hz > 0.0 and not math.isnan(self.bw_hz),
                     f"tx.bw_hz must be > 0 (inf allowed) or null, got {self.bw_hz!r}")


@dataclass(frozen=True)
class CtleConfig:
    """Optional single-stage behavioural CTLE: one zero, two poles, DC gain 0 dB.
    ``peak_db`` is the zero-to-first-pole separation (the asymptotic boost);
    the zero sits that far below ``fp1_hz`` (default the Nyquist frequency),
    the second pole at ``fp2_hz`` (default 2x fp1), so the boost actually
    reached at fp1 is a few dB less than ``peak_db``."""

    enable: bool = False
    peak_db: float = 3.0
    fp1_hz: Optional[float] = None
    fp2_hz: Optional[float] = None

    def __post_init__(self):
        _require(math.isfinite(self.peak_db) and self.peak_db >= 0.0,
                 f"rx.ctle.peak_db must be >= 0, got {self.peak_db!r}")
        for name in ("fp1_hz", "fp2_hz"):
            v = getattr(self, name)
            if v is not None:
                _finite_pos(v, f"rx.ctle.{name}")


@dataclass(frozen=True)
class RxConfig:
    noise_rms_v: float = 2.0e-3            # input-referred noise at the sampler [V RMS]
    ctle: CtleConfig = field(default_factory=CtleConfig)
    sampling_phase_ui: Optional[float] = None   # None = the bathtub minimum (eye-centred tracker)
    vref_offset_v: float = 0.0             # decision threshold offset from mid-swing

    def __post_init__(self):
        _finite_nonneg(self.noise_rms_v, "rx.noise_rms_v")
        _require(math.isfinite(self.vref_offset_v), "rx.vref_offset_v must be finite")
        if self.sampling_phase_ui is not None:
            _require(-0.5 <= self.sampling_phase_ui <= 0.5,
                     f"rx.sampling_phase_ui must be in [-0.5, 0.5], got {self.sampling_phase_ui}")


# ---------------------------------------------------------------------------
# simulation and targets
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SimConfig:
    osr: int = 32                      # samples per UI on the waveform grid
    n_symbols: int = 200_000           # time engine, per lane
    seed: int = 1
    pattern: Literal["prbs15", "prbs31", "random"] = "prbs31"
    chunk_symbols: int = 65_536        # time engine block size
    jitter_block: int = 1 << 18        # edges per phase-noise synthesis block (sets the band's low edge)
    stat_isi_bin_v: float = 5.0e-5     # voltage bin of the exact ISI distribution [V]
    stat_phase_points: int = 64        # bathtub phases per UI
    stat_jitter_sigmas: float = 12.0   # jitter quadrature reach [sigma]; 1e-27 needs 10.8
    engine: Literal["statistical", "time", "both"] = "statistical"

    def __post_init__(self):
        _require(self.osr >= 4, f"sim.osr must be >= 4, got {self.osr}")
        _require(self.n_symbols >= 64, f"sim.n_symbols must be >= 64, got {self.n_symbols}")
        _require(self.chunk_symbols >= 64, f"sim.chunk_symbols must be >= 64, got {self.chunk_symbols}")
        _require(self.jitter_block >= 64 and self.jitter_block & (self.jitter_block - 1) == 0,
                 f"sim.jitter_block must be a power of two >= 64, got {self.jitter_block}")
        _finite_pos(self.stat_isi_bin_v, "sim.stat_isi_bin_v")
        _require(self.stat_phase_points >= 8, "sim.stat_phase_points must be >= 8")
        _require(math.isfinite(self.stat_jitter_sigmas) and self.stat_jitter_sigmas >= 1.0,
                 "sim.stat_jitter_sigmas must be >= 1")
        _require_in(self.pattern, {"prbs15", "prbs31", "random"}, "sim.pattern")
        _require_in(self.engine, {"statistical", "time", "both"}, "sim.engine")


@dataclass(frozen=True)
class TargetConfig:
    """What the link is judged against. ``None`` takes the survey table's value
    for this package and rate (``d2d_link.spec``); a set value overrides it
    and is then the config's own claim, not the specification's."""

    ber: Optional[float] = None            # raw BER target, no FEC
    eye_height_mv: Optional[float] = None  # receiver eye-height target at that BER
    eye_width_ui: Optional[float] = None   # receiver eye-width target at that BER

    def __post_init__(self):
        if self.ber is not None:
            _require(0.0 < self.ber < 1.0, f"target.ber must be in (0, 1), got {self.ber!r}")
        for name in ("eye_height_mv", "eye_width_ui"):
            v = getattr(self, name)
            if v is not None:
                _finite_nonneg(v, f"target.{name}")


# ---------------------------------------------------------------------------
# the link
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LinkConfig:
    data_rate_gtps: float = 32.0
    package: PackageConfig = field(default_factory=PackageConfig)
    channel: ChannelConfig = field(default_factory=ChannelConfig)
    lanes: LaneConfig = field(default_factory=LaneConfig)
    clocking: ClockingConfig = field(default_factory=ClockingConfig)
    tx: TxConfig = field(default_factory=TxConfig)
    rx: RxConfig = field(default_factory=RxConfig)
    sim: SimConfig = field(default_factory=SimConfig)
    target: TargetConfig = field(default_factory=TargetConfig)

    def __post_init__(self):
        _finite_pos(self.data_rate_gtps, "data_rate_gtps")

    # -- derived ------------------------------------------------------------
    @property
    def symbol_rate(self) -> float:
        """Symbols per second (NRZ: one bit per UI)."""
        return self.data_rate_gtps * 1e9

    @property
    def ui(self) -> float:
        return 1.0 / self.symbol_rate

    @property
    def dt(self) -> float:
        return self.ui / self.sim.osr

    @property
    def f_nyquist(self) -> float:
        return 0.5 * self.symbol_rate

    @property
    def forwarded_clock_hz(self) -> float:
        """The forwarded clock's frequency: DDR, so half the data rate."""
        return 0.5 * self.symbol_rate

    def xtalk_db(self) -> tuple[float, float]:
        """(nearest, second neighbour) far-end crosstalk at Nyquist [dB]: the
        configured / preset levels for ``xtalk: fext``, the coupled-line
        estimate (``channel.coupled.fext_db``) for ``xtalk: coupled``."""
        if self.channel.xtalk == "coupled":
            from ..channel.coupled import fext_db

            return fext_db(self)
        adj = self.channel.xtalk_adjacent_db
        adj = PACKAGE_XTALK_DB[self.package.kind] if adj is None else adj
        sec = self.channel.xtalk_second_db
        return adj, (adj - 12.0 if sec is None else sec)

    @property
    def tx_bw_hz(self) -> float:
        """The driver bandwidth the engines use: ``tx.bw_hz``, or twice the
        Nyquist frequency when the config leaves it unset."""
        return self.tx.bw_hz if self.tx.bw_hz is not None else self.symbol_rate

    def stackup(self) -> dict[str, float]:
        """Trace width, dielectric height and eps_r: explicit fields over the
        package preset (source: model), plus the Hammerstad ``eps_eff``."""
        preset = PACKAGE_STACKUP[self.package.kind]
        st = {k: (getattr(self.channel, k) if getattr(self.channel, k) is not None else v)
              for k, v in preset.items()}
        st["eps_eff"] = eps_eff_microstrip(st["eps_r"], st["trace_width_um"], st["dielectric_height_um"])
        return st

    def rlgc(self) -> dict[str, float]:
        """The analytic line's RLGC: explicit channel fields over the package
        preset for R and the losses; L and C from ``z0_ohm`` and the
        stack-up's ``eps_eff`` (L = Z0 sqrt(eps_eff) / c, C = sqrt(eps_eff) /
        (Z0 c)) unless given explicitly. ``eps_eff`` and ``z0_ohm`` ride along."""
        preset = PACKAGE_RLGC[self.package.kind]
        out = {k: (getattr(self.channel, k) if getattr(self.channel, k) is not None else v)
               for k, v in preset.items()}
        eps_eff = self.stackup()["eps_eff"]
        z0 = out["z0_ohm"]
        n = math.sqrt(eps_eff)
        out["l_h_m"] = self.channel.l_h_m if self.channel.l_h_m is not None else z0 * n / C0
        out["c_f_m"] = self.channel.c_f_m if self.channel.c_f_m is not None else n / (z0 * C0)
        out["eps_eff"] = eps_eff
        return out

    def coupled_length_mm(self) -> float:
        """The length the coupled-line crosstalk estimate integrates over."""
        c = self.channel
        return c.coupled_length_mm if c.coupled_length_mm is not None else c.length_mm
