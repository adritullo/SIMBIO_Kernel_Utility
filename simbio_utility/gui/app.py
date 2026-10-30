from __future__ import annotations

import sys


def main() -> int:
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
