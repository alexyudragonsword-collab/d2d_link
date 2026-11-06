"""Every example compiles and imports only names that exist; running them is
tools/run_examples.py --smoke's job (CI)."""

import ast
import importlib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = sorted((REPO / "examples").glob("[0-9][0-9]_*.py"))


def test_milestone_examples_exist():
    assert [p.name[:2] for p in EXAMPLES] == ["00", "01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12", "13", "14", "15"]


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_example_imports_resolve(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("d2d_link"):
            mod = importlib.import_module(node.module)
            for alias in node.names:
                assert hasattr(mod, alias.name), f"{path.name}: {node.module}.{alias.name}"


def test_only_a_missing_optional_package_is_a_skip():
    """run_examples reports an example as skipped only when the optional
    package itself is absent; an ImportError raised inside an installed one
    is a failure (third health check)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("run_examples", REPO / "tools" / "run_examples.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._missing_optional("ModuleNotFoundError: No module named 'matplotlib'") == "matplotlib"
    assert mod._missing_optional("ModuleNotFoundError: No module named 'skrf.io'") == "skrf"
    assert mod._missing_optional("ImportError: cannot import name 'x' from 'matplotlib' (/x)") is None
    assert mod._missing_optional("ModuleNotFoundError: No module named 'scipy'") is None


def test_smoke_flag_reaches_the_examples(tmp_path, monkeypatch):
    """--smoke sets D2D_LINK_SMOKE=1 for the child (examples 08 / 13 / 14 read
    it through _common.SMOKE and run a subset); a full-size run sets 0
    (0.14.8; sixth health check: untested)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("run_examples", REPO / "tools" / "run_examples.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    seen = []
    monkeypatch.setattr(mod, "_one", lambda p, cap, timeout, env, save: (seen.append(env["D2D_LINK_SMOKE"]), (0, "", 0.0))[1])
    mod.run([REPO / "examples" / "00_single_lane_eye.py"], 20_000, 10.0)
    mod.run([REPO / "examples" / "00_single_lane_eye.py"], 0, 10.0)
    assert seen == ["1", "0"]
    import subprocess
    import sys

    out = subprocess.run([sys.executable, "-c", "import _common; print(_common.SMOKE)"], cwd=REPO / "examples",
                         env={**__import__("os").environ, "D2D_LINK_SMOKE": "1"}, capture_output=True, text=True)
    assert out.stdout.strip() == "True"
