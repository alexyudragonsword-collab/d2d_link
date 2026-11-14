"""Specification numbers with their provenance (invariant #5).

Every number the UCIe specification owns -- rates, BER target, bump pitch,
reach, module width, eye mask -- lives in the shared library spec_sources
(``data/ucie.yaml``, keys prefixed ``ucie.``), vendored and pinned under
``src/d2d_link/vendor/spec_sources/`` (0.16.0; until then this repository's
own ``data/spec/ucie_survey.yaml``). One entry each, with ``source: survey``
(from public summaries; unverified) or ``source: spec`` (from the
specification text, with a quote). This module is the shim: it hangs the
shared entries back on this library's old bare keys
(``legacy_keys/d2d_link.yaml``, in the old table's order), so code keeps
taking them through :func:`survey` / :func:`survey_tiered` by the same keys
and carries the source along; nothing hard-codes them. ``grep "source:
survey"`` on the vendored ``ucie.yaml`` lists every unverified number at
once. A change to a number is made in spec_sources and re-pinned here.

The numbers the specification does *not* own but a simulation still needs --
the package trace's resistance and loss tangent, the stack-up geometry, the
behavioural crosstalk level -- are model estimates and live in
``src/d2d_link/data/spec/model_presets.yaml`` with ``source: model``, read through
:func:`preset`. ``grep "source: model"`` lists every estimate; the budget
report's ``--sensitivity`` perturbs each one to show which estimates decide a
verdict.
"""

from __future__ import annotations

import re

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

# the tables ship inside the package (package data): an installed d2d_link
# finds them without the checkout. The UCIe table is spec_sources', vendored.
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
VENDOR_DIR = Path(__file__).resolve().parents[1] / "vendor" / "spec_sources"
SURVEY_FILE = VENDOR_DIR / "data" / "ucie.yaml"
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
    check_ranges(out)
    return out


def check_ranges(table: dict) -> None:
    """Refuse overlapping rate ranges for one key when the table is read, not
    only when a rate in the overlap is asked for (0.15.6; sixth health check)."""
    spans: dict[str, list[tuple[float, float, str]]] = {}
    for k in table:
        m = re.fullmatch(r"(.+)@([0-9.]+)-([0-9.]+)", k)
        if m:
            spans.setdefault(m.group(1), []).append((float(m.group(2)), float(m.group(3)), k))
    for base, items in spans.items():
        items.sort()
        for (a0, a1, ka), (b0, b1, kb) in zip(items, items[1:]):
            if b0 <= a1:
                raise ValueError(f"overlapping rate ranges for {base!r}: {ka} and {kb}")


@lru_cache(maxsize=1)
def _table() -> dict[str, SpecNumber]:
    """spec_sources' ``ucie.*`` entries under this library's old bare keys
    (``legacy_keys/d2d_link.yaml``, the old table's order), as this
    library's own :class:`SpecNumber`; spec_sources leaves ``quote`` /
    ``section`` as None where this library had ``""``."""
    from ..vendor.spec_sources import reader as ss

    shared = ss.load_table(SURVEY_FILE)
    out = {}
    for old, new in ss.legacy_keys("d2d_link").items():
        e = shared[new]
        out[old] = SpecNumber(key=old, value=e.value, unit=e.unit, source=e.source, cite=e.cite,
                              note=e.note, quote=e.quote or "", section=e.section or "")
    out.update(_raw_ber_tiers(shared, ss.ref))
    check_ranges(out)
    return out


RAW_BER_BY_RATE = "ucie.raw_ber_by_rate"


def _raw_ber_tiers(shared: dict, ref) -> dict[str, SpecNumber]:
    """``<package>.raw_ber_target@<rate>`` for every package and rate of
    spec_sources' rate x package BER table (issue #2 point 2, 0.17.0): the
    standard package needs 1e-15 from 12 GT/s, the advanced from 16 GT/s,
    1e-27 below. Each is a ``ref`` into that one entry (lookup only, no
    copied number); the plain ``raw_ber_target`` (1e-27) stays the fallback
    for a rate the table does not list."""
    by = shared[RAW_BER_BY_RATE]
    out = {}
    for package in ("standard", "advanced"):
        for rate in by.value["data_rate_gtps"]:
            key = f"{package}.raw_ber_target@{float(rate):g}"
            v = ref(f"{RAW_BER_BY_RATE}#{package}@data_rate_gtps={rate}", shared)
            out[key] = SpecNumber(key=key, value=float(v), unit=shared["ucie.raw_ber_target"].unit, source=by.source, cite=by.cite,
                                  note=f"{RAW_BER_BY_RATE} 的 {package} 列在 {rate} GT/s 的值(本库按 封装 × 速率 分档读)。",
                                  quote=by.quote or "", section=by.section or "")
    return out


@lru_cache(maxsize=1)
def _presets() -> dict[str, SpecNumber]:
    return load_survey(PRESETS_FILE, allowed=("model",))


def preset(key: str, package: str) -> SpecNumber:
    """The model estimate ``<package>.<key>`` (``src/d2d_link/data/spec/model_presets.yaml``, this library's own)."""
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


def tier_keys(key: str, package: str | None = None, rate_gtps: float | None = None) -> list[str]:
    """The table keys a tiered lookup tries, most specific first:
    ``<package>.<key>@<rate>``, ``<package>.<key>``, ``<key>@<rate>``, ``<key>``
    (``@32`` for 32 GT/s). The package outranks the rate: the standard and
    advanced packages are separate electrical specifications, so a
    package's own number holds at every rate unless that package names the
    rate itself; a rate-only entry is the fallback for packages that say
    nothing (0.13.10; 0.13.5-0.13.9 tried the rate tier first, untested). The survey has only the plain keys today -- the
    eye mask its sources quote carries no rate or package -- so every tier
    resolves to them; an entry added with the original text's tier (e.g.
    ``standard.rx_eye_width_ui@32``, ``source: spec``) takes over for that
    tier alone and the report names the key it came from."""
    rate = None if rate_gtps is None else f"@{float(rate_gtps):g}"
    out = []
    if package is not None and rate is not None:
        out.append(f"{package}.{key}{rate}")
    if package is not None:
        out.append(f"{package}.{key}")
    if rate is not None:
        out.append(f"{key}{rate}")
    out.append(key)
    return out


def _range_entry(table: dict[str, SpecNumber], base: str, rate_gtps: float) -> SpecNumber | None:
    """The entry ``<base>@<lo>-<hi>`` whose closed range holds ``rate_gtps``
    (``rx_eye_width_ui@24-32``), or None. Two overlapping ranges are an error
    in the table."""
    hits = []
    for k, e in table.items():
        m = re.fullmatch(re.escape(base) + r"@([0-9.]+)-([0-9.]+)", k)
        if m and float(m.group(1)) <= rate_gtps <= float(m.group(2)):
            hits.append(e)
    if len(hits) > 1:
        raise ValueError(f"overlapping rate ranges for {base!r} at {rate_gtps:g} GT/s: {[e.key for e in hits]}")
    return hits[0] if hits else None


def survey_tiered(key: str, package: str | None = None, rate_gtps: float | None = None,
                  table: dict[str, SpecNumber] | None = None) -> SpecNumber:
    """The most specific entry for ``key`` at this package and data rate
    (``tier_keys``); its ``.key`` says which tier answered. At each rate tier
    an exact ``@<rate>`` entry wins, then a range ``@<lo>-<hi>`` holding the
    rate (0.14.5: the 0.65 UI quote is for "24 to 32 GT/s", and an exact
    ``@24`` / ``@32`` pair left 28 GT/s on the 0.75 UI fallback -- fifth
    health check)."""
    table = _table() if table is None else table
    for k in tier_keys(key, package, rate_gtps):
        if k in table:
            return table[k]
        if rate_gtps is not None and "@" in k:
            hit = _range_entry(table, k.split("@", 1)[0], float(rate_gtps))
            if hit is not None:
                return hit
    raise KeyError(f"no spec entry for {key!r} at {package} / {rate_gtps} GT/s (tried {tier_keys(key, package, rate_gtps)})")


def all_entries() -> dict[str, SpecNumber]:
    return dict(_table())


def unverified() -> list[SpecNumber]:
    return [e for e in _table().values() if not e.verified]


__all__ = ["SpecNumber", "survey", "survey_tiered", "tier_keys", "all_entries", "unverified", "load_survey", "SURVEY_FILE", "SOURCES",
           "preset", "all_presets", "preset_values", "PRESETS_FILE"]
