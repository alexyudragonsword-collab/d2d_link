"""Far-end crosstalk of two coupled lanes from the routing geometry.

A first-order coupled-microstrip estimate, not a field solver: it turns the
numbers a package is known by -- the bump pitch (survey table), the trace
width, the dielectric height and permittivity (``PACKAGE_STACKUP``) -- into
the far-end coupling level the behavioural ``fext`` mode otherwise takes as
a dB figure. Three ingredients (Johnson & Graham's rules of thumb for
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

from ..config.schema import LinkConfig
from ..spec import survey

C0 = 299_792_458.0


def trace_pitch_um(cfg: LinkConfig) -> tuple[float, str]:
    """The lane pitch [um] and where it came from: the config, or the
    package's bump pitch (midpoint of the survey range)."""
    if cfg.channel.trace_pitch_um is not None:
        return float(cfg.channel.trace_pitch_um), "config"
    row = survey("bump_pitch_um", cfg.package.kind)
    v = row.value
    pitch = 0.5 * (float(v[0]) + float(v[-1])) if isinstance(v, (list, tuple)) else float(v)
    return pitch, row.source


def eps_eff_microstrip(eps_r: float, w_um: float, h_um: float) -> float:
    """Hammerstad's effective permittivity of a microstrip of width w over height h."""
    return 0.5 * (eps_r + 1.0) + 0.5 * (eps_r - 1.0) / math.sqrt(1.0 + 12.0 * h_um / w_um)


def coupling_fraction(spacing_um: float, h_um: float) -> float:
    return 1.0 / (1.0 + (spacing_um / h_um) ** 2)


def fext_ratio_at(cfg: LinkConfig, spacing_um: float) -> float:
    """|X/H| at the Nyquist frequency for two lanes ``spacing_um`` apart."""
    st = cfg.stackup()
    eps_eff = eps_eff_microstrip(st["eps_r"], st["trace_width_um"], st["dielectric_height_um"])
    mismatch = max(1.0 - eps_eff / st["eps_r"], 0.0)
    v = C0 / math.sqrt(eps_eff)
    kappa = coupling_fraction(spacing_um, st["dielectric_height_um"])
    tau = kappa * mismatch * (cfg.channel.length_mm * 1e-3) / (2.0 * v)
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
    eps_eff = eps_eff_microstrip(st["eps_r"], st["trace_width_um"], st["dielectric_height_um"])
    adj, sec = fext_db(cfg)
    return {"pitch_um": pitch, "pitch_source": src, **st, "eps_eff": eps_eff,
            "kappa_adjacent": coupling_fraction(pitch, st["dielectric_height_um"]),
            "mismatch": 1.0 - eps_eff / st["eps_r"], "fext_adjacent_db": adj, "fext_second_db": sec}


__all__ = ["fext_db", "fext_ratio_at", "describe", "trace_pitch_um", "eps_eff_microstrip", "coupling_fraction"]
