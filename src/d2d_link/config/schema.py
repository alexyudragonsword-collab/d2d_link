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

#: Per-package RLGC presets for the analytic lossy line, used where
#: ``ChannelConfig`` leaves a parameter ``None``. These are *model* numbers
#: (a 50 ohm organic-substrate microstrip for the standard package, a short
#: fine-pitch silicon-bridge / interposer line for the advanced one), not
#: specification values; the reach and pitch figures the packages are known
#: by live in data/spec/ucie_survey.yaml with their source tags.
PACKAGE_RLGC: dict[str, dict[str, float]] = {
    # ~1.1 dB/cm at 16 GHz (0.87 conductor + 0.27 dielectric), so 25 mm is
    # about 3 dB at the 32 GT/s Nyquist -- the order of magnitude surveys quote
    # for an organic package trace.
    "standard": dict(rdc_ohm_m=10.0, r_skin=8.0e-3, l_h_m=3.3e-7, c_f_m=1.33e-10,
                     loss_tangent=0.010, g_s_m=0.0),
    # narrow (2-3 um) RDL lines: high DC resistance, dielectric loss of an
    # oxide/polyimide stack, only ever a couple of millimetres long.
    "advanced": dict(rdc_ohm_m=2.0e3, r_skin=2.5e-2, l_h_m=4.0e-7, c_f_m=1.6e-10,
                     loss_tangent=0.004, g_s_m=0.0),
}


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
    # analytic RLGC, None -> PACKAGE_RLGC[package.kind]
    rdc_ohm_m: Optional[float] = None
    r_skin: Optional[float] = None     # R(f) = rdc + r_skin sqrt(f)  [ohm/(m sqrt(Hz))]
    l_h_m: Optional[float] = None
    c_f_m: Optional[float] = None
    loss_tangent: Optional[float] = None
    g_s_m: Optional[float] = None

    def __post_init__(self):
        _require_in(self.kind, {"analytic", "touchstone"}, "channel.kind")
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
    part of the data-to-clock difference. There is no field for an
    independent receive clock on purpose.

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
    dcd_ui: float = 0.0                   # DDR duty-cycle error: odd/even sampling offset [UI]

    def __post_init__(self):
        _require_in(self.scheme, {"forwarded_ddr"}, "clocking.scheme")
        _require(0.0 <= self.correlation <= 1.0,
                 f"clocking.correlation must be in [0, 1], got {self.correlation!r}")
        for name in ("pll_rj_s", "data_path_rj_s", "clock_path_rj_s", "tree_rj_s",
                     "tree_delay_ps", "dcd_ui"):
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
    bw_hz: Optional[float] = None   # driver first-order bandwidth; None = ideal

    def __post_init__(self):
        _finite_pos(self.swing_vpp, "tx.swing_vpp")
        if self.bw_hz is not None:
            _finite_pos(self.bw_hz, "tx.bw_hz")


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
    stat_enumerate_cursors: int = 12   # ISI cursors enumerated exactly; the rest become variance
    stat_phase_points: int = 64        # bathtub phases per UI
    stat_jitter_sigmas: float = 12.0   # jitter quadrature reach [sigma]; 1e-27 needs 10.8
    engine: Literal["statistical", "time", "both"] = "statistical"

    def __post_init__(self):
        _require(self.osr >= 4, f"sim.osr must be >= 4, got {self.osr}")
        _require(self.n_symbols >= 64, f"sim.n_symbols must be >= 64, got {self.n_symbols}")
        _require(self.chunk_symbols >= 64, f"sim.chunk_symbols must be >= 64, got {self.chunk_symbols}")
        _require(self.jitter_block >= 64 and self.jitter_block & (self.jitter_block - 1) == 0,
                 f"sim.jitter_block must be a power of two >= 64, got {self.jitter_block}")
        _require(0 <= self.stat_enumerate_cursors <= 20,
                 f"sim.stat_enumerate_cursors must be in [0, 20], got {self.stat_enumerate_cursors}")
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

    def rlgc(self) -> dict[str, float]:
        """The analytic line's RLGC: explicit channel fields over the package preset."""
        preset = PACKAGE_RLGC[self.package.kind]
        return {k: (getattr(self.channel, k) if getattr(self.channel, k) is not None else v)
                for k, v in preset.items()}
