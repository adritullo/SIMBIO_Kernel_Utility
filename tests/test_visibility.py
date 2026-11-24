import math

import numpy as np
import pytest

from simbio_utility.core import geometry, visibility
from simbio_utility.core.errors import UtilityError
from simbio_utility.core.ltp import load_ltps, parse_ltps
from simbio_utility.core.timeconv import utc_to_et as ET

@pytest.fixture(scope="module")
def session(tmp_path_factory):
    """Own kernel load: the GUI tests (which run earlier) clear the global SPICE pool when their window closes."""
    import make_mock_kernels as mock
    from simbio_utility.core.kernels import KernelSession
    ks = KernelSession()
    ks.load(mock.build(tmp_path_factory.mktemp("vis_kernels")))
    yield ks
    ks.unload()


HRIC = "MPO_SIMBIO-SYS_HRIC_FPAN"
STCH = "MPO_SIMBIO-SYS_STC-H_P700"


def test_ltp_file():
    ltps = load_ltps()
    assert sorted(ltps) == [1, 2, 3, 4]
    assert ltps[1].start_utc == "2027-03-14T02:43:52" and ltps[1].end_utc == "2027-07-04T02:42:27"
    assert ltps[2].start == ltps[1].end and ltps[4].end_utc == "2029-12-31T00:00:00"
    assert ltps[1].stps == (1, 16) and ltps[1].mtps == (1, 4)
    with pytest.raises(UtilityError):
        parse_ltps("# nothing here\n")


def _brute(search: visibility.PositionSearch, et0, et1, dt):
    """Reference: test every epoch on a dense grid."""
    inside = [t for t in np.arange(et0, et1, dt) if search._in_fov(t) is not None]
    passes, cur = [], []
    for t in inside:
        if cur and t - cur[-1] > 1.5 * dt:
            passes.append((cur[0], cur[-1]))
            cur = []
        cur.append(t)
    if cur:
        passes.append((cur[0], cur[-1]))
    return passes


@pytest.mark.parametrize("cam,offset_deg", [(HRIC, 0.0), (HRIC, 0.06), (STCH, 0.0), (STCH, 0.4)])
def test_finds_the_same_passes_as_a_dense_scan(session, cam, offset_deg):
    et = ET("2027-06-20T12:00:00")
    g = geometry.compute(cam, et)
    lat, lon = g.lat_deg, g.lon_deg + offset_deg  # a cross-track offset: the point crosses the FOV off-centre
    et0, et1 = et - 2 * 3600, et + 2 * 3600
    s = visibility.PositionSearch(cam, lat, lon, et0, et1, sunlit_only=False)
    res = s.run()
    ref = _brute(visibility.PositionSearch(cam, lat, lon, et0, et1, sunlit_only=False), et0, et1, 0.2)
    assert ref, "the reference scan must see the point"
    assert len(res.passes) == len(ref)
    for p, (a, b) in zip(res.passes, ref):
        assert abs(p.start_et - a) < s._fine_step + 0.2 and abs(p.end_et - b) < s._fine_step + 0.2
        assert p.start_et <= p.best.et <= p.end_et


def test_central_pixel_is_found_at_the_right_time_with_its_geometry(session):
    et = ET("2027-06-20T12:00:00")
    g = geometry.compute(HRIC, et)
    res = visibility.PositionSearch(HRIC, g.lat_deg, g.lon_deg, et - 3600, et + 3600).run()
    assert len(res.passes) == 1
    p = res.passes[0]
    assert p.start_et - 1 <= et <= p.end_et + 1
    assert p.best.resolution_m_px == pytest.approx(g.resolution_m_px, rel=0.02)
    assert p.best.incidence_deg == pytest.approx(g.incidence_deg, abs=0.5)
    row = p.row()
    assert row["lit"] and row["start_utc"].startswith("2027-06-20T11:59")


def test_night_side_passes_are_hidden_when_sunlit_only(session):
    import make_mock_kernels as mock
    r = mock.R_MERCURY + mock.ALT_KM
    half_orbit = math.pi * math.sqrt(r ** 3 / mock.GM_MERCURY)
    et = ET("2027-06-20T12:00:00") + half_orbit  # half an orbit after a dayside pass: night side
    g = geometry.compute(HRIC, et)
    assert g.incidence_deg > 90
    lat, lon = g.lat_deg, g.lon_deg
    all_p = visibility.PositionSearch(HRIC, lat, lon, et - 3600, et + 3600, sunlit_only=False).run()
    lit = visibility.PositionSearch(HRIC, lat, lon, et - 3600, et + 3600, sunlit_only=True).run()
    assert all_p.passes and all(not p.lit for p in all_p.passes)
    assert not lit.passes and lit.dark_passes == len(all_p.passes)


def test_ranges_without_ephemeris_are_skipped_and_reported(session):
    # the mock MPO ephemeris covers 2027-06-15 .. 07-15 only
    et0, et1 = ET("2027-06-10T00:00:00"), ET("2027-06-16T00:00:00")
    res = visibility.PositionSearch(HRIC, 10.0, 20.0, et0, et1).run()
    assert res.no_ephemeris_s > 4 * 86400
    assert "without spacecraft ephemeris" in res.summary()


def test_cancel_and_validation(session):
    et = ET("2027-06-20T12:00:00")
    s = visibility.PositionSearch(HRIC, 0.0, 0.0, et, et + 86400)
    n = {"k": 0}

    def cancel():
        n["k"] += 1
        return n["k"] > 20

    assert s.run(cancel).cancelled
    with pytest.raises(UtilityError):
        visibility.PositionSearch(HRIC, 0.0, 0.0, et, et - 1)
    with pytest.raises(UtilityError):
        visibility.PositionSearch(HRIC, 95.0, 0.0, et, et + 1)
    with pytest.raises(UtilityError):
        visibility.PositionSearch("NOPE", 0.0, 0.0, et, et + 1)


def test_surface_point_on_the_ellipsoid():
    p = visibility.surface_point(30.0, 45.0, np.array([2440.0, 2440.0, 2440.0]))
    assert np.linalg.norm(p) == pytest.approx(2440.0)
    assert math.degrees(math.asin(p[2] / 2440.0)) == pytest.approx(30.0)
