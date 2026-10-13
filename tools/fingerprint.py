"""Numerical fingerprint of the engines: prove a change did not move a number (invariant #6).

Tests assert thresholds and relations; a result that moves a little and still
satisfies them passes. A refactor therefore has to be checked bit for bit
(Halo_Serdes ``tools/fingerprint.py`` method). This records every bundled
config through the clock budget, the statistical engine and the time engine
(at a small size), plus a set of synthetic links for the paths no config
reaches: white PLL, rho < 1, a tree with delay and bandwidth, no tracker,
infinite tracker, a CTLE, a DDR duty-cycle error, spare-lane repair.

Scalars are stored by ``repr`` and arrays by SHA-256, so the comparison is
exact. Bit-exact means the same machine and library versions: record both
sides in one environment.

    python tools/fingerprint.py record before.json     # on the base commit
    python tools/fingerprint.py record after.json      # on the change
    python tools/fingerprint.py compare before.json after.json

``compare`` prints every differing value and exits 1 if there is one. A change
meant to move numbers (a fix) should move only the ones it explains; list
them in the PR. Both commands also list the entries that raised instead of
recording values: two sides failing the same way compare equal.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))


def digest(a) -> str:
    return hashlib.sha256(np.ascontiguousarray(np.asarray(a, dtype=np.float64))).hexdigest()[:16]


def stat_values(r) -> dict:
    out = {k: repr(float(getattr(r, k))) for k in
           ("log10_ber", "ber", "phase_ui", "eye_height_v", "eye_width_ui", "sigma_jitter_s", "main_cursor_v")}
    out["bathtub"] = digest(r.bathtub_ber)
    out["cursors"] = digest(r.cursors_v)
    out["cursors.n"] = int(r.cursors_v.size)
    for k in ("common_leak_s", "data_path_s", "clock_path_s", "tree_s"):
        out["jitter." + k] = repr(float(getattr(r.jitter, k)))
    for k, v in sorted(r.extras.items()):
        if isinstance(v, (bool, int, float, str)):
            out["x." + k] = repr(v)
    return out


def time_values(t) -> dict:
    return {"ber": repr(t.ber), "n_errors": repr(t.n_errors), "n_symbols": repr(t.n_symbols),
            "bursts": repr(getattr(t, "error_bursts", None)),
            "eye_sampled": repr(float(t.eye_height_sampled_v)), "jitter_rms_s": repr(float(t.jitter_rms_s)),
            "samples": digest(t.samples), "traces": digest(t.eye_traces)}


def _guarded(fn):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _small(cfg, n_symbols: int = 20_000):
    # a coarse bathtub is enough to pin every code path; the full one is minutes on a x64 module
    return dataclasses.replace(cfg, sim=dataclasses.replace(cfg.sim, n_symbols=n_symbols, engine="both",
                                                            stat_phase_points=16))


def record_configs() -> dict:
    from d2d_link.config import load_config
    from d2d_link.engine import run_link

    out = {}
    for p in sorted((REPO / "configs").glob("*.yaml")):
        cfg = _small(load_config(p))
        if cfg.lanes.count > 4:
            # the time engine on every lane of a wide module is minutes; the
            # statistical side still covers every lane
            cfg = dataclasses.replace(cfg, sim=dataclasses.replace(cfg.sim, engine="statistical"))

        def one(cfg=cfg):
            res = run_link(cfg)
            d = {"lanes": repr(res.lanes.logical_to_physical), "active": res.lanes.active_width,
                 "skew": digest(res.skew_ps)}
            for r in res.stat:
                d[f"stat/{r.lane}"] = stat_values(r)
            for t in res.time:
                d[f"time/{t.lane}"] = time_values(t)
            return d
        out[p.stem] = _guarded(one)
        print(f"  config {p.stem}", file=sys.stderr, flush=True)
    return out


def record_synthetic() -> dict:
    from d2d_link.clock.forwarded import ForwardedClock
    from d2d_link.config import (ChannelConfig, ClockingConfig, CtleConfig, LaneConfig, LinkConfig,
                                 RxConfig, SimConfig)
    from d2d_link.engine import run_link

    prof = "data/clock_profiles/bench_markulic16_sspll_40m_10p24g.yaml"
    sim = SimConfig(n_symbols=20_000, engine="both", stat_phase_points=32)
    cases = {
        "white_pll": LinkConfig(clocking=ClockingConfig(pll_rj_s=300e-15, data_path_rj_s=150e-15,
                                                        clock_path_rj_s=150e-15), sim=sim),
        "rho_0.7_tree": LinkConfig(clocking=ClockingConfig(pll_profile=prof, correlation=0.7, tree_delay_ps=60.0,
                                                           tree_bw_hz=8e9, tree_rj_s=80e-15), sim=sim),
        "no_tracker_dcd": LinkConfig(clocking=ClockingConfig(pll_profile=prof, data_path_rj_s=1e-12,
                                                             clock_path_rj_s=1e-12, dcd_ui=0.05), sim=sim),
        "inf_tracker_ctle": LinkConfig(channel=ChannelConfig(length_mm=40.0),
                                       clocking=ClockingConfig(pll_profile=prof, data_path_rj_s=1e-12,
                                                               track_bw_hz=float("inf")),
                                       rx=RxConfig(ctle=CtleConfig(enable=True, peak_db=4.0), noise_rms_v=0.02),
                                       sim=sim),
        "spare_repair_x4": LinkConfig(lanes=LaneConfig(count=4, spare_count=2, failed=(1,), repair="spare",
                                                       skew_ps=(1.0, 2.0, -3.0, 4.0, 0.5, -1.5),
                                                       deskew_step_ps=1.0),
                                      clocking=ClockingConfig(pll_profile=prof, data_path_rj_s=300e-15),
                                      sim=dataclasses.replace(sim, engine="statistical")),
    }
    out = {}
    for name, cfg in cases.items():
        def one(cfg=cfg):
            res = run_link(cfg)
            d = {"lanes": repr(res.lanes.logical_to_physical), "budget": repr(ForwardedClock(cfg).residual_sigma_s())}
            for r in res.stat:
                d[f"stat/{r.lane}"] = stat_values(r)
            for t in res.time:
                d[f"time/{t.lane}"] = time_values(t)
            return d
        out[name] = _guarded(one)
    rng = np.random.default_rng(3)
    out["synth/rho_0.7_tree"] = _guarded(lambda: digest(ForwardedClock(cases["rho_0.7_tree"]).synthesize(1 << 14, rng, 2)))
    print("  synthetic links", file=sys.stderr, flush=True)
    return out


def compare(a: dict, b: dict) -> tuple[int, list[str]]:
    """(leaf values compared, the differing ones as 'path: old -> new')."""
    diffs, n = [], 0

    def walk(path, x, y):
        nonlocal n
        if isinstance(x, dict) or isinstance(y, dict):
            x = x if isinstance(x, dict) else {}
            y = y if isinstance(y, dict) else {}
            for k in sorted(set(x) | set(y)):
                walk(path + [k], x.get(k), y.get(k))
        else:
            n += 1
            if x != y:
                diffs.append(" / ".join(path) + f": {x!r} -> {y!r}")

    walk([], a, b)
    return n, diffs


def raised(fp: dict) -> list[str]:
    out = []

    def walk(path, x):
        if isinstance(x, dict):
            for k in sorted(x):
                if k == "error":
                    out.append(" / ".join(path) + f": {x[k]}")
                else:
                    walk(path + [k], x[k])

    walk([], fp)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record", help="run the engines and write the fingerprint")
    rec.add_argument("out", type=Path)
    rec.add_argument("--no-synthetic", action="store_true", help="bundled configs only")
    cmp_ = sub.add_parser("compare", help="diff two fingerprints; exit 1 on any difference")
    cmp_.add_argument("a", type=Path)
    cmp_.add_argument("b", type=Path)
    args = ap.parse_args(argv)

    if args.cmd == "record":
        warnings.filterwarnings("ignore")
        t0 = time.time()
        fp = {"configs": record_configs()}
        if not args.no_synthetic:
            fp["synthetic"] = record_synthetic()
        args.out.write_text(json.dumps(fp, indent=1, sort_keys=True))
        n, _ = compare(fp, fp)
        print(f"recorded {n} values to {args.out} in {time.time() - t0:.0f} s")
        for line in raised(fp):
            print(f"  raised: {line}")
        return 0

    a = json.loads(args.a.read_text())
    b = json.loads(args.b.read_text())
    n, diffs = compare(a, b)
    for d in diffs:
        print(d)
    bad = raised(b)
    for line in bad:
        print(f"  raised: {line}")
    if bad:
        print(f"{len(bad)} entries raised (compare equal when both sides fail the same way)")
    if diffs:
        print(f"{len(diffs)} of {n} values differ")
        return 1
    print(f"{n} values bit-identical")
    return 0


if __name__ == "__main__":
    sys.exit(main())
