"""The pll_simulator profile file: conventions pinned."""

import numpy as np
import pytest

from conftest import PROFILE, REPO
from d2d_link.clock.profile import ClockProfile


def test_load_shipped_profile():
    p = ClockProfile.load(REPO / PROFILE)
    assert p.f0_hz == pytest.approx(10.24e9, rel=1e-3)
    assert p.f_hz[0] == pytest.approx(100.0) and p.f_hz[-1] == pytest.approx(p.f0_hz / 2, rel=1e-6)
    assert "pllsim" in p.source


def test_single_sideband_convention():
    p = ClockProfile(1e9, np.array([1e3, 1e6]), np.array([-100.0, -100.0]))
    assert p.s_phi(np.array([1e4]))[0] == pytest.approx(2.0 * 1e-10)
    # zero above f0/2, held flat below the grid
    assert p.s_phi(np.array([6e8]))[0] == 0.0
    assert p.s_phi(np.array([10.0]))[0] == pytest.approx(2.0 * 1e-10)


def test_rms_jitter_matches_flat_integral():
    p = ClockProfile(1e9, np.array([1e3, 1e6]), np.array([-100.0, -100.0]))
    var_phi = 2.0 * 1e-10 * (1e6 - 1e3)
    assert p.rms_jitter_s(1e3, 1e6) == pytest.approx(np.sqrt(var_phi) / (2 * np.pi * 1e9), rel=1e-9)
    assert p.s_timing(np.array([1e4]))[0] == pytest.approx(2e-10 / (2 * np.pi * 1e9) ** 2)


def test_shift_and_scale():
    p = ClockProfile.load(REPO / PROFILE)
    assert p.shifted(20.0).rms_jitter_s(1e3, 1e9) == pytest.approx(10 * p.rms_jitter_s(1e3, 1e9), rel=1e-9)
    assert p.scaled_to_rms(200e-15, 1e3).rms_jitter_s(1e3) == pytest.approx(200e-15, rel=1e-9)
    assert p.shifted(0.0) is p


def test_invalid_profiles_raise(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("f0_hz: 1e9\nf_hz: [100, 10]\nl_dbc_hz: [-90, -90]\n")
    with pytest.raises(ValueError, match="ascending"):
        ClockProfile.load(bad)
    bad.write_text("f0_hz: 1e9\nf_hz: [100, 1000]\nl_dbc_hz: [-90, -90]\nextra: 1\n")
    with pytest.raises(ValueError, match="unknown"):
        ClockProfile.load(bad)
    with pytest.raises(FileNotFoundError):
        ClockProfile.load(tmp_path / "missing.yaml")


def test_save_roundtrip(tmp_path):
    p = ClockProfile.load(REPO / PROFILE)
    q = ClockProfile.load(p.save(tmp_path / "copy.yaml"))
    assert np.allclose(q.l_dbc_hz, p.l_dbc_hz) and q.spurs == p.spurs
