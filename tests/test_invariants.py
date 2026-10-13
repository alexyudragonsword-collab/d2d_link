"""Static guards for invariant #1 (config is the only truth) and #2 (no independent Rx clock)."""

import re

from conftest import REPO

SRC = REPO / "src" / "d2d_link"
ENGINE_DIRS = ("engine", "clock", "channel", "core")

# rates, the BER target and the standard-package reach written as literals
_SPEC_LITERALS = re.compile(r"\b(?:4|8|12|16|24|32)(?:\.0)?e9\b|\b1(?:\.0)?e-27\b|\b25\.0?\s*(?:mm|e-3)\b|\b3\.2e10\b")
# in the config layer, examples and tools: a spec number assigned to the field
# that owns it (the table is the only place these may be written)
_SPEC_ASSIGNMENTS = re.compile(
    r"data_rate_gtps\s*=\s*[0-9]|swing_vpp\s*=\s*0\.4\b|length_mm\s*=\s*(?:25|2)\.0\b|"
    r"\b1(?:\.0)?e-27\b|eye_height_mv\s*=\s*40|eye_width_ui\s*=\s*0\.75")
# the two schema defaults that still carry a survey number; phase 5 of the
# plan resolves them from the table and removes this allowance
_ALLOWED = {("config/schema.py", "data_rate_gtps = 32"), ("config/schema.py", "swing_vpp = 0.4")}


def code_only(source: str) -> str:
    """The source with comments and string literals (docstrings) blanked: a
    number quoted in prose is not a number the code uses."""
    import io
    import tokenize

    out = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type not in (tokenize.COMMENT, tokenize.STRING):
            out.append(tok.string)
    return " ".join(out)


def _sources(dirs):
    for d in dirs:
        for p in sorted((SRC / d).rglob("*.py")):
            yield p, code_only(p.read_text(encoding="utf-8"))


def test_law1_engines_hardcode_no_rate_ber_or_reach():
    hits = [(p.relative_to(REPO), m.group(0)) for p, s in _sources(ENGINE_DIRS)
            for m in _SPEC_LITERALS.finditer(s)]
    assert not hits, f"spec numbers must come from the config / survey table, found {hits}"


def test_law1_config_tools_examples_assign_no_spec_number():
    files = [*sorted((SRC / "config").rglob("*.py")), *sorted((REPO / "tools").glob("*.py")),
             *sorted((REPO / "examples").glob("*.py"))]
    hits = []
    for p in files:
        for m in _SPEC_ASSIGNMENTS.finditer(code_only(p.read_text(encoding="utf-8"))):
            key = (p.relative_to(SRC).as_posix() if SRC in p.parents else p.name, re.sub(r"\s+", " ", m.group(0)).replace(".0", ""))
            if key not in _ALLOWED:
                hits.append((p.relative_to(REPO).as_posix(), m.group(0)))
    assert not hits, f"spec numbers assigned outside the table: {hits}"


def test_law1_engines_take_the_config_not_loose_numbers():
    """Every public run_* entry point takes a LinkConfig first."""
    from d2d_link.engine import run_link, run_statistical, run_time
    import inspect

    for fn in (run_link, run_statistical, run_time):
        first = next(iter(inspect.signature(fn).parameters.values()))
        assert first.name == "cfg", fn.__name__


def test_law1_examples_read_the_config_files():
    for p in sorted((REPO / "examples").glob("[0-9][0-9]_*.py")):
        s = p.read_text(encoding="utf-8")
        assert "load_config(" in s, f"{p.name} must start from a config file"
        # a sweep may take the rate from the survey table; a literal number may not
        assert not re.search(r"data_rate_gtps\s*=\s*[0-9]", s), f"{p.name} sets a literal rate outside the config"


def test_law2_no_independent_receive_clock_anywhere():
    """The config has no free-running Rx clock: the receiver's only clock
    fields are the ``clocking.local_pll_*`` of a PLL locked to the forwarded
    clock (a loop bandwidth is mandatory), and nothing but clock/forwarded.py
    synthesises phase noise -- a second PLL object for the receiver is the
    shortcut the invariant forbids."""
    import pytest

    from d2d_link.config import ClockingConfig
    from d2d_link.config.form import schema_paths

    assert not [p for p in schema_paths() if re.search(r"^rx\..*(pll|profile|clock)", p)]
    rx_clock = [p for p in schema_paths() if re.search(r"(pll|clock)", p) and not p.startswith("clocking.")]
    assert not rx_clock, rx_clock
    with pytest.raises(ValueError, match="locked to the forwarded clock"):
        ClockingConfig(local_pll_rj_s=100e-15)          # a local PLL without a loop: refused
    users = [p.relative_to(REPO) for p, s in _sources(("engine", "channel", "core"))
             if "synth_from_psd" in s or "ClockProfile(" in s]
    assert not users, users
