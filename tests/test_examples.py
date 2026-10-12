"""Every example compiles and imports only names that exist; running them is
tools/run_examples.py --smoke's job (CI)."""

import ast
import importlib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = sorted((REPO / "examples").glob("[0-9][0-9]_*.py"))


def test_four_milestone_examples_exist():
    assert [p.name[:2] for p in EXAMPLES] == ["00", "01", "02", "03"]


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_example_imports_resolve(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("d2d_link"):
            mod = importlib.import_module(node.module)
            for alias in node.names:
                assert hasattr(mod, alias.name), f"{path.name}: {node.module}.{alias.name}"
