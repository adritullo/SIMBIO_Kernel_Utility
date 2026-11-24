from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
                               QApplication, QLabel, QLineEdit, QMainWindow, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from .. import APP_NAME, AUTHOR, __version__
from ..config import AppConfig
from ..core import download as dl
from ..core.errors import UtilityError
from ..core.kernels import KernelInfo, KernelSession
from ..core.stp import StpTable
from ..resources import example_mk_path, resource_path
from .cards import CARDS
from .cards.download_card import DownloadCard
from .cards.geometry_card import GeometryCard
from .cards.position_card import PositionCard
from .cards.search_card import SearchCard
from .cards.time_card import TimeCard
from .widgets import Debouncer, label


class _LoadThread(QThread):
    ok = Signal(object)
    fail = Signal(str)

    def __init__(self, session: KernelSession, path: str) -> None:
        super().__init__()
        self.session, self.path = session, path

    def run(self) -> None:
        try:
            self.ok.emit(self.session.load(self.path))
        except UtilityError as exc:
            self.fail.emit(str(exc))
        except Exception as exc:  # pragma: no cover
            self.fail.emit(f"Unexpected error: {exc}")


class SettingsDialog(QDialog):
    def __init__(self, cfg: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("Settings")
        self.setMinimumWidth(660)
        form = QFormLayout(self)
        form.setContentsMargins(22, 22, 22, 18)
        form.setSpacing(12)
        self.abcorr = QComboBox()
        for v, t in (("LT+S", "LT+S  (light time + stellar aberration)"), ("NONE", "NONE  (geometric)"), ("CN+S", "CN+S  (converged Newtonian)")):
            self.abcorr.addItem(t, v)
        self.abcorr.setCurrentIndex(max(0, self.abcorr.findData(cfg.abcorr)))
        self.lon = QComboBox()
        self.lon.addItem("−180 … 180  (east positive)", "180")
        self.lon.addItem("0 … 360  (east positive)", "360")
        self.lon.setCurrentIndex(max(0, self.lon.findData(cfg.lon_domain)))
        self.seasons = QLineEdit(cfg.season_json)
        self.seasons.setPlaceholderText("optional seasons.json (see README) — empty = built-in MTA sectors")
        browse = QPushButton("…")
        browse.setFixedWidth(40)
        browse.setStyleSheet("padding: 8px 0;")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.seasons, 1)
        row.addWidget(browse)
        self.evf = QLineEdit(cfg.stp_evf)
        self.evf.setPlaceholderText("empty = built-in timeline (stps_bc_sgs_PLANNING_20260306_MODIFICATO.evf)")
        ebrowse = QPushButton("…")
        ebrowse.setFixedWidth(40)
        ebrowse.setStyleSheet("padding: 8px 0;")
        ebrowse.clicked.connect(self._browse_evf)
        ereset = QPushButton("Built-in")
        ereset.clicked.connect(lambda: (self.evf.setText(""), self._evf_status()))
        erow = QHBoxLayout()
        erow.addWidget(self.evf, 1)
        erow.addWidget(ebrowse)
        erow.addWidget(ereset)
        self.evf_info = QLabel("")
        self.evf_info.setProperty("role", "small")
        self.evf_info.setWordWrap(True)
        self.evf.textChanged.connect(lambda *_: self._evf_status())
        self._evf_status()
        self.ui_scale = QComboBox()
        for v in (0.75, 0.85, 0.9, 1.0, 1.1, 1.25, 1.5):
            self.ui_scale.addItem(f"{v * 100:.0f} %" + ("  (default)" if v == 1.0 else ""), v)
        idx = min(range(self.ui_scale.count()), key=lambda i: abs(self.ui_scale.itemData(i) - cfg.ui_scale))
        self.ui_scale.setCurrentIndex(idx)
        self.ui_scale.setToolTip("Size of text and controls. Smaller values fit small laptop screens; applied after a restart.\n"
                                 "It multiplies the Windows/macOS display scaling.")
        form.addRow("Interface size", self.ui_scale)
        form.addRow("Aberration correction", self.abcorr)
        form.addRow("Longitude convention", self.lon)
        form.addRow("Season definition", row)
        form.addRow("STP / MTP timeline (EVF)", erow)
        form.addRow("", self.evf_info)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _browse(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "Season definition", "", "JSON (*.json)")
        if p:
            self.seasons.setText(p)

    def _browse_evf(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "STP event file", self.evf.text() or "", "Event files (*.evf *.txt);;All files (*)")
        if p:
            self.evf.setText(p)

    def _evf_status(self) -> None:
        path = self.evf.text().strip().strip('"') or str(resource_path("stp_default.evf"))
        try:
            t = StpTable.from_file(path)
            self.evf_info.setText(f"{'Built-in' if not self.evf.text().strip() else 'Custom'}: {t.summary()}  (MTP = {t.stps_per_mtp} STPs)")
            self.evf_info.setStyleSheet("")
        except Exception as exc:
            self.evf_info.setText(f"Invalid event file: {exc}")
            self.evf_info.setStyleSheet("color: #ff6b6b;")

    def _save(self) -> None:
        path = self.evf.text().strip().strip('"')
        if path:
            try:
                StpTable.from_file(path)
            except Exception as exc:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "STP / MTP timeline", f"This event file cannot be used:\n{exc}")
                return
        self.cfg.set("stp_evf", path)
        self.cfg.set("abcorr", self.abcorr.currentData())
        self.cfg.set("lon_domain", self.lon.currentData())
        self.cfg.set("season_json", self.seasons.text().strip())
        new_scale = float(self.ui_scale.currentData())
        changed = abs(new_scale - self.cfg.ui_scale) > 1e-3
        self.cfg.set("ui_scale", new_scale)
        self.accept()
        if changed:
            from PySide6.QtWidgets import QMessageBox
            if QMessageBox.question(self.parent(), "Interface size", "The new interface size is applied when the app restarts.\n\nRestart now?") == QMessageBox.Yes:
                from .app import restart
                restart()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME}")
        self.setMinimumSize(760, 500)  # cards scroll below their natural size (small laptops, 125-150 % scaling)
        self.setAcceptDrops(True)
        self.cfg = AppConfig()
        self.session = KernelSession()
        self._thread: _LoadThread | None = None

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ---- sidebar
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(236)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(16, 22, 16, 16)
        sl.setSpacing(4)
        sl.addWidget(label("SIMBIO", "brand"))
        sl.addWidget(label("KERNEL UTILITY", "brandsub"))
        sl.addSpacing(22)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.stack = QStackedWidget()
        self.cards = []
        for i, cls in enumerate(CARDS):
            card = cls(self.cfg)
            self.cards.append(card)
            self.stack.addWidget(card)
            b = QPushButton(f"{card.glyph}   {card.title}")
            b.setProperty("nav", True)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(card.subtitle)
            self.nav_group.addButton(b, i)
            sl.addWidget(b)
        self.nav_group.idClicked.connect(self.stack.setCurrentIndex)
        self.nav_group.button(0).setChecked(True)
        sl.addStretch(1)
        st = QPushButton("⚙   Settings")
        st.setProperty("nav", True)
        st.clicked.connect(self._settings)
        sl.addWidget(st)
        sl.addWidget(label(f"v{__version__} by {AUTHOR}", "small"))
        lay.addWidget(side)

        # ---- right column
        right = QVBoxLayout()
        right.setSpacing(0)
        bar = QFrame()
        bar.setObjectName("topbar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(28, 14, 28, 14)
        bl.setSpacing(10)
        bl.addWidget(label("METAKERNEL", "h2"))
        self.path = QLineEdit(str(self.cfg.get("metakernel", "")))
        self.path.setProperty("mono", True)
        self.path.setPlaceholderText(f"{example_mk_path()}   (or drop a .tm file here)")
        self.path.returnPressed.connect(self.load)
        bl.addWidget(self.path, 1)
        bb = QPushButton("Browse…")
        bb.clicked.connect(self._browse)
        self.btn_load = QPushButton("Load")
        self.btn_load.setProperty("primary", True)
        self.btn_load.clicked.connect(self.load)
        self.pill = QLabel("no kernels")
        self.pill.setProperty("pill", "idle")
        bl.addWidget(bb)
        bl.addWidget(self.btn_load)
        bl.addWidget(self.pill)
        right.addWidget(bar)
        right.addWidget(self.stack, 1)
        lay.addLayout(right, 1)

        # card wiring
        for c in self.cards:
            if isinstance(c, TimeCard):
                self.time_card = c
            if isinstance(c, GeometryCard):
                self.geo_card = c
        self.time_card.send_to_geometry = self._time_to_geometry
        for c in self.cards:
            if isinstance(c, DownloadCard):
                self.dl_card = c
        self.dl_card.metakernel_path = lambda: self.path.text()
        self.dl_card.load_metakernel = lambda p: self._load_path(p, check=False)  # just downloaded: load straight away
        for c in self.cards:
            if isinstance(c, SearchCard):
                self.sk_card = c
        self.sk_card.use_metakernel = self._load_path  # checked: if its kernels are missing we go to Kernel Download
        self.ps_card = next(c for c in self.cards if isinstance(c, PositionCard))
        self.ps_card.open_in_geometry = self._pass_to_geometry
        self._dl_refresh = Debouncer(self.dl_card.refresh, 300)
        self.path.textChanged.connect(self._dl_refresh)
        self.dl_card.refresh()

        self._initial_geometry()
        if self.path.text() and Path(self.path.text()).is_file():
            QTimer.singleShot(150, self.load)

    # ------------------------------------------------------------------
    def _initial_geometry(self) -> None:
        """Restore the last window geometry, but never larger than the screen (the old default was 1360x720 minimum,
        too big for 1366x768 laptops at 125 % scaling)."""
        g = self.cfg.get("window_geometry", None)
        restored = False
        if g is not None:
            try:
                restored = bool(self.restoreGeometry(g))
            except Exception:
                restored = False
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            if not restored:
                self.resize(1320, 860)
            return
        avail = screen.availableGeometry()
        if restored and not self.isMaximized():
            fr = self.frameGeometry()
            if fr.width() <= avail.width() and fr.height() <= avail.height() and avail.contains(fr.center()):
                return
        w = min(1320, int(avail.width() * 0.94))
        h = min(860, int(avail.height() * 0.90))
        self.resize(max(w, self.minimumWidth()), max(h, self.minimumHeight()))
        self.move(avail.x() + (avail.width() - self.width()) // 2, avail.y() + max(0, (avail.height() - self.height()) // 3))

    def _pass_to_geometry(self, camera: str, et: float) -> None:
        """Positional Search -> Observation Geometry at the best epoch of a pass, computed straight away."""
        self.geo_card.select_camera(camera)
        self._time_to_geometry(et)
        self.geo_card.compute()

    def _time_to_geometry(self, et: float) -> None:
        self.geo_card.set_et(et)
        idx = self.cards.index(self.geo_card)
        self.nav_group.button(idx).setChecked(True)
        self.stack.setCurrentIndex(idx)

    def _browse(self) -> None:
        start = str(Path(self.path.text()).parent) if self.path.text() else ""
        p, _ = QFileDialog.getOpenFileName(self, "Select metakernel", start, "Metakernels (*.tm *.mk *.txt);;All files (*)")
        if p:
            self.path.setText(p)
            self.load()

    def _set_pill(self, kind: str, text: str, tip: str = "") -> None:
        self.pill.setProperty("pill", kind)
        self.pill.setText(text)
        self.pill.setToolTip(tip)
        self.pill.style().unpolish(self.pill)
        self.pill.style().polish(self.pill)

    def goto_card(self, card) -> None:
        idx = self.cards.index(card)
        self.nav_group.button(idx).setChecked(True)
        self.stack.setCurrentIndex(idx)

    def _load_path(self, path: str, check: bool = True) -> None:
        self.path.setText(path)
        self.load(check=check)

    def _offer_download(self, p: str) -> bool:
        """If the metakernel lists kernels that are not on disk, go to Kernel Download instead of failing to load."""
        try:
            mk = dl.parse_metakernel(p)
        except UtilityError:
            return False  # not parseable here: let the normal load report the real problem
        missing = mk.missing()
        if not missing:
            return False
        self._set_pill("err", f"{len(missing)} kernels missing", f"{mk.path.name}: {len(missing)} of {mk.total} kernels are not on this computer")
        self.dl_card.offer(mk, missing)
        self.goto_card(self.dl_card)
        return True

    def load(self, check: bool = True) -> None:
        p = self.path.text().strip().strip('"')
        if not p or self._thread is not None:
            return
        if check and self._offer_download(p):
            return
        self.btn_load.setEnabled(False)
        self.path.setEnabled(False)
        self._set_pill("idle", "loading…")
        self._thread = _LoadThread(self.session, p)
        self._thread.ok.connect(self._loaded)
        self._thread.fail.connect(self._load_failed)
        self._thread.finished.connect(self._thread_done)
        self._thread.start()

    def _thread_done(self) -> None:
        self._thread = None
        self.btn_load.setEnabled(True)
        self.path.setEnabled(True)

    def _loaded(self, info: KernelInfo) -> None:
        self.cfg.set("metakernel", str(info.metakernel))
        self.path.setText(str(info.metakernel))
        self._set_pill("ok", f"● {info.total} kernels", f"{info.metakernel.name}\n{info.summary()}")
        for c in self.cards:
            c.set_ready(True)
            c.kernels_changed()

    def _load_failed(self, msg: str) -> None:
        for c in self.cards:
            c.set_ready(not c.needs_kernels)
        self._set_pill("err", "load failed", msg)
        self.statusBar().showMessage(msg.splitlines()[0], 8000)
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(self, "Metakernel", msg)

    def _settings(self) -> None:
        if SettingsDialog(self.cfg, self).exec():
            for c in self.cards:
                c.kernels_changed() if self.session.loaded else None

    # drag & drop a metakernel
    def dragEnterEvent(self, e) -> None:  # noqa: N802
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:  # noqa: N802
        urls = e.mimeData().urls()
        if urls:
            self.path.setText(urls[0].toLocalFile())
            self.load()

    def closeEvent(self, e) -> None:  # noqa: N802
        self.cfg.set("window_geometry", self.saveGeometry())
        for c in self.cards:
            c.shutdown()
        if self._thread is not None:
            self._thread.wait(3000)
        self.session.unload()
        super().closeEvent(e)
