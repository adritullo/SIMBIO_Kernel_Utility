import csv
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

import make_mock_kernels as mock  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def wait_hillshade(g, app, timeout=15.0):
    """Wait until the hillshade worker has finished (caption no longer 'Rendering…')."""
    t = time.time()
    while time.time() - t < timeout:
        app.processEvents()
        if g.hs_caption.text() not in ("", "Rendering…"):
            break
        time.sleep(0.01)
    spin(app, 50)


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
    wait_hillshade(g, app)
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
    g.channel.setCurrentText("STC-H")  # do not depend on the channel left by other tests / saved settings
    g.mode.set_index(0)
    g.time_in.setText("2027-06-20T12:00:00")
    g.chk_hs.setChecked(True)
    g.chk_scale.setChecked(True)
    from simbio_utility.resources import resource_path
    g.dtm_path.setText(str(resource_path("exampleDTM_HRIC.tif")))  # fine DTM (5 m/px): scaling is visible
    g.compute()
    wait_hillshade(g, app)
    assert g.t_plan.value.text() == "MTP4 · STP15"
    assert "rescaled to the instrument ground resolution" in g.hs_caption.text()
    assert "(2.5 m/px" not in g.hs_caption.text() and g.view._qimg.width() < 400  # ~49 m/px -> ~240 px wide
    g.chk_scale.setChecked(False)
    wait_hillshade(g, app)
    assert "not scaled to the instrument" in g.hs_caption.text() and g.view._qimg.width() > 1000
    g.chk_scale.setChecked(True)
    spin(app, 800)


def test_version_label(win):
    from PySide6.QtWidgets import QLabel
    w, _ = win
    assert any(l.text() == "v0.3.0 by a.tullo" for l in w.findChildren(QLabel))


def test_dtm_follows_channel(win):
    from pathlib import Path
    w, app = win
    g = w.geo_card
    chans = [g.channel.itemText(i) for i in range(g.channel.count())]
    assert "HRIC" in chans and "STC-H" in chans
    g.channel.setCurrentText("HRIC")
    assert Path(g.dtm_path.text()).name == "exampleDTM_HRIC.tif"
    g.channel.setCurrentText("STC-H")
    assert Path(g.dtm_path.text()).name == "exampleDTM_STC.tif"
    g.channel.setCurrentText("STC-L")
    assert Path(g.dtm_path.text()).name == "exampleDTM_STC.tif"
    # a user override is remembered per family and does not leak to the other one
    custom = str(Path(g.dtm_path.text()).with_name("exampleDTM_HRIC.tif"))
    g.dtm_path.setText(custom)
    g.dtm_path.editingFinished.emit()
    g.channel.setCurrentText("HRIC")
    assert Path(g.dtm_path.text()).name == "exampleDTM_HRIC.tif"
    g.channel.setCurrentText("STC-H")
    assert g.dtm_path.text() == custom
    # clearing restores the bundled DTM
    g.dtm_path.setText("")
    g.dtm_path.editingFinished.emit()
    assert Path(g.dtm_path.text()).name == "exampleDTM_STC.tif"
    # switching does not trigger a computation
    assert not g.error.isVisible()


def test_hillshade_uses_selected_dtm(win):
    w, app = win
    g = w.geo_card
    g.chk_hs.setChecked(True)
    for chan, name in (("HRIC", "exampleDTM_HRIC.tif"), ("STC-H", "exampleDTM_STC.tif")):
        g.channel.setCurrentText(chan)
        g.mode.set_index(0)
        g.time_in.setText("2027-06-20T12:00:00")
        g.compute()
        wait_hillshade(g, app)
        assert g.result is not None and name in g.hs_caption.text(), g.hs_caption.text()


def test_download_card(win, tmp_path):
    """The card works from the metakernel path alone (kernels not required), shows a summary, and downloads from a local FTP server."""
    import shutil
    import threading
    pytest.importorskip("pyftpdlib")
    from pyftpdlib.authorizers import DummyAuthorizer
    from pyftpdlib.handlers import FTPHandler
    from pyftpdlib.servers import FTPServer
    from simbio_utility.core import download as dl

    w, app = win
    c = w.dl_card
    assert c.host.text() == dl.DEFAULT_HOST and c.remote.text() == dl.DEFAULT_REMOTE_ROOT
    assert not c.needs_kernels
    src = mock.build(tmp_path / "src")
    served = tmp_path / "served"
    shutil.copytree(src.parent.parent, served / "data/SPICE/BEPICOLOMBO/kernels")
    auth = DummyAuthorizer()
    auth.add_anonymous(str(served))
    srv = FTPServer(("127.0.0.1", 0), type("H", (FTPHandler,), {"authorizer": auth}))
    threading.Thread(target=srv.serve_forever, kwargs={"timeout": 0.2, "handle_exit": False}, daemon=True).start()
    try:
        old_path = w.path.text()
        w.path.setText(str(src))
        c.out.setText(str(tmp_path / "out"))
        c.host.setText(f"127.0.0.1:{srv.address[1]}")
        c.refresh()
        assert "5 kernels" in c.mk_info.text() and "0 already" in c.mk_info.text()
        c.btn_test.click()
        assert "reachable" in c.status.text() and not c.error.isVisible()
        c.btn.click()
        t = time.time()
        while c._thread is not None and time.time() - t < 20:
            app.processEvents()
            time.sleep(0.01)
        spin(app, 100)
        assert c.status.text() == "Download complete" and c.bar.value() == 1000
        assert c.btn_load.isEnabled() and (tmp_path / "out/data/SPICE/BEPICOLOMBO/kernels/spk/mock.bsp").is_file()
        assert "5 already" in c.mk_info.text()
        # an error is shown instead of crashing
        c.out.setText("")
        c.btn.click()
        assert c.error.isVisibleTo(c) and c._thread is None
        # restore the host/path state for the other tests
        c.host.setText(dl.DEFAULT_HOST)
        w.path.setText(old_path)
    finally:
        srv.close_all()
