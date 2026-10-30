import csv
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

import make_mock_kernels as mock  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def spin(app, ms):
    t = time.time()
    while time.time() - t < ms / 1000:
        app.processEvents()
        time.sleep(0.005)


@pytest.fixture(scope="module")
def win(tmp_path_factory):
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path_factory.mktemp("cfg"))
    from simbio_utility.gui.main_window import MainWindow
    from simbio_utility.gui.theme import apply_theme
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    w = MainWindow()
    w.show()
    mk = mock.build(tmp_path_factory.mktemp("k"))
    w.path.setText(str(mk))
    w.load()
    spin(app, 1500)
    yield w, app
    w.close()


def test_load_and_time_card(win):
    w, app = win
    assert w.session.loaded and w.pill.text().startswith("●")
    tc = w.time_card
    tc.a.inp.setText("2027-06-20T12:00:00")
    tc.b.inp.setText("not a number")
    spin(app, 500)
    assert tc.a.rows[0].value.text() == "866764869.184420"
    assert tc.b.err.isVisibleTo(tc) and "not a number" in tc.b.err.text()
    tc.b.inp.setText("866764869.184420")
    spin(app, 500)
    assert tc.b.rows[0].value.text() == "2027-06-20T12:00:00.000"


def test_geometry_card_compute_and_errors(win, tmp_path):
    w, app = win
    g = w.geo_card
    assert g.channel.count() == 3 and g.filter.currentData() is not None
    g.time_in.setText("garbage")
    g.compute()
    assert g.error.isVisibleTo(g) and g.result is None
    g.time_in.setText("2027-03-01T00:00:00")  # outside the MPO SPK coverage
    g.compute()
    assert g.error.isVisibleTo(g) and g.result is None
    g.mode.set_index(1)
    g.time_in.setText("866764869.184420")
    g.compute()
    spin(app, 2500)
    assert g.result is not None and g.result.season == "APH1"
    assert g.tiles["incidence_deg"].value.text() == f"{g.result.incidence_deg:.3f}"
    assert "APH1" in g.season.text() and g.btn_png.isEnabled()
    assert "not the Mercury surface" in g.hs_caption.text()
    out = tmp_path / "x.csv"
    rows = g._rows()
    with open(out, "w", newline="") as fh:
        csv.writer(fh).writerows(rows)
    assert any(r[0] == "Season" and r[1] == "APH1" for r in rows)


def test_hillshade_flag_off_hides_panel(win):
    w, app = win
    g = w.geo_card
    g.chk_hs.setChecked(False)
    assert not g.hs_panel.isVisibleTo(g)
    g.chk_hs.setChecked(True)
    assert g.hs_panel.isVisibleTo(g)
    spin(app, 1500)


def test_time_step_arrows(win):
    w, app = win
    g = w.geo_card
    g.mode.set_index(0)
    g.time_in.setText("2027-06-20T12:00:00")
    g.compute()
    spin(app, 300)
    base = g.result.et
    plus = {s: b for b, s in g.step_btns}
    plus[1.0].click()
    assert g.time_in.text() == "2027-06-20T12:00:01.000" and g.result.et == pytest.approx(base + 1, abs=1e-5)
    plus[60.0].click()
    assert g.time_in.text() == "2027-06-20T12:01:01.000" and g.result.et == pytest.approx(base + 61, abs=1e-5)
    plus[3600.0].click()
    assert g.time_in.text() == "2027-06-20T13:01:01.000" and g.result.et == pytest.approx(base + 3661, abs=1e-5)
    plus[-3600.0].click()
    plus[-60.0].click()
    plus[-1.0].click()
    assert g.time_in.text() == "2027-06-20T12:00:00.000" and g.result.et == pytest.approx(base, abs=1e-5)
    g.mode.set_index(1)
    g.time_in.setText("866764869.184420")
    plus[1.0].click()
    assert g.time_in.text() == "866764870.184420"
    g.mode.set_index(0)


def test_mission_plan_tile_and_scaled_hillshade(win):
    w, app = win
    g = w.geo_card
    g.mode.set_index(0)
    g.time_in.setText("2027-06-20T12:00:00")
    g.chk_hs.setChecked(True)
    g.chk_scale.setChecked(True)
    g.compute()
    spin(app, 2500)
    assert g.t_plan.value.text() == "MTP4 · STP15"
    assert "rescaled to the instrument ground resolution" in g.hs_caption.text()
    assert "(2.5 m/px" not in g.hs_caption.text() and g.view._qimg.width() < 400  # ~49 m/px -> ~240 px wide
    g.chk_scale.setChecked(False)
    spin(app, 2500)
    assert "not scaled to the instrument" in g.hs_caption.text() and g.view._qimg.width() > 1000
    g.chk_scale.setChecked(True)
    spin(app, 800)


def test_version_label(win):
    from PySide6.QtWidgets import QLabel
    w, _ = win
    assert any(l.text() == "v0.2.0 by a.tullo" for l in w.findChildren(QLabel))
