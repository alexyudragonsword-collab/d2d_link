"""Channel and pulse response."""

import numpy as np
import pytest

from d2d_link.channel import ChannelModel, link_response
from d2d_link.channel.model import ctle_response
from d2d_link.config import ChannelConfig, CtleConfig, LinkConfig, RxConfig


def _lossless(length_mm=25.0):
    return LinkConfig(channel=ChannelConfig(length_mm=length_mm, rdc_ohm_m=0.0, r_skin=0.0,
                                            loss_tangent=0.0, g_s_m=0.0, l_h_m=2.5e-7, c_f_m=1.0e-10))


def test_lossless_matched_line_is_unity():
    ch = ChannelModel.from_config(_lossless())
    assert np.allclose(np.abs(ch.H), 1.0, atol=1e-9)
    assert ch.insertion_loss_db(16e9) == pytest.approx(0.0, abs=1e-6)


def test_loss_grows_with_length_and_frequency():
    il = [ChannelModel.from_config(LinkConfig(channel=ChannelConfig(length_mm=L))).insertion_loss_db(16e9)
          for L in (5.0, 15.0, 25.0)]
    assert il[0] > il[1] > il[2]
    ch = ChannelModel.from_config(LinkConfig())
    assert ch.insertion_loss_db(16e9) < ch.insertion_loss_db(4e9) < 0.0
    # the standard-package preset at the survey reach: a few dB at Nyquist
    assert -6.0 < il[2] < -1.5


def test_pulse_amplitude_and_cursor_sum():
    cfg = LinkConfig()
    r = link_response(cfg)
    c, i_main = r.cursors(0.0)
    assert c[i_main] == pytest.approx(r.main_amplitude)
    # the cursors sum to the DC response times the symbol amplitude
    dc = abs(r.channel.H[0]) * 0.5 * cfg.tx.swing_vpp
    assert np.sum(c) == pytest.approx(dc, rel=0.02)
    assert r.main_amplitude < 0.5 * cfg.tx.swing_vpp
    assert r.cursors(0.5)[0].size >= 3


def test_lossless_pulse_is_the_symbol_amplitude():
    # a brick-wall band edge rings (Gibbs), so the peak overshoots a little;
    # the cursors still sum to the symbol amplitude exactly
    r = link_response(_lossless(5.0))
    c, _ = r.cursors(0.0)
    assert np.sum(c) == pytest.approx(0.5 * 0.4, rel=0.01)   # sinc tails beyond +-64 UI
    assert r.main_amplitude == pytest.approx(0.5 * 0.4, rel=0.15)


def test_ctle_unity_dc_and_peaking():
    cfg = LinkConfig(rx=RxConfig(ctle=CtleConfig(enable=True, peak_db=4.0)))
    f = np.array([0.0, cfg.f_nyquist])
    h = np.abs(ctle_response(cfg, f))
    assert h[0] == pytest.approx(1.0)
    assert 1.0 < 20 * np.log10(h[1]) < 4.0      # peak_db is the asymptote, not the boost at fp1
    assert np.all(ctle_response(LinkConfig(), f) == 1.0)


def test_grid_matches_waveform_step():
    cfg = LinkConfig()
    r = link_response(cfg)
    assert r.pulse.dt == pytest.approx(cfg.dt, rel=1e-9)


def test_touchstone_path_through_vendored_reader(tmp_path):
    skrf = pytest.importorskip("skrf")
    # a lossless matched differential line written as a 4-port single-ended file
    cfg = _lossless(10.0)
    f = ChannelModel.grid(cfg)[1:]
    z0 = 50.0
    beta = 2 * np.pi * f * np.sqrt(2.5e-7 * 1.0e-10)
    s = np.zeros((f.size, 4, 4), dtype=complex)
    thru = np.exp(-1j * beta * 0.010)
    s[:, 0, 1] = s[:, 1, 0] = thru     # +A -> +B
    s[:, 2, 3] = s[:, 3, 2] = thru     # -A -> -B
    ntwk = skrf.Network(f=f, s=s, z0=z0, f_unit="Hz")
    path = tmp_path / "line.s4p"
    ntwk.write_touchstone(str(path.with_suffix("")), form="ri")
    cfg2 = LinkConfig(channel=ChannelConfig(kind="touchstone", file=str(path), renumber=False))
    ch = ChannelModel.from_config(cfg2)
    assert np.allclose(np.abs(ch.H[1:-1]), 1.0, atol=0.02)
