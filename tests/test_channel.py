"""Channel and pulse response."""

import dataclasses

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


def test_single_ended_multiport_touchstone_carries_its_own_crosstalk(tmp_path):
    """A 2N-port single-ended file (ports 1..N near ends, N+1..2N far ends):
    the lane's through path reads 1 on a lossless matched line and the
    neighbours' coupling terms become the crosstalk pulses, reciprocal
    between lanes, with no behavioural shape imposed."""
    skrf = pytest.importorskip("skrf")
    from d2d_link.config import LaneConfig

    cfg = LinkConfig()
    f = ChannelModel.grid(cfg)[1:]
    beta = 2 * np.pi * f * np.sqrt(2.656e-7 * 1.063e-10)
    thru = np.exp(-1j * beta * 0.025)
    kx = 0.1 * (1j * f / cfg.f_nyquist) / (1 + 1j * f / cfg.f_nyquist)      # -20 dB at Nyquist, FEXT-shaped
    n = 3
    s = np.zeros((f.size, 2 * n, 2 * n), dtype=complex)
    for i in range(n):
        s[:, n + i, i] = s[:, i, n + i] = thru
        for j in range(n):
            if abs(i - j) == 1:
                s[:, n + i, j] = s[:, j, n + i] = kx * thru
            elif abs(i - j) == 2:
                s[:, n + i, j] = s[:, j, n + i] = 0.3 * kx * thru
    path = tmp_path / "lanes"
    skrf.Network(f=f, s=s, z0=50.0, f_unit="Hz").write_touchstone(str(path), form="ri")
    file = str(path) + ".s6p"
    mid = LinkConfig(channel=ChannelConfig(kind="touchstone", file=file, touchstone_mode="single_ended", lane=1,
                                           xtalk="touchstone"), lanes=LaneConfig(count=3))
    ch = ChannelModel.from_config(mid)
    k = int(np.argmin(np.abs(ch.f - cfg.f_nyquist)))
    assert np.allclose(np.abs(ch.H[1:-1]), 1.0, atol=0.02) and sorted(ch.xtalk_H) == [1]
    assert abs(ch.xtalk_H[1][k]) == pytest.approx(0.1 / np.sqrt(2.0), rel=0.02)          # |kx| at Nyquist
    edge = ChannelModel.from_config(dataclasses.replace(mid, channel=dataclasses.replace(mid.channel, lane=0)))
    assert sorted(edge.xtalk_H) == [1, 2] and abs(edge.xtalk_H[2][k]) == pytest.approx(0.03 / np.sqrt(2.0), rel=0.02)
    assert np.allclose(edge.xtalk_H[1], ch.xtalk_H[1])                                     # reciprocal coupling
    r = link_response(mid)
    assert sorted(r.xtalk_pulses) == [1] and 0.03 < np.max(np.abs(r.xtalk_pulses[1].y)) / r.main_amplitude < 0.1
    with pytest.raises(ValueError, match="single-ended"):
        ChannelConfig(kind="touchstone", file=file, xtalk="touchstone")
    with pytest.raises(ValueError, match="2N"):
        ChannelModel.from_touchstone_single_ended(file, ChannelModel.grid(cfg), 50.0, 50.0, 0, n_lanes=4)


def test_touchstone_channels_have_no_dc_notch(tmp_path):
    """The file has no DC point and the interpolation fills transmission
    outside its band with 0: without fill_dc the through path read H(0) = 0,
    a notch that hung a long negative tail on the pulse (a 182 mV eye read
    60 mV in example 08's first draft). Both readers carry the lowest in-band
    magnitude to DC; the pulse's cursor sum then matches the lossy line's."""
    skrf = pytest.importorskip("skrf")
    from d2d_link.channel.model import fill_dc
    from d2d_link.config import LaneConfig

    cfg = LinkConfig(channel=ChannelConfig(length_mm=25.0))
    ana = ChannelModel.from_config(cfg)
    f = ana.f[1:]
    n = 2
    s = np.zeros((f.size, 2 * n, 2 * n), dtype=complex)
    for i in range(n):
        s[:, n + i, i] = s[:, i, n + i] = ana.H[1:]
    path = tmp_path / "lossy"
    skrf.Network(f=f, s=s, z0=50.0, f_unit="Hz").write_touchstone(str(path), form="ri")
    se = LinkConfig(channel=ChannelConfig(kind="touchstone", file=str(path) + ".s4p", touchstone_mode="single_ended",
                                          coupled_length_mm=25.0), lanes=LaneConfig(count=2))
    ch = ChannelModel.from_config(se)
    assert abs(ch.H[0]) == pytest.approx(abs(ana.H[0]), rel=2e-3) and ch.H[0].imag == 0.0   # sqrt(f) extrapolation to DC
    assert np.allclose(np.abs(ch.H[1:-1]), np.abs(ana.H[1:-1]), rtol=1e-3)
    r_file, r_ana = link_response(se), link_response(cfg)
    assert np.sum(r_file.cursors(0.0)[0]) == pytest.approx(np.sum(r_ana.cursors(0.0)[0]), rel=2e-3)
    assert r_file.main_amplitude == pytest.approx(r_ana.main_amplitude, rel=2e-3)
    # the differential reader goes through the same fill (its port order is 1+, 2+, 1-, 2-: through = 0 -> 1, 2 -> 3)
    sd = np.zeros_like(s)
    sd[:, 1, 0] = sd[:, 0, 1] = sd[:, 3, 2] = sd[:, 2, 3] = ana.H[1:]
    skrf.Network(f=f, s=sd, z0=50.0, f_unit="Hz").write_touchstone(str(tmp_path / "lossy_diff"), form="ri")
    diff = ChannelModel.from_config(LinkConfig(channel=ChannelConfig(kind="touchstone", file=str(tmp_path / "lossy_diff.s4p"),
                                                                     renumber=False)))
    assert diff.H[0] != 0.0 and abs(diff.H[0]) == pytest.approx(abs(ana.H[0]), rel=2e-3)
    h = np.array([0.0, 0.5 + 0.1j, 0.4]); assert abs(fill_dc(h, np.array([0.0, 1.0, 2.0]))[0]) >= abs(0.5 + 0.1j)
    assert fill_dc(np.array([0.9, 0.5, 0.4]), np.array([0.0, 1.0, 2.0]))[0] == 0.9           # a file with DC is left alone
    assert fill_dc(np.array([0.0, 0.5, 0.6]), np.array([0.0, 1.0, 2.0]))[0] == 0.5           # rising: no extrapolation, the lowest point

