"""Which commit of a push moved the numbers -- and did it say so?

The CI fingerprint job compares the push's base with its head. Until 0.13.10
a ``(numbers-move`` marker on *any* commit in the range waived the whole
range: a push of a marked commit and an unmarked one let an accidental move
in the unmarked one through (fourth health check). This tool settles a range
whose fingerprint moved:

- no commit marked (and no PR label): fail -- as before;
- every commit marked: pass -- nothing to attribute;
- some marked: record the fingerprint at every commit of the range (first
  parent, oldest first; each in a worktree with its own code) and compare
  consecutive ones. An unmarked commit whose fingerprint differs from its
  parent's fails, named. Ranges longer than ``--max-walk`` commits fall
  back to the range rule with a warning.

    python tools/fingerprint_walk.py --base SHA --base-json base.json --head-json head.json

The marker is ``(numbers-move`` followed by ``)``, ``:`` or ``,`` in the
commit message, so prose that mentions the word does not count.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import fingerprint as fp  # noqa: E402

MARKER = re.compile(r"\(numbers-move[:,)]")


def git(*args: str, cwd: Path = REPO) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def commits(base: str, head: str = "HEAD") -> list[str]:
    """The first-parent commits of base..head, oldest first."""
    return git("rev-list", "--reverse", "--first-parent", f"{base}..{head}").split()


def marked(sha: str) -> bool:
    return bool(MARKER.search(git("log", "-1", "--format=%B", sha)))


def record_at(sha: str, out: Path) -> dict:
    """Fingerprint of commit ``sha`` with its own code: a worktree, an
    editable install of it, its own tools/fingerprint.py."""
    with tempfile.TemporaryDirectory(prefix="fpwalk_") as tmp:
        wt = Path(tmp) / "wt"
        git("worktree", "add", "--detach", str(wt), sha)
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--no-deps", "-e", str(wt)], check=True)
            subprocess.run([sys.executable, "tools/fingerprint.py", "record", str(out)], cwd=wt, check=True)
        finally:
            git("worktree", "remove", "--force", str(wt))
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--no-deps", "-e", str(REPO)], check=True)
    return json.loads(out.read_text(encoding="utf-8"))


def settle(base: str, base_fp: dict, head_fp: dict, labels: list[str], max_walk: int, recorder=record_at,
           shas: list[str] | None = None, is_marked=marked) -> tuple[bool, list[str]]:
    """``(ok, messages)`` for a range whose head may differ from its base."""
    n = len(fp.compare(base_fp, head_fp)[1])
    if n == 0:
        return True, ["fingerprint bit-identical over the range"]
    if "numbers-move" in labels:
        return True, [f"{n} values moved; the PR carries the numbers-move label"]
    shas = commits(base) if shas is None else shas
    flags = {s: is_marked(s) for s in shas}
    if not any(flags.values()):
        return False, [f"{n} values moved and no commit in the range carries (numbers-move)"]
    if all(flags.values()):
        return True, [f"{n} values moved; every commit in the range carries (numbers-move)"]
    if len(shas) > max_walk:
        return True, [f"warning: {len(shas)} commits exceed --max-walk {max_walk}; the range rule waives them"]
    msgs, bad = [], False
    prev = base_fp
    for i, s in enumerate(shas):
        cur = head_fp if i == len(shas) - 1 else recorder(s, Path(tempfile.mkstemp(suffix=".json")[1]))
        k = len(fp.compare(prev, cur)[1])
        state = "marked" if flags[s] else "unmarked"
        msgs.append(f"{s[:7]} {state}: {k} values moved")
        if k and not flags[s]:
            bad = True
            msgs.append(f"error: {s[:7]} moved {k} values without (numbers-move)")
        prev = cur
    return not bad, msgs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", required=True)
    ap.add_argument("--base-json", type=Path, required=True)
    ap.add_argument("--head-json", type=Path, required=True)
    ap.add_argument("--labels", default="[]", help="the PR's labels as JSON (empty on a push)")
    ap.add_argument("--max-walk", type=int, default=12)
    a = ap.parse_args(argv)
    labels = json.loads(a.labels or "[]") or []
    ok, msgs = settle(a.base, json.loads(a.base_json.read_text()), json.loads(a.head_json.read_text()), labels, a.max_walk)
    for m in msgs:
        print(("::error::" + m) if m.startswith("error") else m)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
