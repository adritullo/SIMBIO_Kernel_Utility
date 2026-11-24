from __future__ import annotations

import csv
import time
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QHeaderView,
                               QLineEdit, QProgressBar, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ...core import instruments, timeconv
from ...core.errors import UtilityError
from ...core.ltp import Ltp, load_ltps
from ...core.visibility import PositionSearch, SearchResult
from ..widgets import Panel, Segmented, label
from .base import Card

SLICE_SECONDS = 0.04  # work per timer tick: the window stays responsive while searching


def _fmt_dur(s: float) -> str:
    if s < 1:
        return "< 1 s"
    if s < 120:
        return f"{s:.0f} s"
    return f"{s / 60:.1f} min"


class PositionCard(Card):
    title = "Positional Search"
    subtitle = "When does a camera see a given point (lat / lon) in an LTP or a custom range"
    glyph = "⌖"

    COLS = ["Start UTC", "End UTC", "Duration", "Best UTC", "Resolution m/px", "Emission °", "Incidence °", "Phase °"]

    def build(self, root: QWidget) -> None:
        self._cameras: list[instruments.Camera] = []
        self._search: PositionSearch | None = None
        self._iter = None
        self._cancel = False
        self._t0 = 0.0
        self.result: SearchResult | None = None
        self.open_in_geometry = lambda camera, et: None  # set by the main window
        try:
            self._ltps: dict[int, Ltp] = load_ltps()
        except Exception:  # the bundled file is always there; a broken install should not stop the card
            self._ltps = {}
        self._timer = QTimer(self)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._tick)

        outer = QHBoxLayout(root)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(18)

        # ---------------- inputs ----------------
        left = Panel("Target & range")
        left.setMinimumWidth(300)
        left.setMaximumWidth(440)
        self.left_panel, self.left_max = left, 440
        left.body.addWidget(label("Channel", "muted"))
        self.channel = QComboBox()
        left.body.addWidget(self.channel)
        left.body.addWidget(label("Filter", "muted"))
        self.filter = QComboBox()
        left.body.addWidget(self.filter)

        g = QGridLayout()
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(4)
        g.addWidget(label("Latitude (°N)", "muted"), 0, 0)
        g.addWidget(label("Longitude (°E)", "muted"), 0, 1)
        self.lat = QLineEdit(str(self.config.get("ps_lat", "0")))
        self.lon = QLineEdit(str(self.config.get("ps_lon", "0")))
        for w, tip in ((self.lat, "Planetocentric latitude, −90 … 90"), (self.lon, "East-positive longitude, −180 … 180 or 0 … 360")):
            w.setProperty("mono", True)
            w.setToolTip(tip)
        g.addWidget(self.lat, 1, 0)
        g.addWidget(self.lon, 1, 1)
        left.body.addLayout(g)

        left.body.addSpacing(4)
        left.body.addWidget(label("Time range", "muted"))
        names = [f"LTP{n}" for n in sorted(self._ltps)] + ["Custom"]
        self.range_sel = Segmented(names)
        self.range_sel.setStyleSheet(self.range_sel.styleSheet() + "QPushButton{padding:6px 2px;}")
        for b in self.range_sel.group.buttons():
            b.setMinimumWidth(0)
        left.body.addWidget(self.range_sel)
        self.ltp_info = label("", "small", wrap=True)
        left.body.addWidget(self.ltp_info)
        tg = QGridLayout()
        tg.setHorizontalSpacing(10)
        tg.setVerticalSpacing(6)
        self.start = QLineEdit()
        self.end = QLineEdit()
        for i, (w, cap) in enumerate(((self.start, "Start"), (self.end, "End"))):
            w.setProperty("mono", True)
            w.setPlaceholderText("2027-06-01T00:00:00")
            w.setToolTip("UTC, e.g. 2027-06-01T00:00:00 or 2027-152T00:00:00")
            tg.addWidget(label(cap, "muted"), i, 0)
            tg.addWidget(w, i, 1)
        tg.setColumnStretch(1, 1)
        left.body.addLayout(tg)

        self.chk_lit = QCheckBox("Sunlit only (incidence < 90°)")
        self.chk_lit.setChecked(self.config.get_bool("ps_sunlit", True))
        self.chk_lit.setToolTip("Hide the passes in which the point is on the night side (they are still counted).")
        left.body.addWidget(self.chk_lit)

        left.body.addSpacing(6)
        self.btn = QPushButton("Search")
        self.btn.setProperty("primary", True)
        left.body.addWidget(self.btn)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setEnabled(False)
        left.body.addWidget(self.btn_cancel)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(10)
        left.body.addWidget(self.bar)
        self.status = label("", "small", wrap=True)
        left.body.addWidget(self.status)
        self.error = label("", "error", wrap=True)
        self.error.hide()
        left.body.addWidget(self.error)
        left.body.addStretch(1)
        left.body.addWidget(label("The point is tracked with the real attitude of the metakernel (CK) and the camera FOV "
                                  "of the IK; times are accurate to about a second. Ranges without ephemeris or attitude "
                                  "are skipped and reported.", "note", wrap=True))
        outer.addWidget(left, 1)

        # ---------------- results ----------------
        right = QWidget()
        col = QVBoxLayout(right)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(14)
        panel = Panel("Passes over the point")
        self.count = label("Enter a point and press Search.", "small", wrap=True)
        panel.body.addWidget(self.count)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setToolTip("Double-click a pass to open its best epoch in Observation Geometry")
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setStretchLastSection(True)
        panel.body.addWidget(self.table, 1)
        brow = QHBoxLayout()
        self.btn_geo = QPushButton("Open in Observation Geometry")
        self.btn_geo.setEnabled(False)
        self.btn_csv = QPushButton("Export CSV…")
        self.btn_csv.setEnabled(False)
        brow.addWidget(self.btn_geo)
        brow.addStretch(1)
        brow.addWidget(self.btn_csv)
        panel.body.addLayout(brow)
        col.addWidget(panel, 1)
        outer.addWidget(right, 2)

        # ---------------- wiring ----------------
        self.channel.currentIndexChanged.connect(self._fill_filters)
        self.range_sel.changed.connect(self._range_changed)
        self.start.textEdited.connect(self._custom_edited)
        self.end.textEdited.connect(self._custom_edited)
        self.btn.clicked.connect(self.search)
        self.btn_cancel.clicked.connect(self.cancel)
        self.btn_geo.clicked.connect(self._open_selected)
        self.btn_csv.clicked.connect(self._export)
        self.table.itemDoubleClicked.connect(lambda *_: self._open_selected())
        self.table.itemSelectionChanged.connect(lambda: self.btn_geo.setEnabled(bool(self.table.selectedItems())))
        self.lat.returnPressed.connect(self.search)
        self.lon.returnPressed.connect(self.search)

        # initial range: last choice, LTP1 by default
        sel = str(self.config.get("ps_range", "LTP1"))
        idx = names.index(sel) if sel in names else 0
        self.range_sel.set_index(idx)
        if sel == "Custom":
            self.start.setText(str(self.config.get("ps_start", "")))
            self.end.setText(str(self.config.get("ps_end", "")))
            self._range_changed(idx)
        else:
            self._range_changed(idx)

    # ------------------------------------------------------------------ cameras / ranges
    def kernels_changed(self) -> None:
        if self._iter is not None:
            self.cancel()
        self._cameras = instruments.discover_cameras()
        want = str(self.config.get("ps_camera", "") or self.config.get("last_camera", "MPO_SIMBIO-SYS_STC-H_P700"))
        self.channel.blockSignals(True)
        self.channel.clear()
        for ch in dict.fromkeys(c.channel for c in self._cameras):
            self.channel.addItem(ch)
        self.channel.blockSignals(False)
        cam = next((c for c in self._cameras if c.name == want), self._cameras[0] if self._cameras else None)
        if cam:
            self.channel.setCurrentText(cam.channel)
        self._fill_filters(prefer=cam.filter if cam else None)

    def _fill_filters(self, *_a, prefer: str | None = None) -> None:
        ch = self.channel.currentText()
        self.filter.clear()
        for c in self._cameras:
            if c.channel == ch:
                self.filter.addItem(c.filter, c.name)
        if prefer:
            self.filter.setCurrentText(prefer)

    def camera(self) -> str:
        return self.filter.currentData() or ""

    def _range_names(self) -> list[str]:
        return [f"LTP{n}" for n in sorted(self._ltps)] + ["Custom"]

    def _range_changed(self, idx: int) -> None:
        name = self._range_names()[idx]
        if name == "Custom":
            self.ltp_info.setText("Custom range: type the start and end epochs (UTC).")
            return
        ltp = self._ltps[int(name[3:])]
        self.start.setText(ltp.start_utc)
        self.end.setText(ltp.end_utc)
        self.ltp_info.setText(ltp.label)

    def _custom_edited(self, *_a) -> None:
        names = self._range_names()
        if names[self.range_sel.index()] != "Custom":
            self.range_sel.set_index(len(names) - 1)
            self.ltp_info.setText("Custom range: type the start and end epochs (UTC).")

    # ------------------------------------------------------------------ search
    def _parse(self) -> tuple[str, float, float, float, float]:
        cam = self.camera()
        if not cam:
            raise UtilityError("No camera selected (load a metakernel with the SIMBIO-SYS IK).")
        try:
            lat = float(self.lat.text().strip().replace(",", "."))
            lon = float(self.lon.text().strip().replace(",", "."))
        except ValueError as exc:
            raise UtilityError("Latitude and longitude must be numbers in degrees, e.g. 12.5 and -45.") from exc
        if not -90.0 <= lat <= 90.0:
            raise UtilityError("Latitude must be between −90 and 90°.")
        if not -180.0 <= lon <= 360.0:
            raise UtilityError("Longitude must be between −180 and 360° (east positive).")
        et0 = timeconv.utc_to_et(self.start.text())
        et1 = timeconv.utc_to_et(self.end.text())
        if et1 <= et0:
            raise UtilityError("The end of the range must be after its start.")
        return cam, lat, lon, et0, et1

    def search(self) -> None:
        if self._iter is not None:
            return
        self.error.hide()
        try:
            cam, lat, lon, et0, et1 = self._parse()
            self._search = PositionSearch(cam, lat, lon, et0, et1, sunlit_only=self.chk_lit.isChecked())
        except UtilityError as exc:
            self.error.setText(str(exc))
            self.error.show()
            return
        names = self._range_names()
        self.config.set("ps_lat", self.lat.text().strip())
        self.config.set("ps_lon", self.lon.text().strip())
        self.config.set("ps_camera", cam)
        self.config.set("ps_sunlit", self.chk_lit.isChecked())
        self.config.set("ps_range", names[self.range_sel.index()])
        self.config.set("ps_start", self.start.text().strip())
        self.config.set("ps_end", self.end.text().strip())
        self.table.setRowCount(0)
        self.result = None
        self.btn_csv.setEnabled(False)
        self.btn_geo.setEnabled(False)
        self.bar.setValue(0)
        self._cancel = False
        self._t0 = time.time()
        self._iter = self._search.steps(lambda: self._cancel)
        self._set_busy(True)
        self.status.setText(f"Searching {(et1 - et0) / 86400:.0f} days…")
        self._timer.start()

    def cancel(self) -> None:
        self._cancel = True

    def _set_busy(self, busy: bool) -> None:
        for w in (self.btn, self.channel, self.filter, self.lat, self.lon, self.range_sel, self.start, self.end, self.chk_lit):
            w.setEnabled(not busy)
        self.btn_cancel.setEnabled(busy)

    def _tick(self) -> None:
        if self._iter is None:
            self._timer.stop()
            return
        t_end = time.perf_counter() + SLICE_SECONDS
        try:
            while time.perf_counter() < t_end:
                frac = next(self._iter)
                if frac >= 1.0:
                    raise StopIteration
        except StopIteration:
            self._finish()
            return
        except Exception as exc:  # SPICE trouble mid-way: report, keep what was found
            self._finish(error=str(exc).splitlines()[0])
            return
        self.bar.setValue(int(frac * 1000))
        n = len(self._search.result.passes)
        self.status.setText(f"Searching… {frac * 100:.0f} %  ·  {n} pass{'es' if n != 1 else ''} so far")

    def _finish(self, error: str = "") -> None:
        self._timer.stop()
        self._iter = None
        self._set_busy(False)
        res = self._search.result
        self.result = res
        self.bar.setValue(1000 if not res.cancelled else self.bar.value())
        self._fill_table(res)
        took = time.time() - self._t0
        self.status.setText(f"Done in {took:.1f} s." if not res.cancelled else "Cancelled - partial results.")
        s = self._search
        self.count.setText(f"{res.summary()} · {s.camera} · lat {s.lat:g}°, lon {s.lon:g}°E · "
                           f"{timeconv.et_to_utc(s.et0, 0)} → {timeconv.et_to_utc(s.et1, 0)}")
        self.btn_csv.setEnabled(bool(res.passes))
        if error:
            self.error.setText(f"Search stopped: {error}")
            self.error.show()

    def _fill_table(self, res: SearchResult) -> None:
        self.table.setRowCount(len(res.passes))
        for i, p in enumerate(res.passes):
            r = p.row()
            vals = [r["start_utc"], r["end_utc"], _fmt_dur(p.duration_s), r["best_utc"], f"{r['resolution_m_px']:.2f}",
                    f"{r['emission_deg']:.1f}", f"{r['incidence_deg']:.1f}", f"{r['phase_deg']:.1f}"]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if j == 0:
                    it.setData(256, p.best.et)  # Qt.UserRole
                self.table.setItem(i, j, it)

    # ------------------------------------------------------------------ output
    def _open_selected(self) -> None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows or self._search is None:
            return
        et = self.table.item(rows[0].row(), 0).data(256)
        self.open_in_geometry(self._search.camera, float(et))

    def _export(self) -> None:
        if not self.result or not self.result.passes:
            return
        s = self._search
        p, _ = QFileDialog.getSaveFileName(self, "Export passes", f"passes_lat{s.lat:g}_lon{s.lon:g}.csv", "CSV (*.csv)")
        if p:
            self.write_csv(p)

    def write_csv(self, path: str | Path) -> None:
        rows = [p.row() for p in self.result.passes]
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)

    def shutdown(self) -> None:
        self._cancel = True
        self._timer.stop()
