from pathlib import Path

import numpy as np
import pytest

from simbio_utility.core import dtm, hillshade

EXAMPLE = Path(__file__).parent.parent / "simbio_utility" / "resources" / "exampleDTM.tif"


def _ramp(az_dir):
    """Plane tilted 30 deg, facing ``az_dir`` (deg clockwise from N): z rises opposite to it."""
    n, ps = 80, 10.0
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    east, north = xx * ps, -yy * ps
    a = np.radians(az_dir)
    return (-(east * np.sin(a) + north * np.cos(a)) * np.tan(np.radians(30))).astype(np.float32), ps


def test_sun_facing_slope_is_brighter_than_flat_than_away_slope():
    z, ps = _ramp(90)  # slope faces east
    sun_east = hillshade.compute(z, ps, 90, 60, cast_shadows=False, stretch=False).image.mean()
    flat = hillshade.compute(np.zeros_like(z), ps, 90, 60, cast_shadows=False, stretch=False).image.mean()
    sun_west = hillshade.compute(z, ps, 270, 60, cast_shadows=False, stretch=False).image.mean()
    assert sun_east > flat > sun_west
    # analytic: flat = cos(60)=0.5, east-facing 30deg slope with sun at 60 incidence -> cos(60-30)
    assert flat / 255 == pytest.approx(0.03 + 0.97 * 0.5, abs=0.01)
    assert sun_east / 255 == pytest.approx(0.03 + 0.97 * np.cos(np.radians(30)), abs=0.01)


def test_night_is_black_and_flagged():
    z, ps = _ramp(0)
    h = hillshade.compute(z, ps, 10, 95)
    assert h.night and h.image.max() == 0


def test_cast_shadow_behind_a_ridge():
    z = np.zeros((60, 200), np.float32)
    z[:, 100] = 50.0  # N-S ridge 50 m high, 10 m pixels
    h = hillshade.compute(z, 10.0, 90.0, 80.0, cast_shadows=True, stretch=False)  # sun in the east, 10 deg elevation
    img = h.image.astype(int)
    shadow_len_px = 50 / np.tan(np.radians(10)) / 10  # ~28 px west of the ridge
    assert img[30, 100 - 15] < 20 and abs(img[30, 100 + 15] - 51) < 3  # shadowed west, lit east (0.03+0.97*cos80deg)
    assert abs(img[30, 100 - 45] - 51) < 3 and shadow_len_px > 20


def test_example_dtm_loads_and_renders():
    d = dtm.load_dtm(EXAMPLE)
    assert d.pixel_size_m == pytest.approx(10.0, rel=1e-3)  # 5 m native, 2x block-averaged
    assert d.z.shape[1] <= 1400 and 300 < d.relief_m < 500
    h = hillshade.compute(d.z, d.pixel_size_m, 250, 70)
    assert h.image.std() > 10 and h.image.shape == d.z.shape
