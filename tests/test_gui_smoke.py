import csv
import threading
import os
import time
from pathlib import Path

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
    spin(app, 500)
    assert tc.a.rows[0].value.text() == "866764869.184420"
    tc.b.inp.setText("not a number")
    spin(app, 500)
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
    import simbio_utility
    w, _ = win
    assert any(l.text() == f"v{simbio_utility.__version__} by a.tullo" for l in w.findChildren(QLabel))


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
        t = time.time()
        while (w._thread is not None or not w.session.loaded) and time.time() - t < 20:  # the app loads the new metakernel by itself
            app.processEvents()
            time.sleep(0.01)
        spin(app, 150)
        new_mk = tmp_path / "out/data/SPICE/BEPICOLOMBO/kernels/mk/mock_plan.tm"
        assert c.status.text() == "Download complete - metakernel loaded" and c.bar.value() == 1000
        assert w.session.loaded and Path(w.path.text()).resolve() == new_mk.resolve()  # pointed at the downloaded metakernel and loaded
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


def test_time_columns_mirror(win):
    w, app = win
    t = w.time_card
    t.prec.setCurrentIndex(3)
    # UTC typed on the left -> ET on the right (and the right column shows its UTC result)
    t.a.inp.setText("2027-06-20T12:00:00")
    spin(app, 400)
    assert t.b.inp.text() == "866764869.184420"
    assert t.b.rows[0].value.text() == "2027-06-20T12:00:00.000"  # the right column computed its own result too
    # ET typed on the right -> UTC on the left (and the left column shows its ET result)
    t.b.inp.setText("866768469.184420")
    spin(app, 400)
    assert t.a.inp.text() == "2027-06-20T13:00:00.000"
    # clearing one column clears the other
    t.a.inp.setText("")
    spin(app, 400)
    assert t.b.inp.text() == "" and t.a.inp.text() == ""
    # an invalid entry shows its error and empties the other column instead of leaving a stale value
    t.a.inp.setText("2027-06-20T12:00:00")
    spin(app, 400)
    t.a.inp.setText("not a time")
    spin(app, 400)
    assert t.a.err.isVisibleTo(t.a) and t.b.inp.text() == ""
    # precision only changes the displayed result, not what the user typed
    t.b.inp.setText("866764869.184420")
    spin(app, 400)
    left = t.a.inp.text()
    t.prec.setCurrentIndex(0)
    spin(app, 100)
    assert t.a.inp.text() == left and t.b.inp.text() == "866764869.184420"
    t.prec.setCurrentIndex(3)
    t.b.inp.setText("")
    spin(app, 400)


def test_missing_kernels_jump_to_download(win, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    w, app = win
    src = mock.build(tmp_path / "src")
    # a metakernel copy with none of its kernels next to it
    lonely = tmp_path / "x/data/SPICE/BEPICOLOMBO/kernels/mk/mock_plan.tm"
    lonely.parent.mkdir(parents=True)
    lonely.write_text(src.read_text())
    w.nav_group.button(0).click()
    w.path.setText(str(lonely))
    w.load()  # same as Browse -> pick -> load
    assert w.stack.currentWidget() is w.dl_card
    assert "5 of 5 kernels are not on this computer" in w.dl_card.banner.text()
    assert w.dl_card.out.text() == str(tmp_path / "x")  # inferred from the ESA layout
    assert w._thread is None and "missing" in w.pill.text()
    # a complete metakernel loads normally and stays where it is
    w.nav_group.button(0).click()
    w.path.setText(str(src))
    w.load()
    t = time.time()
    while (w._thread is not None or not w.session.loaded) and time.time() - t < 15:
        app.processEvents()
        time.sleep(0.01)
    assert w.session.loaded and w.stack.currentIndex() == 0


def test_search_card(win, tmp_path):
    import functools
    import http.server
    w, app = win
    www = tmp_path / "www/mk"
    www.mkdir(parents=True)
    (www / "bc_ops.tm").write_text("ops")
    (www / "bc_plan.tm").write_text("plan")
    (www / "bc_plan_v440_20261015_002.tm").write_text("v440")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path / "www"))
    handler.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    c = w.sk_card
    try:
        from simbio_utility.core import mkindex
        assert c.url.text() == mkindex.DEFAULT_URL  # default folder
        c.url.setText(f"http://127.0.0.1:{srv.server_address[1]}/mk/")
        c.search()
        t = time.time()
        while c.table.rowCount() == 0 and time.time() - t < 10:
            app.processEvents()
            time.sleep(0.01)
        spin(app, 100)
        names = [c.table.item(r, 0).text() for r in range(c.table.rowCount())]
        assert names == ["bc_ops.tm", "bc_plan.tm", "bc_plan_v440_20261015_002.tm"]
        assert c.table.item(0, 1).text() == "latest operational" and "v440" in c.table.item(2, 1).text()
        # filter
        c.filter.setText("v440")
        assert [c.table.isRowHidden(r) for r in range(3)] == [True, True, False] and "1 match" in c.count.text()
        c.filter.setText("")
        # download one
        dest = tmp_path / "saved"
        c.dest.setText(str(dest))
        c.table.selectRow(1)
        assert c.btn_dl.isEnabled() and c.btn_open.isEnabled()
        c.btn_dl.click()
        t = time.time()
        while not (dest / "bc_plan.tm").exists() and time.time() - t < 10:
            app.processEvents()
            time.sleep(0.01)
        spin(app, 200)
        assert (dest / "bc_plan.tm").read_text() == "plan" and "Saved 1 file" in c.status.text()
        # download + use: goes through the checked load (this file lists no kernels -> normal load error path, not a crash)
        opened = []
        c.use_metakernel = opened.append
        c.table.selectRow(0)
        c.btn_open.click()
        t = time.time()
        while not opened and time.time() - t < 10:
            app.processEvents()
            time.sleep(0.01)
        assert opened == [str(dest / "bc_ops.tm")]
        # unreachable server: an error, no crash
        c.url.setText("http://127.0.0.1:1/x/")
        c.search()
        t = time.time()
        while c._list_thread.isRunning() and time.time() - t < 15:
            app.processEvents()
            time.sleep(0.01)
        spin(app, 100)
        assert c.error.isVisibleTo(c)
    finally:
        srv.shutdown()
        c.url.setText(mkindex.DEFAULT_URL)


def test_download_card_https_option(win, tmp_path):
    """The 'Use HTTPS (port 443)' option is off by default, is remembered, and downloads over the web protocol."""
    import functools
    import shutil
    import threading
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    from simbio_utility.core import download as dl

    w, app = win
    c = w.dl_card
    assert not c.chk_https.isChecked()
    c.chk_https.setChecked(True)
    assert c.config.get_bool("dl_https", False) is True

    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    src = mock.build(tmp_path / "src")
    served = tmp_path / "served"
    shutil.copytree(src.parent.parent, served / "data/SPICE/BEPICOLOMBO/kernels")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(served)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        w.path.setText(str(src))
        c.out.setText(str(tmp_path / "out"))
        c.host.setText(f"http://127.0.0.1:{srv.server_address[1]}")
        c.refresh()
        c.btn_test.click()
        assert "reachable" in c.status.text() and "not reachable" not in c.status.text() and not c.error.isVisible()
        c.btn.click()
        t = time.time()
        while c._thread is not None and time.time() - t < 20:
            app.processEvents()
            time.sleep(0.01)
        assert (tmp_path / "out" / dl.DEFAULT_REMOTE_ROOT / "spk" / "mock.bsp").is_file()
    finally:
        srv.shutdown()
        srv.server_close()
        c.chk_https.setChecked(False)
        c.host.setText(dl.DEFAULT_HOST)
