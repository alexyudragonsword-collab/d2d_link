"""Specification numbers with their provenance (invariant #5).

Every number the UCIe specification owns -- rates, BER target, bump pitch,
reach, module width, eye mask -- lives in ``src/d2d_link/data/spec/ucie_survey.yaml``, one
entry each, with ``source: survey`` (from public summaries; unverified) or
``source: spec`` (from the specification text, with a quote). Code takes
them through :func:`survey` by key and carries the source along; nothing
hard-codes them. ``grep "source: survey"`` on the data file lists every
unverified number at once.

The numbers the specification does *not* own but a simulation still needs --
the package trace's resistance and loss tangent, the stack-up geometry, the
behavioural crosstalk level -- are model estimates and live in
``src/d2d_link/data/spec/model_presets.yaml`` with ``source: model``, read through
:func:`preset`. ``grep "source: model"`` lists every estimate; the budget
report's ``--sensitivity`` perturbs each one to show which estimates decide a
verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

# the tables ship inside the package (src/d2d_link/data/spec, package data):
# an installed d2d_link finds them without the checkout
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
SURVEY_FILE = DATA_DIR / "spec" / "ucie_survey.yaml"
PRESETS_FILE = DATA_DIR / "spec" / "model_presets.yaml"
SOURCES = ("survey", "spec", "model")


@dataclass(frozen=True)
class SpecNumber:
    key: str
    value: Any
    unit: str
    source: str          # "survey" | "spec" | "model"
    cite: str
    note: str = ""
    quote: str = ""      # required when source == "spec"
    section: str = ""

    def __post_init__(self):
        if self.source not in SOURCES:
            raise ValueError(f"spec entry {self.key!r}: source must be one of {SOURCES}, got {self.source!r}")
        if not self.cite:
            raise ValueError(f"spec entry {self.key!r}: cite is required")
        if self.source == "spec" and not self.quote:
            raise ValueError(f"spec entry {self.key!r}: source 'spec' needs the quoted text")

    @property
    def verified(self) -> bool:
        return self.source == "spec"

    @property
    def estimated(self) -> bool:
        return self.source == "model"

    def tag(self) -> str:
        """``value unit (source: survey)`` -- how a result line should print it."""
        return f"{self.value} {self.unit} (source: {self.source})"


def load_survey(path: Path | str = SURVEY_FILE, allowed: tuple[str, ...] = ("survey", "spec")) -> dict[str, SpecNumber]:
    """Read a table of tagged numbers; every entry's source must be in ``allowed``."""
    import yaml

    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    entries = data.get("entries") or {}
    out = {}
    for key, e in entries.items():
        if not isinstance(e, dict):
            raise ValueError(f"spec entry {key!r} is not a mapping")
        unknown = set(e) - {"value", "unit", "source", "cite", "note", "quote", "section"}
        if unknown:
            raise ValueError(f"spec entry {key!r}: unknown fields {sorted(unknown)}")
        out[key] = SpecNumber(key=key, value=e.get("value"), unit=str(e.get("unit", "")),
                              source=str(e.get("source", "")), cite=str(e.get("cite", "")),
                              note=str(e.get("note", "")), quote=str(e.get("quote", "")),
                              section=str(e.get("section", "")))
        if out[key].source not in allowed:
            raise ValueError(f"spec entry {key!r} in {Path(path).name}: source {out[key].source!r} "
                             f"does not belong in this table (allowed {allowed})")
    return out


@lru_cache(maxsize=1)
def _table() -> dict[str, SpecNumber]:
    return load_survey()


@lru_cache(maxsize=1)
def _presets() -> dict[str, SpecNumber]:
    return load_survey(PRESETS_FILE, allowed=("model",))


def preset(key: str, package: str) -> SpecNumber:
    """The model estimate ``<package>.<key>`` (``src/d2d_link/data/spec/model_presets.yaml``)."""
    table = _presets()
    full = f"{package}.{key}"
    if full not in table:
        raise KeyError(f"no model preset {full!r} (have {sorted(table)})")
    return table[full]


def all_presets() -> dict[str, SpecNumber]:
    return dict(_presets())


def preset_values() -> dict[str, dict[str, float]]:
    """``{package: {parameter: value}}`` -- the shape the config layer's
    ``PACKAGE_*`` dictionaries are built from."""
    out: dict[str, dict[str, float]] = {}
    for full, e in _presets().items():
        pkg, name = full.split(".", 1)
        out.setdefault(pkg, {})[name] = e.value
    return out


def survey(key: str, package: str | None = None) -> SpecNumber:
    """The entry ``key``; with ``package`` given, ``<package>.<key>`` first."""
    table = _table()
    if package is not None and f"{package}.{key}" in table:
        return table[f"{package}.{key}"]
    if key not in table:
        raise KeyError(f"no spec entry {key!r} (have {sorted(table)})")
    return table[key]


def all_entries() -> dict[str, SpecNumber]:
    return dict(_table())


def unverified() -> list[SpecNumber]:
    return [e for e in _table().values() if not e.verified]


__all__ = ["SpecNumber", "survey", "all_entries", "unverified", "load_survey", "SURVEY_FILE", "SOURCES",
           "preset", "all_presets", "preset_values", "PRESETS_FILE"]
