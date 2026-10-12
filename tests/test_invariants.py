"""Static guards for invariant #1 (config is the only truth) and #2 (no independent Rx clock)."""

import re

from conftest import REPO

SRC = REPO / "src" / "d2d_link"
ENGINE_DIRS = ("engine", "clock", "channel", "core")

# rates, the BER target and the standard-package reach written as literals
_SPEC_LITERALS = re.compile(r"\b(?:4|8|12|16|24|32)(?:\.0)?e9\b|\b1(?:\.0)?e-27\b|\b25\.0?\s*(?:mm|e-3)\b")


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
        assert "data_rate_gtps=" not in s, f"{p.name} sets the rate outside the config"


def test_law2_no_independent_receive_clock_anywhere():
    """The config has no Rx clock profile, and nothing but clock/forwarded.py
    synthesises phase noise: a second PLL object for the receiver is the
    shortcut the invariant forbids."""
    from d2d_link.config.form import schema_paths

    assert not [p for p in schema_paths() if re.search(r"rx.*(pll|profile|clock)", p)]
    users = [p.relative_to(REPO) for p, s in _sources(("engine", "channel", "core"))
             if "synth_from_psd" in s or "ClockProfile(" in s]
    assert not users, users
