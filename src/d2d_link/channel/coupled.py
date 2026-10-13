"""Far-end crosstalk of two coupled lanes from the routing geometry.

A first-order coupled-microstrip estimate, not a field solver: it turns the
numbers a package is known by -- the bump pitch (survey table), the trace
width, the dielectric height and permittivity (``PACKAGE_STACKUP``, source:
model) -- into the far-end coupling level the behavioural ``fext`` mode
otherwise takes as a dB figure. The effective permittivity is the same
Hammerstad value the channel's own L and C are derived from
(``LinkConfig.rlgc``), so the data and the crosstalk travel at one speed. The
coupled length is ``channel.coupled_length_mm`` when given (mandatory with a
Touchstone channel), else the analytic line's ``length_mm``. Three ingredients (Johnson & Graham's rules of thumb for
coupled traces, Hammerstad's microstrip effective permittivity):

* the coupling fraction between two traces at centre spacing ``s`` over a
  dielectric of height ``h`` falls as ``kappa = 1 / (1 + (s/h)^2)``;
* far-end crosstalk needs the even and odd modes to travel at different
  speeds, which they do only in an inhomogeneous dielectric: the velocity
  mismatch is taken as ``(1 - eps_eff / eps_r)`` with the microstrip
  ``eps_eff`` -- a stripline (homogeneous) couples no FEXT at this order;
* the coupled voltage grows with the coupled length over the rise time:
  ``X/H = j 2 pi f * tau``, ``tau = kappa (1 - eps_eff/eps_r) length / (2 v)``,
  evaluated at the Nyquist frequency and capped at -3 dB (the behavioural
  shape saturates there anyway).

The second neighbour sits at twice the pitch. Both levels go through the
same ``k (jf/fn) / (1 + jf/fn)`` shape as the ``fext`` mode, so switching a
config from ``fext`` to ``coupled`` changes the level, not the model.
"""

from __future__ import annotations

import math

from ..config.schema import C0, LinkConfig, eps_eff_microstrip
from ..spec import survey


def trace_pitch_um(cfg: LinkConfig) -> tuple[float, str]:
    """The lane pitch [um] and where it came from: the config, or the
    package's bump pitch (midpoint of the survey range)."""
    if cfg.channel.trace_pitch_um is not None:
        return float(cfg.channel.trace_pitch_um), "config"
    row = survey("bump_pitch_um", cfg.package.kind)
    v = row.value
    pitch = 0.5 * (float(v[0]) + float(v[-1])) if isinstance(v, (list, tuple)) else float(v)
    return pitch, row.source


def coupling_fraction(spacing_um: float, h_um: float) -> float:
    return 1.0 / (1.0 + (spacing_um / h_um) ** 2)


def fext_ratio_at(cfg: LinkConfig, spacing_um: float) -> float:
    """|X/H| at the Nyquist frequency for two lanes ``spacing_um`` apart."""
    st = cfg.stackup()
    eps_eff = st["eps_eff"]
    mismatch = max(1.0 - eps_eff / st["eps_r"], 0.0)      # 0 for a stripline: no first-order FEXT
    v = C0 / math.sqrt(eps_eff)
    kappa = coupling_fraction(spacing_um, st["dielectric_height_um"])
    tau = kappa * mismatch * (cfg.coupled_length_mm() * 1e-3) / (2.0 * v)
    return min(2.0 * math.pi * cfg.f_nyquist * tau, 1.0 / math.sqrt(2.0))


def fext_db(cfg: LinkConfig) -> tuple[float, float]:
    """(nearest, second neighbour) far-end crosstalk at Nyquist [dB]."""
    pitch, _ = trace_pitch_um(cfg)
    out = []
    for n in (1, 2):
        r = fext_ratio_at(cfg, n * pitch)
        out.append(20.0 * math.log10(max(r, 1e-15)))
    return out[0], out[1]


def describe(cfg: LinkConfig) -> dict:
    """The numbers behind the estimate, for printing."""
    pitch, src = trace_pitch_um(cfg)
    st = cfg.stackup()
    eps_eff = st["eps_eff"]
    adj, sec = fext_db(cfg)
    ch = cfg.channel
    explicit = {k for k in ("trace_width_um", "dielectric_height_um", "eps_r") if getattr(ch, k) is not None}
    kb = cfg.next_ratio()
    return {"pitch_um": pitch, "pitch_source": src, **st,
            "stackup_source": "config" if explicit else "model",
            "coupled_length_mm": cfg.coupled_length_mm(), "coupled_delay_ps": 1e12 * cfg.coupled_delay_s(),
            "kappa_adjacent": coupling_fraction(pitch, st["dielectric_height_um"]),
            "mismatch": 1.0 - eps_eff / st["eps_r"], "fext_adjacent_db": adj, "fext_second_db": sec,
            "next_mode": cfg.channel.xtalk_next, "next_db": 20.0 * math.log10(kb) if kb > 0.0 else None}


__all__ = ["fext_db", "fext_ratio_at", "describe", "trace_pitch_um", "eps_eff_microstrip", "coupling_fraction"]
