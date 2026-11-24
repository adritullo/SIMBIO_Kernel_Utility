from __future__ import annotations

import os
import sys


def apply_ui_scale() -> None:
    """Interface size from Settings, applied before the QApplication exists (Qt reads QT_SCALE_FACTOR only at start).
    An explicit QT_SCALE_FACTOR in the environment wins."""
    if "QT_SCALE_FACTOR" in os.environ:
        return
    try:
        from simbio_utility.config import AppConfig
        s = AppConfig().ui_scale
    except Exception:
        return
    if abs(s - 1.0) > 1e-3:
        os.environ["QT_SCALE_FACTOR"] = f"{s:g}"


def restart() -> None:
    """Start a fresh copy of the app (frozen exe or `python run.py`) and quit this one."""
    from PySide6.QtCore import QProcess
    from PySide6.QtWidgets import QApplication
    if getattr(sys, "frozen", False):
        QProcess.startDetached(sys.executable, sys.argv[1:])
    else:
        QProcess.startDetached(sys.executable, sys.argv)
    QApplication.quit()


def main() -> int:
    apply_ui_scale()
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from simbio_utility import APP_NAME
    from simbio_utility.gui.main_window import MainWindow
    from simbio_utility.gui.theme import apply_theme
    from simbio_utility.resources import resource_path

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("INAF")
    apply_theme(app)
    app.setWindowIcon(QIcon(str(resource_path("icon.png"))))  # taskbar/dock/title bar on Linux, macOS and source runs
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
