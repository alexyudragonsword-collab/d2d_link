"""Form-field declarations for a future GUI (Halo_Serdes ``config_bridge.SECTIONS`` method).

No GUI ships in this milestone. What ships is the declaration a GUI would be
generated from: every ``LinkConfig`` field, by dotted path, with a label, a
kind and (where the config stores SI units) a display scale. A test keeps
``SECTIONS`` and the schema's field inventory identical in both directions, so
a new config field cannot appear without its form row and a form row cannot
outlive its field. The GUI, when it comes, reads the config through this and
adds no simulation logic (invariant #1).
"""

from __future__ import annotations

import dataclasses
import typing

from . import schema
from .schema import LinkConfig


def _f(path: str, label: str, kind: str, **kw) -> dict:
    """One form field: dotted path, label, kind (bool | enum | float | int |
    opt_float | opt_int | opt_str | tuple_float | tuple_int), plus
    ``options`` for enums and ``scale`` for display units."""
    d = {"path": path, "label": label, "kind": kind}
    d.update(kw)
    return d


SECTIONS: list[tuple[str, str, list[dict]]] = [
    ("link", "Link", [
        _f("data_rate_gtps", "Data rate [GT/s]", "float"),
        _f("package.kind", "Package", "enum", options=["standard", "advanced"]),
    ]),
    ("channel", "Channel", [
        _f("channel.kind", "Kind", "enum", options=["analytic", "touchstone"]),
        _f("channel.length_mm", "Length [mm] (analytic)", "float"),
        _f("channel.file", "Touchstone file", "opt_str"),
        _f("channel.lane", "Lane (8/12-port file)", "int"),
        _f("channel.renumber", "Auto port renumber", "bool"),
        _f("channel.zs_ohm", "Source term [ohm]", "float"),
        _f("channel.zl_ohm", "Receiver term [ohm]", "float"),
        _f("channel.n_freq", "Freq grid points", "int"),
        _f("channel.rdc_ohm_m", "R_dc [ohm/m] (empty = package preset, source: model)", "opt_float"),
        _f("channel.r_skin", "R_skin [ohm/(m sqrt(Hz))]", "opt_float"),
        _f("channel.l_h_m", "L [H/m] (empty = from Z0 and stack-up)", "opt_float"),
        _f("channel.c_f_m", "C [F/m] (empty = from Z0 and stack-up)", "opt_float"),
        _f("channel.loss_tangent", "Loss tangent", "opt_float"),
        _f("channel.g_s_m", "G [S/m]", "opt_float"),
        _f("channel.z0_ohm", "Z0 [ohm] (empty = package preset, source: model)", "opt_float"),
        _f("channel.xtalk", "Lane crosstalk", "enum", options=["none", "fext", "coupled"]),
        _f("channel.xtalk_adjacent_db", "FEXT nearest lane @Nyquist [dB] (empty = package preset)", "opt_float"),
        _f("channel.xtalk_second_db", "FEXT second lane @Nyquist [dB] (empty = -12 dB)", "opt_float"),
        _f("channel.trace_pitch_um", "Trace pitch [um] (empty = bump pitch, survey)", "opt_float"),
        _f("channel.trace_width_um", "Trace width [um] (empty = package preset)", "opt_float"),
        _f("channel.dielectric_height_um", "Dielectric height [um] (empty = package preset)", "opt_float"),
        _f("channel.eps_r", "Dielectric eps_r (empty = package preset)", "opt_float"),
        _f("channel.coupled_length_mm", "Coupled length [mm] (empty = length; needed with Touchstone)", "opt_float"),
    ]),
    ("lanes", "Lanes and repair", [
        _f("lanes.count", "Data lanes", "int"),
        _f("lanes.skew_ps", "Lane skew [ps] (per lane)", "tuple_float"),
        _f("lanes.skew_sigma_ps", "Random skew sigma [ps]", "float"),
        _f("lanes.skew_seed", "Skew seed", "int"),
        _f("lanes.deskew_step_ps", "Deskew step [ps] (0 = perfect)", "float"),
        _f("lanes.spare_count", "Spare lanes", "int"),
        _f("lanes.failed", "Failed physical lanes", "tuple_int"),
        _f("lanes.repair", "Repair", "enum", options=["none", "spare", "width_degrade"]),
    ]),
    ("clocking", "Forwarded clock", [
        _f("clocking.scheme", "Scheme", "enum", options=["forwarded_ddr"]),
        _f("clocking.pll_profile", "Tx PLL phase-noise profile", "opt_str"),
        _f("clocking.pll_f0_hz", "Profile carrier override [GHz]", "opt_float", scale=1e9),
        _f("clocking.pll_shift_db", "Profile shift [dB]", "float"),
        _f("clocking.pll_rj_s", "PLL white RJ [fs]", "float", scale=1e-15),
        _f("clocking.correlation", "Data/clock PLL correlation", "float"),
        _f("clocking.data_path_rj_s", "Data path RJ [fs]", "float", scale=1e-15),
        _f("clocking.clock_path_rj_s", "Clock path RJ [fs]", "float", scale=1e-15),
        _f("clocking.tree_delay_ps", "Rx tree delay [ps]", "float"),
        _f("clocking.tree_bw_hz", "Rx tree bandwidth [GHz]", "opt_float", scale=1e9),
        _f("clocking.tree_rj_s", "Rx tree RJ [fs]", "float", scale=1e-15),
        _f("clocking.track_bw_hz", "Phase tracker bandwidth [MHz]", "opt_float", scale=1e6),
        _f("clocking.track_delay_ui", "Tracker loop latency [UI]", "int"),
        _f("clocking.pi_step_ui", "Phase interpolator step [UI]", "float"),
        _f("clocking.dcd_ui", "Rx DDR duty-cycle error [UI]", "float"),
        _f("clocking.tx_dcd_ui", "Tx PLL duty-cycle error [UI] (common mode; shows with a local PLL)", "float"),
        _f("clocking.local_pll_profile", "Rx local PLL profile (locked to forwarded clock)", "opt_str"),
        _f("clocking.local_pll_f0_hz", "Local PLL carrier override [GHz]", "opt_float", scale=1e9),
        _f("clocking.local_pll_shift_db", "Local PLL profile shift [dB]", "float"),
        _f("clocking.local_pll_rj_s", "Local PLL white RJ [fs]", "float", scale=1e-15),
        _f("clocking.local_pll_fn_hz", "Local PLL loop natural frequency [MHz]", "opt_float", scale=1e6),
        _f("clocking.local_pll_damping", "Local PLL damping", "float"),
        _f("clocking.data_path_wander_s", "Data path wander [fs]", "float", scale=1e-15),
        _f("clocking.clock_path_wander_s", "Clock path wander [fs]", "float", scale=1e-15),
        _f("clocking.wander_corner_hz", "Wander corner [MHz]", "float", scale=1e6),
        _f("clocking.wander_floor_hz", "Wander RMS band floor [kHz] (empty = 1 / block)", "opt_float", scale=1e3),
    ]),
    ("tx", "Transmitter", [
        _f("tx.swing_vpp", "Swing [V pp]", "float"),
        _f("tx.bw_hz", "Driver bandwidth [GHz] (empty = 2x Nyquist)", "opt_float", scale=1e9),
    ]),
    ("rx", "Receiver", [
        _f("rx.noise_rms_v", "Sampler noise [mV RMS]", "float", scale=1e-3),
        _f("rx.ctle.enable", "CTLE", "bool"),
        _f("rx.ctle.peak_db", "CTLE peaking [dB]", "float"),
        _f("rx.ctle.fp1_hz", "CTLE pole 1 [GHz] (empty = Nyquist)", "opt_float", scale=1e9),
        _f("rx.ctle.fp2_hz", "CTLE pole 2 [GHz] (empty = 2x Nyquist)", "opt_float", scale=1e9),
        _f("rx.sampling_phase_ui", "Sampling phase [UI] (empty = eye centre)", "opt_float"),
        _f("rx.vref_offset_v", "Vref offset [mV]", "float", scale=1e-3),
    ]),
    ("sim", "Simulation", [
        _f("sim.osr", "Samples per UI", "int"),
        _f("sim.n_symbols", "Symbols per lane (time engine)", "int"),
        _f("sim.seed", "Seed", "int"),
        _f("sim.pattern", "Pattern", "enum", options=["prbs15", "prbs31", "random"]),
        _f("sim.chunk_symbols", "Time-engine block [symbols]", "int"),
        _f("sim.jitter_block", "Jitter synthesis block [edges]", "int"),
        _f("sim.stat_isi_bin_v", "ISI distribution bin [uV]", "float", scale=1e-6),
        _f("sim.stat_phase_points", "Bathtub phases per UI", "int"),
        _f("sim.stat_jitter_sigmas", "Jitter quadrature reach [sigma]", "float"),
        _f("sim.engine", "Engine", "enum", options=["statistical", "time", "both"]),
        _f("sim.time_mode", "Time engine mode", "enum", options=["waveform", "samples"]),
        _f("sim.time_cursor_floor", "Samples mode: cursor floor [fraction of main]", "float"),
    ]),
    ("target", "Targets (empty = survey table)", [
        _f("target.ber", "BER target", "opt_float"),
        _f("target.eye_height_mv", "Eye height target [mV]", "opt_float"),
        _f("target.eye_width_ui", "Eye width target [UI]", "opt_float"),
    ]),
]

FIELDS: dict[str, dict] = {fld["path"]: fld for _, _, flds in SECTIONS for fld in flds}


def schema_paths(cls: type = LinkConfig, prefix: str = "") -> list[str]:
    """Every leaf field of the config as a dotted path (what SECTIONS must cover)."""
    out = []
    hints = typing.get_type_hints(cls)
    for f in dataclasses.fields(cls):
        tp = hints[f.name]
        if typing.get_origin(tp) is typing.Union:
            args = [a for a in typing.get_args(tp) if a is not type(None)]
            tp = args[0] if len(args) == 1 else tp
        if dataclasses.is_dataclass(tp):
            out.extend(schema_paths(tp, prefix + f.name + "."))
        else:
            out.append(prefix + f.name)
    return out


def config_to_values(cfg: LinkConfig) -> dict[str, object]:
    """Flat ``{path: display value}`` for populating a form (scale applied)."""
    out = {}
    for path, fld in FIELDS.items():
        v = cfg
        for part in path.split("."):
            v = getattr(v, part)
        scale = fld.get("scale")
        if scale and v is not None:
            v = v / scale
        out[path] = v
    return out


def values_to_overrides(values: dict[str, object]) -> dict[str, object]:
    """Form values back to config overrides (scale undone, blanks -> None)."""
    out = {}
    for path, v in values.items():
        fld = FIELDS[path]
        if v in ("", None):
            out[path] = None
            continue
        scale = fld.get("scale")
        if fld["kind"] in ("float", "opt_float"):
            v = float(v) * (scale or 1.0)
        elif fld["kind"] in ("int", "opt_int"):
            v = int(v)
        elif fld["kind"] in ("tuple_float", "tuple_int"):
            if isinstance(v, str):
                v = [x for x in v.replace(",", " ").split() if x]
            conv = float if fld["kind"] == "tuple_float" else int
            v = tuple(conv(x) for x in v)
        out[path] = v
    return out


__all__ = ["SECTIONS", "FIELDS", "schema_paths", "config_to_values", "values_to_overrides", "schema"]
