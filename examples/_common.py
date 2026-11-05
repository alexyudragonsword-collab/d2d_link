"""Shared plumbing for the examples: repo paths, a non-interactive matplotlib,
PLL-floor variants of a bundled clock profile (examples 10 and 11)."""

import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
OUT = REPO / "examples" / "output"
OUT.mkdir(exist_ok=True)
CONFIGS = REPO / "configs"


def plt_or_none():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        return plt
    except ImportError:
        return None


def fmt_target(res, name: str, unit: str) -> str:
    v, src = res.targets[name]
    return f"{v:g} {unit} (source: {src})"


_VARIANTS: Path | None = None


def pll_floor_variant(profile: str, floor_dbc: float, bundled_floor: float = -145.0) -> str:
    """``profile`` (a config's ``clocking.pll_profile``) with its white floor
    ``bundled_floor`` [dBc/Hz] taken off and ``floor_dbc`` put on: the in-band
    shape (what lies above the floor) is kept. Written to a temporary
    directory and returned as a path for ``clocking.pll_profile`` (the config
    stays the single source of truth, invariant #1). A design target, not a
    measured PLL."""
    if floor_dbc == bundled_floor:
        return profile
    import numpy as np
    import yaml

    from d2d_link.clock.forwarded import resolve_data_file

    global _VARIANTS
    if _VARIANTS is None:
        _VARIANTS = Path(tempfile.mkdtemp(prefix="d2d_floor_"))
    src = resolve_data_file(profile)
    base = yaml.safe_load(src.read_text())
    level = np.asarray(base["l_dbc_hz"], dtype=float)
    top = float(level[-1])
    if abs(top - bundled_floor) > 0.1:
        raise ValueError(f"{src.name} ends at {top:.2f} dBc/Hz, not the {bundled_floor:g} dBc/Hz floor this variant "
                         "takes off (give bundled_floor)")
    s = np.maximum(10.0 ** (level / 10.0) - 10.0 ** (bundled_floor / 10.0), 0.0) + 10.0 ** (floor_dbc / 10.0)
    var = dict(base, l_dbc_hz=[float(v) for v in 10.0 * np.log10(s)],
               source=f"{base['source']}; white floor {bundled_floor:g} -> {floor_dbc:g} dBc/Hz (a design target)")
    p = _VARIANTS / f"{src.stem}_floor{-floor_dbc:g}.yaml"
    p.write_text(yaml.safe_dump(var, sort_keys=False))
    return str(p)
