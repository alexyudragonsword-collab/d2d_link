"""Export a pll_simulator preset as a clock profile whose grid reaches the
link's Nyquist frequency (16 GHz at 32 GT/s), not just the carrier's f0/2.

pll_simulator's exporter (``pllsim.export.clock_profile``) writes 100 Hz..f0/2.
That is the format's convention, and the exporter refuses to extrapolate. A
10.24 GHz PLL's file therefore stops at 5.12 GHz, while d2d_link's forwarded
clock integrates its common-mode leak to the edge rate's Nyquist fs/2.
``clocking.profile_above`` decides what lies in between: ``floor`` holds the
last level, ``zero`` drops it. The 0.13.0 verdict turned on that choice.

This tool asks the model instead of guessing. It analyses the preset on a
log-uniform grid from 100 Hz to ``--f-hi`` (60 points per decade, the
exporter's density) and writes the total L(f) and the analytic spurs in the
same format. The source line names the preset, the pllsim commit and this
tool. The file reads like any profile; above its last point, which is now
fs/2, nothing is integrated.

It needs a pll_simulator checkout (``--pllsim``) or an installed ``pllsim``.
CI has neither: it checks the files this tool wrote, not the tool. See
``tests/test_clock_profile.py::test_profile_to_nyquist_matches_the_floor_reading``.

    python tools/export_profile_to_nyquist.py --pllsim ../pll_simulator \\
        bench_markulic16_sspll_40m_10p24g bench_wu19_spll_frac_52m_6p253g
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "src" / "d2d_link" / "data" / "clock_profiles"


def export(preset: str, f_hi: float, out_dir: Path) -> Path:
    from pllsim import presets
    from pllsim.core.jitter import ldbc_from_sphi
    from pllsim.export.clock_profile import (F_LO_HZ, POINTS_PER_DECADE, _flow_list, _quoted, default_source,
                                             spur_entries, yaml_float)

    pll = getattr(presets, preset)()
    n = int(round(POINTS_PER_DECADE * math.log10(f_hi / F_LO_HZ))) + 1
    f = np.geomspace(F_LO_HZ, f_hi, n)
    ar = pll.analyze(f=f)
    l_dbc = ldbc_from_sphi(ar.pn_breakdown["total"])
    spurs = spur_entries(ar, pll.cfg.fref)
    base = default_source(preset)
    if "0+unknown" in base:                            # a checkout on sys.path, not an install: its pyproject knows
        import re

        import pllsim

        pp = Path(pllsim.__file__).resolve().parents[2] / "pyproject.toml"
        m = re.search(r'^version = "([^"]+)"', pp.read_text(encoding="utf-8"), re.M) if pp.exists() else None
        base = base.replace("0+unknown", m.group(1)) if m else base
    source = (f"{base}; grid 100 Hz..{f_hi / 1e9:g} GHz (the link's Nyquist, past f0/2) "
              "by d2d_link tools/export_profile_to_nyquist.py")
    lines = [
        "# pllsim clock phase-noise profile, grid extended to the link's Nyquist frequency",
        "# l_dbc_hz is the total L(f) = S_phi/2 of the linear model in dBc/Hz;",
        f"# timing is phase / (2 pi f0_hz).  Offsets are log-uniform, 100 Hz..{f_hi / 1e9:g} GHz.",
        f"f0_hz: {yaml_float(float(ar.f0))}",
        "f_hz: " + _flow_list([float(v) for v in f.tolist()]),
        "l_dbc_hz: " + _flow_list([float(v) for v in np.asarray(l_dbc).tolist()]),
    ]
    if spurs:
        lines.append("spurs:")
        lines += [f"  - {{f_hz: {yaml_float(fs)}, dbc: {yaml_float(d)}}}" for fs, d in spurs]
    else:
        lines.append("spurs: []")
    lines.append(f"source: {_quoted(source)}")
    out = out_dir / f"{preset}_to{f_hi / 1e9:g}g.yaml"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    terms = {k: float(ldbc_from_sphi(v)[-1]) for k, v in ar.pn_breakdown.items()}
    print(f"{out.name}: {f.size} points to {f_hi / 1e9:g} GHz; L at the top "
          + ", ".join(f"{k} {v:.2f}" for k, v in terms.items()) + " dBc/Hz")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("presets", nargs="+", help="pllsim preset names")
    ap.add_argument("--pllsim", type=Path, help="pll_simulator checkout (its src/ goes on sys.path)")
    ap.add_argument("--f-hi", type=float, default=16e9, help="top of the grid [Hz] (default 16e9: 32 GT/s Nyquist)")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--check", action="store_true",
                    help="export to a temporary directory and compare with the bundled files (CI's vendor-drift job)")
    a = ap.parse_args(argv)
    if a.pllsim is not None:
        sys.path.insert(0, str(a.pllsim.resolve() / "src"))
    if not a.check:
        for p in a.presets:
            export(p, a.f_hi, a.out)
        return 0
    import tempfile

    import yaml

    bad = 0
    with tempfile.TemporaryDirectory() as tmp:
        for p in a.presets:
            fresh = yaml.safe_load(export(p, a.f_hi, Path(tmp)).read_text(encoding="utf-8"))
            ship = a.out / f"{p}_to{a.f_hi / 1e9:g}g.yaml"
            have = yaml.safe_load(ship.read_text(encoding="utf-8"))
            same = (fresh["f0_hz"] == have["f0_hz"] and fresh["source"] == have["source"]
                    and np.allclose(fresh["f_hz"], have["f_hz"], rtol=1e-12, atol=0.0)
                    and np.allclose(fresh["l_dbc_hz"], have["l_dbc_hz"], rtol=0.0, atol=1e-6)
                    and len(fresh["spurs"]) == len(have["spurs"])
                    and all(abs(x["dbc"] - y["dbc"]) < 1e-6 and x["f_hz"] == y["f_hz"] for x, y in zip(fresh["spurs"], have["spurs"])))
            print(f"{ship.name}: {'matches the pinned pll_simulator' if same else 'DIFFERS from a fresh export'}")
            bad += not same
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
