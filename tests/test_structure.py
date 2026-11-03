"""Structural properties of every bundled configuration's pulse and engine
inputs (phase 13).

Two model errors lived through every numerical consistency test because both
engines read the same pulse: the non-causal analytic line (energy before the
line's delay, 9b) and the waveform grid's brick wall at low data rates
(response left at the grid's top frequency, phase 12). Both were found by
looking at a structural property, not by comparing numbers. These tests run
those probes, and a few more of the same kind, over every config in
``configs/``: causality, passivity, DC consistency, grid truncation, window
wrap-around, and the normalisation of what the statistical engine
integrates over. Thresholds sit a factor 1.5-3 above today's worst config;
the comments give the measured values.
"""

import math

import numpy as np
import pytest

from conftest import REPO
from d2d_link.channel import link_response
from d2d_link.config import load_config
from d2d_link.engine.statistical import StatisticalEngine

CONFIGS = sorted((REPO / "configs").glob("*.yaml"))


@pytest.fixture(scope="module", params=CONFIGS, ids=lambda p: p.stem)
def bundled(request):
    cfg = load_config(request.param)
    return cfg, link_response(cfg)


def _lc_arrival_index(cfg) -> int | None:
    """The sample one UI before the analytic line's LC delay (None for a file)."""
    if cfg.channel.kind != "analytic":
        return None
    p = cfg.rlgc()
    tau = cfg.channel.length_mm * 1e-3 * math.sqrt(p["l_h_m"] * p["c_f_m"])
    return int(tau / cfg.dt) - cfg.sim.osr


def test_causal(bundled):
    """Nothing arrives before the line's LC delay: 0.30 % of the main cursor
    at most today (band-edge ripple), 2 % with the 0.11 non-causal line."""
    cfg, r = bundled
    n = _lc_arrival_index(cfg)
    if n is None or n <= 0:
        pytest.skip("no analytic delay to measure against")
    assert np.max(np.abs(r.pulse.y[:n])) < 0.006 * r.main_amplitude
    for key, w in (r.xtalk_pulses or {}).items():
        if key == "next":
            continue                       # near-end crosstalk arrives without the line's delay
        assert np.max(np.abs(w.y[:n])) < 0.006 * max(float(np.max(np.abs(w.y))), 1e-30), key


def test_passive_and_real_at_dc(bundled):
    """A matched passive line never gains (|H| <= 1 on the normalised scale)
    and its DC response is real and positive."""
    cfg, r = bundled
    H = r.channel.H
    assert np.max(np.abs(H)) <= 1.0 + 1e-9
    assert abs(H[0].imag) < 1e-12 and H[0].real > 0.0


def test_grid_top_leaves_nothing_to_ring(bundled):
    """The waveform grid's top frequency osr x f_N cuts the response off: what
    is left there rings the pulse (0.58 at 4 GT/s on the 32x grid before phase
    12). Bundled configs: 0.076 at most (the 2 mm advanced line)."""
    _cfg, r = bundled
    assert r.grid_top_response < 0.15


def test_pulse_window_holds_the_tail(bundled):
    """The FFT window is circular: what the pulse still holds at its end
    wraps onto its start. 6.3e-4 of the main cursor at most today."""
    cfg, r = bundled
    osr = cfg.sim.osr
    assert np.max(np.abs(r.pulse.y[-2 * osr:])) < 2e-3 * r.main_amplitude


def test_baud_samples_sum_to_dc(bundled):
    """Every baud-spaced sample of the pulse sums to the symbol's DC response
    (the pulse is a 1-UI box through H): 0.9997 of it on the 512 UI window.
    The statistical engine's cursor window (sim.stat_cursor_reach each side)
    reads 0.994 of it today -- the 0.6 % beyond +256 UI is the third health
    check's finding M1, and this bound is where it shows if it grows."""
    cfg, r = bundled
    y, osr, i0 = r.pulse.y, cfg.sim.osr, r.main_index
    dc = 0.5 * cfg.tx.swing_vpp * abs(r.channel.H[0])
    ks = np.arange(-(i0 // osr), (y.size - 1 - i0) // osr + 1)
    every = np.interp(i0 + ks * osr, np.arange(y.size), y)
    assert np.sum(every) == pytest.approx(dc, rel=1e-3)
    c, _ = r.cursors(0.0)
    assert np.sum(c) == pytest.approx(dc, rel=1e-2)


def test_engine_integrates_over_normalised_measures(bundled):
    """The ISI distribution and the jitter quadrature are probability
    measures, and the quadrature's variance is the budget's: Gaussian sigma^2
    + the PI step's w^2/12 + each spur's A^2/2. The step's box on the fine
    grid was a whole number of nodes wide, which put the variance 2 % high on
    x5 (the third health check's finding M2); since phase 15 the box's end
    nodes carry the fraction that makes its variance exact."""
    cfg, r = bundled
    eng = StatisticalEngine(cfg, r)
    assert eng.weights.sum() == pytest.approx(1.0, abs=1e-12)
    expected = eng.sigma_j_ui ** 2 + eng.quant_ui ** 2 / 12.0 + sum(0.5 * a ** 2 for a in eng.spurs_ui)
    if expected > 0.0:
        assert float(np.sum(eng.weights * eng.nodes ** 2)) == pytest.approx(expected, rel=2e-3)
    m = eng.model_at(0.0)
    assert m.pmf.sum() == pytest.approx(1.0, abs=1e-12)
    assert np.all(m.pmf >= 0.0)
