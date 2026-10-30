from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel,
                               QPushButton, QSizePolicy, QToolTip, QVBoxLayout, QWidget)

from . import theme


def label(text: str = "", role: str | None = None, wrap: bool = False, selectable: bool = False) -> QLabel:
    lb = QLabel(text)
    if role:
        lb.setProperty("role", role)
    lb.setWordWrap(wrap)
    if selectable:
        lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lb


def copy_to_clipboard(text: str) -> None:
    QApplication.clipboard().setText(text)


class Panel(QFrame):
    """Rounded surface with an optional small-caps title."""

    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("panel", True)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(20, 18, 20, 20)
        self.body.setSpacing(12)
        if title:
            self.body.addWidget(label(title.upper(), "h2"))


class Tile(QFrame):
    """Metric tile: caption, big monospaced value, unit. Click to copy the value."""

    def __init__(self, caption: str, unit: str = "", hint: str = "") -> None:
        super().__init__()
        self.setProperty("tile", True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip((hint + "\n" if hint else "") + "Click to copy the value")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 13, 16, 14)
        lay.setSpacing(4)
        lay.addWidget(label(caption.upper(), "tilelabel"))
        row = QHBoxLayout()
        row.setSpacing(6)
        self.value = label("—", "value")
        self.unit = label(unit, "unit")
        row.addWidget(self.value, 0, Qt.AlignBaseline)
        row.addWidget(self.unit, 0, Qt.AlignBaseline)
        row.addStretch(1)
        lay.addLayout(row)
        self._raw = ""

    def set_hint(self, hint: str) -> None:
        self.setToolTip((hint + "\n" if hint else "") + "Click to copy the value")

    def set_value(self, text: str, raw: str | None = None) -> None:
        self.value.setText(text)
        self._raw = raw if raw is not None else text

    def clear(self) -> None:
        self.set_value("—", "")

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if self._raw:
            copy_to_clipboard(self._raw)
            QToolTip.showText(e.globalPosition().toPoint(), "Copied", self, self.rect(), 900)


class ResultRow(QWidget):
    """label | selectable monospaced value | copy button."""

    def __init__(self, caption: str, big: bool = False) -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        cap = label(caption, "muted")
        cap.setFixedWidth(150)
        self.value = label("—", "valuebig" if big else "mono", selectable=True)
        self.btn = QPushButton("Copy")
        self.btn.setProperty("flat", True)
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.clicked.connect(lambda: copy_to_clipboard(self.value.text()) if self.value.text() != "—" else None)
        lay.addWidget(cap)
        lay.addWidget(self.value, 1)
        lay.addWidget(self.btn)

    def set_text(self, text: str) -> None:
        self.value.setText(text or "—")

    def clear(self) -> None:
        self.value.setText("—")


class Segmented(QWidget):
    """Two-or-more option pill switch."""

    changed = Signal(int)

    def __init__(self, options: list[str]) -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for i, text in enumerate(options):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setProperty("segment", "true")
            b.setProperty("pos", "left" if i == 0 else "right" if i == len(options) - 1 else "mid")
            self.group.addButton(b, i)
            lay.addWidget(b)
        self.group.button(0).setChecked(True)
        self.group.idClicked.connect(self.changed)
        self.setStyleSheet(
            "QPushButton[pos='left']{border-top-left-radius:9px;border-bottom-left-radius:9px;}"
            "QPushButton[pos='right']{border-top-right-radius:9px;border-bottom-right-radius:9px;border-left:none;}"
            "QPushButton[pos='mid']{border-left:none;}")

    def index(self) -> int:
        return self.group.checkedId()

    def set_index(self, i: int) -> None:
        self.group.button(i).setChecked(True)


class Debouncer:
    def __init__(self, fn, ms: int = 180) -> None:
        self.t = QTimer()
        self.t.setSingleShot(True)
        self.t.setInterval(ms)
        self.t.timeout.connect(fn)

    def __call__(self, *_a) -> None:
        self.t.start()


def _nice_length(target_m: float) -> float:
    if target_m <= 0:
        return 1.0
    mag = 10 ** math.floor(math.log10(target_m))
    for m in (1, 2, 5, 10):
        if m * mag >= target_m * 0.6:
            return m * mag
    return 10 * mag


class ImageView(QGraphicsView):
    """Pan/zoom image viewer with a fixed compass (north up, arrow towards the Sun) and a scale bar."""

    def __init__(self) -> None:
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(QPainter.SmoothPixmapTransform | QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self._item = None
        self._fit = True
        self.sun_az: float | None = None
        self.pixel_size_m = 1.0
        self.message = ""
        self._qimg: QImage | None = None

    def set_image(self, gray: "np.ndarray", sun_az: float | None, pixel_size_m: float, message: str = "") -> None:
        import numpy as np
        h, w = gray.shape
        self._qimg = QImage(np.ascontiguousarray(gray).data, w, h, w, QImage.Format_Grayscale8).copy()
        self._scene.clear()
        self._item = self._scene.addPixmap(QPixmap.fromImage(self._qimg))
        self._scene.setSceneRect(QRectF(0, 0, w, h))
        self.sun_az, self.pixel_size_m, self.message = sun_az, pixel_size_m, message
        self._fit = True
        self.fit()
        self.viewport().update()

    def png(self, path: str) -> bool:
        pm = self.grab()
        return pm.save(path)

    def fit(self) -> None:
        if self._item is not None:
            self.fitInView(self._item, Qt.KeepAspectRatio)
        self._sync_smoothing()

    def _sync_smoothing(self) -> None:
        # magnified -> show true (blocky) instrument pixels; shrunk -> smooth
        self.setRenderHint(QPainter.SmoothPixmapTransform, self.transform().m11() < 1.0)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        if self._fit:
            self.fit()

    def wheelEvent(self, e) -> None:  # noqa: N802
        f = 1.18 if e.angleDelta().y() > 0 else 1 / 1.18
        self._fit = False
        self.scale(f, f)
        self._sync_smoothing()

    def mouseDoubleClickEvent(self, e) -> None:  # noqa: N802
        self._fit = True
        self.fit()

    def drawForeground(self, p: QPainter, rect: QRectF) -> None:  # noqa: N802
        p.save()
        p.resetTransform()
        p.setRenderHint(QPainter.Antialiasing)
        vw, vh = self.viewport().width(), self.viewport().height()
        # compass (bottom-left)
        c, r = QPointF(56, vh - 56), 32.0
        p.setPen(QPen(QColor(255, 255, 255, 90), 1.2))
        p.setBrush(QColor(0, 0, 0, 120))
        p.drawEllipse(c, r, r)
        p.setPen(QPen(QColor(255, 255, 255, 190), 1.4))
        p.drawLine(c + QPointF(0, -r), c + QPointF(0, -r + 7))
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255, 210))
        p.drawText(QRectF(c.x() - 8, c.y() - r - 17, 16, 14), Qt.AlignCenter, "N")
        if self.sun_az is not None:
            a = math.radians(self.sun_az)
            tip = c + QPointF(math.sin(a), -math.cos(a)) * (r - 5)
            tail = c - QPointF(math.sin(a), -math.cos(a)) * (r - 17)
            p.setPen(QPen(QColor(theme.ACCENT), 2.6, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(tail, tip)
            p.setBrush(QColor(theme.ACCENT))
            p.setPen(Qt.NoPen)
            ux, uy = math.sin(a), -math.cos(a)
            left = tip - QPointF(ux, uy) * 9 + QPointF(-uy, ux) * 4.5
            right = tip - QPointF(ux, uy) * 9 - QPointF(-uy, ux) * 4.5
            p.drawPolygon(QPolygonF([tip, left, right]))
        # scale bar (bottom-right)
        if self._item is not None and self.pixel_size_m > 0:
            scale = self.transform().m11()
            if scale > 0:
                bar_m = _nice_length(110 / scale * self.pixel_size_m)
                bar_px = bar_m / self.pixel_size_m * scale
                x1, y = vw - 18, vh - 22
                p.setPen(QPen(QColor(255, 255, 255, 220), 2))
                p.drawLine(QPointF(x1 - bar_px, y), QPointF(x1, y))
                p.drawLine(QPointF(x1 - bar_px, y - 4), QPointF(x1 - bar_px, y + 4))
                p.drawLine(QPointF(x1, y - 4), QPointF(x1, y + 4))
                txt = f"{bar_m / 1000:g} km" if bar_m >= 1000 else f"{bar_m:g} m"
                p.drawText(QRectF(x1 - bar_px - 20, y - 24, bar_px + 40, 16), Qt.AlignCenter, txt)
        if self.message:
            f.setPointSizeF(11)
            p.setFont(f)
            p.setPen(QColor(255, 255, 255, 230))
            p.drawText(QRectF(0, 0, vw, vh), Qt.AlignCenter, self.message)
        p.restore()
