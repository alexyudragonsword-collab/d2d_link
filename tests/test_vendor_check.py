"""Vendor drift: the vendored tree matches the pinned upstream commits.

Runs the real ``tools/vendor_check.py``. Skips when the sibling checkouts are
absent (a bare checkout still passes); the ``vendor-drift`` CI job checks them
out at the pinned SHAs and passes ``--strict --fail-on-skip`` so there a skip
is red. Adapted from Halo_Serdes tests/test_vendor_check.py.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("vendor_check", REPO / "tools" / "vendor_check.py")
vc = importlib.util.module_from_spec(_spec)
sys.modules["vendor_check"] = vc
_spec.loader.exec_module(vc)

SIBLINGS = {"Halo_Serdes": ("/home/user/alexyudragonsword-collab/halo_serdes",),
            "pll_simulator": ("/home/user/alexyudragonsword-collab/pll_simulator",)}


def _siblings():
    roots = {}
    for repo, cands in SIBLINGS.items():
        if vc.Siblings({}).path(repo) is None:
            for c in cands:
                if (Path(c) / ".git").exists():
                    roots[repo] = c
    return vc.Siblings(roots)


def _have_all(sib):
    return all(sib.path(r) is not None for r in SIBLINGS)


def test_no_drift():
    sib = _siblings()
    if not _have_all(sib):
        pytest.skip("sibling checkouts not present")
    manifest = vc.json.loads(vc.MANIFEST.read_text()) if vc.MANIFEST.exists() else {}
    results = vc.check(sib, manifest)
    drift = [r for r in results if r.status == "DRIFT"]
    assert not drift, "vendor drift:\n" + "\n".join(f"  {r.rel}: {r.detail}" for r in drift)
    assert not [r for r in results if r.status == "skip"]


def test_every_file_has_a_full_sha_header():
    bad = []
    for f in sorted((REPO / "src/d2d_link/vendor").rglob("*.py")):
        if f.name == "__init__.py":
            continue
        first = f.read_text().splitlines()[0]
        m = vc.HEADER.match(first)
        if not m or len(m["sha"]) != 40:
            bad.append(str(f.relative_to(REPO)))
    assert not bad, "vendored files without a full-SHA attribution header: " + ", ".join(bad)


def test_manifest_files_exist():
    declared = vc.json.loads(vc.MANIFEST.read_text()).get("files", {})
    missing = [rel for rel in declared if not (REPO / "src/d2d_link/vendor" / rel).exists()]
    assert not missing


def test_detects_injected_drift():
    sib = _siblings()
    if not _have_all(sib):
        pytest.skip("sibling checkouts not present")
    target = REPO / "src/d2d_link/vendor/pllsim/jitter.py"
    original = target.read_text()
    try:
        target.write_text(original + "\nINJECTED_DRIFT = 1\n")
        results = vc.check(sib, vc.json.loads(vc.MANIFEST.read_text()))
        assert any(r.status == "DRIFT" and "jitter.py" in r.rel for r in results)
    finally:
        target.write_text(original)
