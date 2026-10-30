from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from simbio_utility.core import dtm, stp
from simbio_utility.core.errors import UtilityError

EVF = Path(__file__).parent.parent / "simbio_utility" / "resources" / "stp_default.evf"
D = datetime.fromisoformat


@pytest.fixture(scope="module")
def table():
    return stp.StpTable.from_file(EVF)


def test_builtin_evf_parses(table):
    assert len(table) == 147 and table.n_mtp == 37
    assert table.span == (D("2027-03-14 02:43:52"), D("2029-12-31 00:00:00"))


@pytest.mark.parametrize("stp_n,mtp,k", [(1, 1, 1), (4, 1, 4), (5, 2, 1), (8, 2, 4), (9, 3, 1), (147, 37, 3)])
def test_mtp_is_four_stps(table, stp_n, mtp, k):
    i = table.info(stp_n)
    assert (i.mtp, i.stp_in_mtp) == (mtp, k)


@pytest.mark.parametrize("utc,stp_n", [
    ("2027-03-14 02:43:52", 1),            # first instant of STP1
    ("2027-03-21 10:42:12", 1),            # last second of STP1
    ("2027-03-21 10:42:13", 2),            # boundary belongs to the next STP
    ("2027-04-11 10:59:33.5", 4),          # END(4)=10:59:33 ... START(5)=10:59:34 : 1 s gap
    ("2027-04-11 10:59:34", 5),
    ("2027-06-20 12:00:00", 15),
    ("2029-12-30 23:59:59", 147),
])
def test_lookup(table, utc, stp_n):
    assert table.lookup(D(utc)).stp == stp_n


def test_lookup_outside(table):
    assert table.lookup(D("2027-03-14 02:43:51")) is None
    assert table.lookup(D("2029-12-31 00:00:00")) is None
    assert table.lookup(D("2025-01-01 00:00:00")) is None


def test_rejects_garbage_and_custom_mtp_size():
    with pytest.raises(UtilityError):
        stp.StpTable.from_text("nothing useful here")
    t = stp.StpTable.from_text("01-Jan-2030_00:00:00 STP_START (COUNT = 1)\n02-Jan-2030_00:00:00 STP_END (COUNT = 1)\n"
                               "02-Jan-2030_00:00:00 STP_START (COUNT = 2)\n03-Jan-2030_00:00:00 STP_END (COUNT = 2)", stps_per_mtp=1)
    assert t.info(2).mtp == 2


# ---- DTM resampling -----------------------------------------------------------------------------
def test_resample_noop_when_not_coarser():
    z = np.random.default_rng(0).normal(size=(40, 50)).astype(np.float32)
    z2, ps = dtm.resample_to_pixel_size(z, 5.0, 5.0)
    assert z2 is z and ps == 5.0
    z3, ps3 = dtm.resample_to_pixel_size(z, 5.0, 2.0)  # finer than the data: unchanged
    assert z3 is z and ps3 == 5.0


@pytest.mark.parametrize("res", [10.0, 12.5, 49.39, 75.0])
def test_resample_geometry_and_ramp(res):
    n, ps = 400, 5.0
    ramp = (np.arange(n, dtype=np.float32) * ps * 0.2)[None, :].repeat(n, 0)  # 0.2 m rise per metre east
    z, used = dtm.resample_to_pixel_size(ramp, ps, res)
    assert used == res
    assert z.shape[1] == pytest.approx(n * ps / res, abs=2)
    # slope in the new grid must still be 0.2 (interior, away from edge handling)
    slope = np.diff(z[z.shape[0] // 2, 2:-3]) / res
    assert np.allclose(slope, 0.2, atol=0.01)


def test_resample_averages_small_features():
    z = np.zeros((200, 200), np.float32)
    z[::2, ::2] = 10.0  # 1-pixel pits/peaks: unresolvable at 20 m when pixels are 5 m
    out, _ = dtm.resample_to_pixel_size(z, 5.0, 20.0)
    assert out.std() < 0.5 and out.mean() == pytest.approx(z.mean(), rel=0.05)


def test_example_dtm_native_and_fit():
    d = dtm.load_dtm(Path(__file__).parent.parent / "simbio_utility" / "resources" / "exampleDTM.tif", max_dim=0)
    assert d.shape == (1554, 2363) and d.pixel_size_m == pytest.approx(5.0, rel=1e-3)
    z, ps = dtm.fit_max_dim(d.z, d.pixel_size_m, 1400)
    assert max(z.shape) <= 1400 and ps == pytest.approx(10.0, rel=1e-3)
