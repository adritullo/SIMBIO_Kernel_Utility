from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QScrollArea, QStackedLayout, QVBoxLayout, QWidget

from ...config import AppConfig
from ..widgets import label


class Card(QWidget):
    """Base class of a function page. Subclasses set the class attributes and implement ``build``.

    * ``kernels_changed()`` is called after a metakernel (re)load so the card can refresh its lists
    * the card is shown behind a placeholder until kernels are loaded (``needs_kernels``)
    """

    title = "Card"
    subtitle = ""
    glyph = "•"  # short sidebar prefix
    needs_kernels = True

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self._stack = QStackedLayout(self)
        self.content = QWidget()
        self.build(self.content)
        # small screens / large scaling: the card scrolls instead of forcing a huge window
        self.scroller = QScrollArea()
        self.scroller.setWidgetResizable(True)
        self.scroller.setFrameShape(QFrame.NoFrame)
        self.scroller.setWidget(self.content)
        self._stack.addWidget(self.scroller)
        ph = QWidget()
        pl = QVBoxLayout(ph)
        pl.setAlignment(Qt.AlignCenter)
        pl.addWidget(label("Load a metakernel to start", "h1"), 0, Qt.AlignCenter)
        pl.addWidget(label("Choose a BepiColombo .tm file in the bar above — it is used by every card.", "muted"), 0, Qt.AlignCenter)
        self._stack.addWidget(ph)
        self.set_ready(not self.needs_kernels)

    #: the input panel on the left (set by the subclass); narrowed on small windows so the results keep the room
    left_panel: QWidget | None = None
    left_max = 460

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        if self.left_panel is not None:
            self.left_panel.setMaximumWidth(max(300, min(self.left_max, int(self.width() * 0.42))))

    def build(self, root: QWidget) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def set_ready(self, ready: bool) -> None:
        self._stack.setCurrentIndex(0 if ready else 1)

    def kernels_changed(self) -> None:
        pass

    def shutdown(self) -> None:
        pass
