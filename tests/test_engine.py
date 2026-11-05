import math
from datetime import datetime

import numpy as np
import pytest
import spiceypy as sp

import make_mock_kernels as mock
from simbio_utility.core import geometry, instruments, seasons, timeconv
from simbio_utility.core.errors import TimeParseError, UtilityError

HRIC = "MPO_SIMBIO-SYS_HRIC_FPAN"
STCH = "MPO_SIMBIO-SYS_STC-H_P700"
STCL = "MPO_SIMBIO-SYS_STC-L_P700"
ET = lambda s: timeconv.utc_to_et(s)  # noqa: E731


def test_metakernel_relative_paths(session):
    assert session.loaded and session.info.total == 5


def test_time_roundtrip(session):
    et = ET("2027-04-06T07:48:34.000")
    assert timeconv.et_to_utc(et, 3) == "2027-04-06T07:48:34.000"
    assert timeconv.et_to_utc_doy(et, 0) == "2027-096T07:48:34"
    assert ET("2027-04-06 T07:48:34.000") == et and ET("2027-04-06T07:48:34Z") == et
    assert ET("2027 APR 06 07:48:34") == et
    # independent check: elapsed UTC seconds since J2000(UTC=11:58:55.816) + 5 leap seconds since 2000 (TDB ~ TT)
    elapsed = (datetime(2027, 4, 6, 7, 48, 34) - datetime(2000, 1, 1, 11, 58, 55, 816000)).total_seconds()
    assert et == pytest.approx(elapsed + 5, abs=0.01)
    with pytest.raises(TimeParseError):
        ET("not a time")


def test_camera_discovery(session):
    cams = {c.name: c for c in instruments.discover_cameras()}
    assert set(cams) == {STCH, STCL, HRIC, "MPO_SIMBIO-SYS_STC-H_F420"}
    assert cams[STCH].channel == "STC-H" and cams[STCH].filter == "P700"
    assert cams[HRIC].channel == "HRIC" and cams[HRIC].filter == "FPAN"


def test_whole_stc_not_listed(monkeypatch):
    names = ["MPO_SIMBIO-SYS_STC_FPA", "MPO_SIMBIO-SYS_STC-FPA_FPA", "MPO_SIMBIO-SYS_STC_P700", "MPO_SIMBIO-SYS_STC-H_P700", "MPO_SIMBIO-SYS_STC-L_P700", "MPO_SIMBIO-SYS_HRIC_FPAN"]
    monkeypatch.setattr(instruments, "_pool_camera_names", lambda: names)
    cams = instruments.discover_cameras()
    assert [c.channel for c in cams] == ["HRIC", "STC-H", "STC-L"]


def test_nadir_camera_matches_analytic_orbit(session):
    et = ET("2027-06-20T12:00:00")
    g = geometry.compute(HRIC, et)
    r = mock.R_MERCURY + mock.ALT_KM
    assert g.altitude_km == pytest.approx(mock.ALT_KM, abs=0.1)
    assert g.emission_deg < 0.01
    assert g.orbital_velocity_kms == pytest.approx(math.sqrt(mock.GM_MERCURY / r), rel=1e-3)
    assert g.resolution_m_px == pytest.approx(mock.ALT_KM * 1e3 * 10e-6 / 0.8, rel=1e-3)  # 5.0 m/px
    assert g.lat_deg == pytest.approx(g.sc_lat_deg, abs=1e-3) and g.lon_deg == pytest.approx(g.sc_lon_deg, abs=1e-3)
    assert g.phase_deg == pytest.approx(g.incidence_deg, abs=0.01)  # nadir -> phase == incidence


@pytest.mark.parametrize("cam,tilt", [(STCH, 20.0), (STCL, -20.0)])
def test_tilted_camera_matches_sphere_geometry(session, cam, tilt):
    et = ET("2027-06-20T12:00:00")
    g = geometry.compute(cam, et)
    r, R, th = mock.R_MERCURY + mock.ALT_KM, mock.R_MERCURY, math.radians(abs(tilt))
    slant = r * math.cos(th) - math.sqrt(R * R - (r * math.sin(th)) ** 2)
    emission = math.degrees(math.asin(r / R * math.sin(th)))
    assert g.slant_range_km == pytest.approx(slant, rel=2e-4)
    assert g.emission_deg == pytest.approx(emission, abs=0.01)
    ifov = 10e-6 / 0.095
    assert g.resolution_m_px == pytest.approx(slant * 1e3 * ifov / math.cos(math.radians(emission)), rel=2e-4)


def test_incidence_and_azimuth_independent_check(session):
    """Recompute incidence/azimuth from lat/lon + sun vector with a different formulation."""
    for utc in ("2027-06-20T12:00:00", "2027-06-27T03:10:00", "2027-07-05T18:45:00"):
        et = ET(utc)
        g = geometry.compute(STCH, et)
        lat, lon = math.radians(g.lat_deg), math.radians(g.lon_deg)
        up = np.array([math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)])
        east = np.array([-math.sin(lon), math.cos(lon), 0.0])
        north = np.cross(up, east)
        sun, _ = sp.spkpos("SUN", et, "IAU_MERCURY", "LT+S", "MERCURY")
        s = np.asarray(sun) - mock.R_MERCURY * up
        s /= np.linalg.norm(s)
        assert g.incidence_deg == pytest.approx(math.degrees(math.acos(s @ up)), abs=0.05)
        az = math.degrees(math.atan2(s @ east, s @ north)) % 360
        assert abs((g.azimuth_deg - az + 180) % 360 - 180) < 0.05


def test_night_side_reported(session):
    t0 = ET(mock.MPO_COVERAGE[0]) + 3600.0  # LT+S needs data slightly before the epoch
    nights = [geometry.compute(HRIC, t0 + k * 600.0) for k in range(0, 60)]
    assert any(g.is_night for g in nights) and any(not g.is_night for g in nights)
    assert all(0 <= g.azimuth_deg < 360 for g in nights)


def test_outside_spk_coverage_raises_clean_error(session):
    with pytest.raises(UtilityError):
        geometry.compute(HRIC, ET("2027-03-01T00:00:00"))


def test_longitude_domain(session):
    et = ET("2027-06-20T12:00:00")
    lon360 = geometry.compute(HRIC, et, geometry.GeometrySettings(lon_domain="360")).lon_deg
    lon180 = geometry.compute(HRIC, et).lon_deg
    assert 0 <= lon360 < 360 and (lon360 - lon180) % 360 == pytest.approx(0, abs=1e-9)


# ---- seasons -------------------------------------------------------------------------------------
@pytest.mark.parametrize("utc,label", [
    ("2027-03-22T08:00:00", "APH0"), ("2027-04-20T00:00:00", "D2N0"), ("2027-05-05T08:00:00", "PER0"),
    ("2027-05-25T00:00:00", "N2D0"), ("2027-06-18T07:00:00", "APH1"), ("2027-07-15T00:00:00", "D2N1"),
    ("2027-08-01T07:00:00", "PER1"), ("2027-08-20T00:00:00", "N2D1"), ("2027-09-14T06:00:00", "APH2"),
    ("2027-03-01T00:00:00", "N2D-1"), ("2027-10-28T00:00:00", "PER2"), ("2027-12-01T00:00:00", "APH3"),
])
def test_season_labels_from_spice_mta(session, utc, label):
    et = ET(utc)
    mta, ecc = geometry.mercury_true_anomaly(et)
    cfg = seasons.SeasonConfig()
    assert seasons.classify(mta, ecc, et, ET(cfg.epoch_utc), cfg).label == label


def test_mta_is_180_at_aphelion_epoch(session):
    mta, ecc = geometry.mercury_true_anomaly(ET(mock.APH0_UTC))
    assert mta == pytest.approx(180.0, abs=1e-6) and ecc == pytest.approx(0.20563, abs=1e-4)


def test_season_boundaries_and_unwrapping():
    cfg, ecc = seasons.SeasonConfig(), 0.2056
    et0, year = 0.0, 87.9693 * 86400
    ok = lambda ta, t: seasons.classify(ta, ecc, t, et0, cfg).label  # noqa: E731
    assert ok(134.99, et0 - 0.3 * year) == "N2D-1" and ok(135.0, et0 - 0.25 * year) == "APH0"
    assert ok(224.99, et0 + 0.1 * year) == "APH0" and ok(225.0, et0 + 0.1 * year) == "D2N0"
    assert ok(315.0, et0 + 0.5 * year) == "PER0" and ok(45.0, et0 + 0.8 * year) == "N2D0"
    assert ok(180.0, et0 + 10 * year) == "APH10"
    # year counter survives a slightly wrong period (1 minute per orbit)
    assert ok(180.0, et0 + 10 * (year + 60)) == "APH10"


def test_mtp_stp_in_geometry_result(session):
    from simbio_utility.core.stp import StpTable
    from pathlib import Path
    table = StpTable.from_file(Path(__file__).parent.parent / "simbio_utility" / "resources" / "stp_default.evf")
    et = ET("2027-06-20T12:00:00")
    g = geometry.compute(HRIC, et, geometry.GeometrySettings(stp=table))
    assert (g.stp, g.mtp, g.stp_in_mtp, g.plan_label) == (15, 4, 3, "MTP4 · STP15")
    assert "2027-06-20 03:18:06" in g.stp_window
    assert geometry.compute(HRIC, et).mtp is None  # no timeline configured -> not reported
