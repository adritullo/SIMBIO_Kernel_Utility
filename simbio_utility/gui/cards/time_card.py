from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ...core import timeconv
from ...core.errors import UtilityError, spice_message
from ..widgets import Debouncer, Panel, ResultRow, label
from .base import Card


class _Converter(Panel):
    """One conversion direction: input line + result rows."""

    use_et = Signal(float)

    def __init__(self, title: str, placeholder: str, rows: list[tuple[str, bool]], extra: QWidget | None = None) -> None:
        super().__init__(title)
        self.inp = QLineEdit()
        self.inp.setPlaceholderText(placeholder)
        self.inp.setProperty("mono", True)
        self.inp.setClearButtonEnabled(True)
        row = QHBoxLayout()
        row.addWidget(self.inp, 1)
        if extra is not None:
            row.addWidget(extra)
        self.body.addLayout(row)
        self.err = label("", "error", wrap=True)
        self.err.hide()
        self.body.addWidget(self.err)
        self.rows = [ResultRow(cap, big) for cap, big in rows]
        for r in self.rows:
            self.body.addWidget(r)
        self.send = QPushButton("Use this epoch in Observation Geometry  →")
        self.send.setProperty("flat", True)
        self.send.setEnabled(False)
        self.body.addWidget(self.send)
        self.body.addStretch(1)
        self._et: float | None = None
        self.send.clicked.connect(lambda: self._et is not None and self.use_et.emit(self._et))

    def show_error(self, msg: str) -> None:
        self.err.setText(msg)
        self.err.setVisible(bool(msg))
        for r in self.rows:
            r.clear()
        self._et = None
        self.send.setEnabled(False)

    def show_ok(self, et: float, texts: list[str]) -> None:
        self.err.hide()
        for r, t in zip(self.rows, texts):
            r.set_text(t)
        self._et = et
        self.send.setEnabled(True)


class TimeCard(Card):
    title = "Time Converter"
    subtitle = "UTC ⇄ ET (TDB seconds past J2000)"
    glyph = "◷"

    def build(self, root: QWidget) -> None:
        lay = QVBoxLayout(root)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(16)
        lay.addWidget(label(self.title, "h1"))
        lay.addWidget(label("Leap seconds come from the LSK in the loaded metakernel. UTC accepts ISO (2027-04-06T07:48:34.000), "
                            "calendar (2027 APR 06 07:48:34) and day-of-year (2027-096T07:48:34) formats.", "muted", wrap=True))

        now = QPushButton("Now")
        now.clicked.connect(self._now)
        self.a = _Converter("UTC → ET", "2027-04-06T07:48:34.000",
                            [("ET  [s past J2000]", True), ("UTC (ISO)", False), ("UTC (day of year)", False), ("TDB calendar", False)], now)
        self.prec = QComboBox()
        for p in range(0, 7):
            self.prec.addItem(f"{p} decimals" if p != 1 else "1 decimal", p)
        self.prec.setCurrentIndex(3)
        self.b = _Converter("ET → UTC", "866764869.184",
                            [("UTC (ISO)", True), ("UTC (day of year)", False), ("TDB calendar", False)], self.prec)

        cols = QHBoxLayout()
        cols.setSpacing(16)
        cols.addWidget(self.a, 1)
        cols.addWidget(self.b, 1)
        lay.addLayout(cols, 1)

        self._da, self._db = Debouncer(self._update_a), Debouncer(self._update_b)
        self.a.inp.textChanged.connect(self._da)
        self.b.inp.textChanged.connect(self._db)
        self.prec.currentIndexChanged.connect(lambda *_: self._update_b())
        self.a.use_et.connect(self._forward)
        self.b.use_et.connect(self._forward)
        self.send_to_geometry = lambda et: None  # wired by the main window

    def _forward(self, et: float) -> None:
        self.send_to_geometry(et)

    def _now(self) -> None:
        self.a.inp.setText(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3])

    def _update_a(self) -> None:
        text = self.a.inp.text().strip()
        if not text:
            self.a.show_error("")
            return
        try:
            et = timeconv.utc_to_et(text)
            self.a.show_ok(et, [f"{et:.6f}", timeconv.et_to_utc(et, 6), timeconv.et_to_utc_doy(et, 6), timeconv.et_to_tdb(et, 6)])
        except UtilityError as exc:
            self.a.show_error(str(exc))

    def _update_b(self) -> None:
        text = self.b.inp.text().strip().replace(",", ".")
        if not text:
            self.b.show_error("")
            return
        p = self.prec.currentData()
        try:
            et = float(text)
            self.b.show_ok(et, [timeconv.et_to_utc(et, p), timeconv.et_to_utc_doy(et, p), timeconv.et_to_tdb(et, p)])
        except ValueError:
            self.b.show_error(f"'{text}' is not a number (ET is seconds past J2000 TDB).")
        except Exception as exc:  # SPICE: out of LSK range etc.
            self.b.show_error(f"Cannot convert: {spice_message(exc)}")

    def set_et(self, et: float) -> None:
        self.b.inp.setText(f"{et:.6f}")

    def kernels_changed(self) -> None:
        self._update_a()
        self._update_b()
