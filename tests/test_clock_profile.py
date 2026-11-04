"""The pll_simulator profile file: conventions pinned."""

import numpy as np
import pytest

from conftest import PROFILE
from d2d_link.clock.forwarded import resolve_data_file
from d2d_link.clock.profile import ClockProfile


def test_load_shipped_profile():
    p = ClockProfile.load(resolve_data_file(PROFILE))
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
    p = ClockProfile.load(resolve_data_file(PROFILE))
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
    p = ClockProfile.load(resolve_data_file(PROFILE))
    q = ClockProfile.load(p.save(tmp_path / "copy.yaml"))
    assert np.allclose(q.l_dbc_hz, p.l_dbc_hz) and q.spurs == p.spurs


def test_profile_to_nyquist_matches_the_floor_reading():
    """pll_simulator's exporter stops at f0/2 (5.12 GHz for the 10.24 GHz
    Markulic PLL); the link integrates to fs/2 = 16 GHz. The same model
    analysed to 16 GHz (tools/export_profile_to_nyquist.py) is flat at its
    VCO floor there -- -145.00 dBc/Hz, every other term below -175 -- so the
    0.13.0 ``profile_above: floor`` reading is the model, and ``zero`` is
    only the format's cut: read through the 16 GHz file, both readings give
    the bundled floor budget to 0.01 %."""
    import dataclasses

    from conftest import REPO
    from d2d_link.clock.forwarded import ForwardedClock
    from d2d_link.config import load_config

    to16 = {"pll_profile": "data/clock_profiles/bench_markulic16_sspll_40m_10p24g_to16g.yaml",
            "local_pll_profile": "data/clock_profiles/bench_wu19_spll_frac_52m_6p253g_to16g.yaml"}
    for key, floor_dbc in (("pll_profile", -145.0), ("local_pll_profile", -154.0)):
        p = ClockProfile.load(resolve_data_file(to16[key]))
        top = p.f_hz >= 1e9
        assert p.f_hz[-1] == pytest.approx(16e9) and np.all(np.abs(p.l_dbc_hz[top] - floor_dbc) < 0.05)
    for cfg_name, keys in (("standard_32g_x1", ("pll_profile",)), ("standard_32g_x16_module", ("pll_profile", "local_pll_profile"))):
        cfg = load_config(REPO / "configs" / f"{cfg_name}.yaml")
        ref = ForwardedClock(cfg).budget()                       # the f0/2 files, floor reading
        for reading in ("floor", "zero"):
            kw = {k: to16[k] for k in keys}
            b = ForwardedClock(dataclasses.replace(cfg, clocking=dataclasses.replace(
                cfg.clocking, profile_above=reading, **kw))).budget()
            assert b.common_leak_s == pytest.approx(ref.common_leak_s, rel=2e-4), (cfg_name, reading)
            assert b.total_s == pytest.approx(ref.total_s, rel=1e-4), (cfg_name, reading)
    zero = ForwardedClock(dataclasses.replace(cfg, clocking=dataclasses.replace(cfg.clocking, profile_above="zero"))).budget()
    assert zero.common_leak_s < 0.75 * ref.common_leak_s       # the f0/2 file read with zero drops what the model has
