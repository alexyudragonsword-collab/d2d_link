"""Specification numbers with their provenance (invariant #5).

Every number the UCIe specification owns -- rates, BER target, bump pitch,
reach, module width, eye mask -- lives in ``data/spec/ucie_survey.yaml``, one
entry each, with ``source: survey`` (from public summaries; unverified) or
``source: spec`` (from the specification text, with a quote). Code takes
them through :func:`survey` by key and carries the source along; nothing
hard-codes them. ``grep "source: survey"`` on the data file lists every
unverified number at once.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
SURVEY_FILE = REPO / "data" / "spec" / "ucie_survey.yaml"
SOURCES = ("survey", "spec")


@dataclass(frozen=True)
class SpecNumber:
    key: str
    value: Any
    unit: str
    source: str          # "survey" | "spec"
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

    def tag(self) -> str:
        """``value unit (source: survey)`` -- how a result line should print it."""
        return f"{self.value} {self.unit} (source: {self.source})"


def load_survey(path: Path | str = SURVEY_FILE) -> dict[str, SpecNumber]:
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
    return out


@lru_cache(maxsize=1)
def _table() -> dict[str, SpecNumber]:
    return load_survey()


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


__all__ = ["SpecNumber", "survey", "all_entries", "unverified", "load_survey", "SURVEY_FILE", "SOURCES"]
