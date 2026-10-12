"""Shared plumbing for the examples: repo paths, a non-interactive matplotlib."""

import sys
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
