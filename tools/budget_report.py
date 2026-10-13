"""The timing budget of a link, lane by lane, as a Markdown (or JSON) report.

    python tools/budget_report.py configs/standard_32g_x16_module.yaml
    python tools/budget_report.py configs/standard_32g_x1.yaml -o budget.md
    python tools/budget_report.py configs/standard_32g_x1.yaml --json budget.json
    python tools/budget_report.py configs/standard_32g_x5_coupled.yaml --sensitivity

``--sensitivity`` answers "which guesses decide the verdict": every model
preset the config leans on (source: model -- trace resistance, loss tangent,
Z0, stack-up geometry, behavioural crosstalk level) and every survey number
it leans on (bump pitch for the coupled estimate; the eye-mask targets) is
moved by +-20 % (targets by +-10 mV / +-0.05 UI) and the link rerun; the
table lists the worst lane's margin on each side and marks the parameters
whose perturbation flips PASS/FAIL.

Everything comes from the config and the statistical engine (invariant #1,
#3): the clock-path budget in fs and UI by origin (Tx PLL leak, local PLL,
path noise, wander, tree, quantisation), the per-lane eye height and width
at the target BER against the targets with their source (invariant #5), the
crosstalk each lane sees and how the lanes were mapped after repair. The
report is the deliverable a "timing budget" asks for; the examples print the
same numbers in prose.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from d2d_link.report import (build, budget_rows, report, sensitivity, sensitivity_knobs,  # noqa: E402,F401
                             sensitivity_markdown, to_markdown)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("config", type=Path)
    ap.add_argument("-o", "--out", type=Path, help="Markdown file (default: stdout)")
    ap.add_argument("--json", type=Path, help="also write the report as JSON")
    ap.add_argument("--sensitivity", action="store_true",
                    help="also perturb every model / survey number by +-20 %% and report which flip the verdict")
    args = ap.parse_args(argv)
    from d2d_link.config import load_config

    cfg = load_config(args.config)
    rep = build(cfg)
    md = to_markdown(rep)
    if args.sensitivity:
        rep["sensitivity"] = sensitivity(cfg)
        md += "\n" + sensitivity_markdown(rep["sensitivity"])
    if args.out:
        args.out.write_text(md, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(md)
    if args.json:
        args.json.write_text(json.dumps(rep, indent=1), encoding="utf-8")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
