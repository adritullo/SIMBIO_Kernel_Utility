from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

BG = "#0d1015"
SURFACE = "#141920"
SURFACE_2 = "#1a2029"
BORDER = "#252c38"
TEXT = "#e6e9ef"
MUTED = "#8b94a5"
ACCENT = "#f2a93b"
ACCENT_HI = "#ffc062"
DANGER = "#ff6b6b"
OK = "#4cd1a0"

SEASON_COLORS = {"APH": "#7aa2ff", "PER": "#ff7f5c", "D2N": "#b58cff", "N2D": "#4fd0d6"}
SEASON_NAMES = {"APH": "Aphelion", "PER": "Perihelion", "D2N": "Terminator · day → night", "N2D": "Terminator · night → day"}

from ..resources import resource_path

ARROW = resource_path("arrow-down.png").as_posix()
CHECK = resource_path("check.png").as_posix()
MONO = "Cascadia Mono, Consolas, 'DejaVu Sans Mono', monospace"
SANS = "Segoe UI Variable Text, Segoe UI, Inter, 'DejaVu Sans', sans-serif"

QSS = f"""
* {{ font-family: {SANS}; font-size: 13px; color: {TEXT}; }}
QMainWindow, QWidget#root {{ background: {BG}; }}
QToolTip {{ background: {SURFACE_2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px 8px; }}

QFrame#sidebar {{ background: {SURFACE}; border-right: 1px solid {BORDER}; }}
QFrame#topbar {{ background: {BG}; border-bottom: 1px solid {BORDER}; }}
QFrame[panel="true"] {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 14px; }}
QFrame[tile="true"] {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame[tile="true"]:hover {{ border-color: {ACCENT}; }}
QFrame[panel="true"] QLabel, QFrame[tile="true"] QLabel {{ background: transparent; border: none; }}

QLabel[role="brand"] {{ font-size: 19px; font-weight: 700; letter-spacing: 1px; }}
QLabel[role="brandsub"] {{ color: {MUTED}; font-size: 11px; letter-spacing: 2px; }}
QLabel[role="h1"] {{ font-size: 20px; font-weight: 650; }}
QLabel[role="h2"] {{ font-size: 13px; font-weight: 650; color: {MUTED}; letter-spacing: 1px; }}
QLabel[role="muted"] {{ color: {MUTED}; }}
QLabel[role="small"] {{ color: {MUTED}; font-size: 11px; }}
QLabel[role="tilelabel"] {{ color: {MUTED}; font-size: 11px; font-weight: 600; letter-spacing: 1px; }}
QLabel[role="value"] {{ font-family: {MONO}; font-size: 20px; font-weight: 600; }}
QLabel[role="valuebig"] {{ font-family: {MONO}; font-size: 17px; font-weight: 600; color: {ACCENT_HI}; }}
QLabel[role="mono"] {{ font-family: {MONO}; }}
QLabel[role="unit"] {{ color: {MUTED}; font-size: 12px; }}
QLabel[role="error"] {{ color: {DANGER}; }}
QLabel[role="note"] {{ color: {MUTED}; font-size: 11px; }}

QLabel[pill="idle"] {{ background: {SURFACE_2}; color: {MUTED}; border: 1px solid {BORDER}; border-radius: 11px; padding: 3px 12px; }}
QLabel[pill="ok"] {{ background: rgba(76,209,160,0.12); color: {OK}; border: 1px solid rgba(76,209,160,0.45); border-radius: 11px; padding: 3px 12px; }}
QLabel[pill="err"] {{ background: rgba(255,107,107,0.12); color: {DANGER}; border: 1px solid rgba(255,107,107,0.45); border-radius: 11px; padding: 3px 12px; }}

QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {{
    background: {BG}; border: 1px solid {BORDER}; border-radius: 9px; padding: 8px 12px; selection-background-color: {ACCENT}; selection-color: #1a1204; }}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus {{ border-color: {ACCENT}; }}
QLineEdit[mono="true"] {{ font-family: {MONO}; }}
QLineEdit:read-only {{ color: {MUTED}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url({ARROW}); width: 12px; height: 8px; margin-right: 10px; }}
QComboBox QAbstractItemView {{ background: {SURFACE_2}; border: 1px solid {BORDER}; selection-background-color: {BORDER}; outline: none; padding: 4px; }}
QComboBox:disabled, QLineEdit:disabled {{ color: {MUTED}; }}

QPushButton {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 9px; padding: 8px 16px; }}
QPushButton:hover {{ background: #232b37; border-color: #343d4c; }}
QPushButton:pressed {{ background: {BG}; }}
QPushButton:disabled {{ color: #5b6475; background: {SURFACE}; }}
QPushButton[primary="true"] {{ background: {ACCENT}; border: none; color: #1a1204; font-weight: 700; padding: 9px 20px; }}
QPushButton[primary="true"]:hover {{ background: {ACCENT_HI}; }}
QPushButton[primary="true"]:disabled {{ background: #4a3a1c; color: #8c7a55; }}
QPushButton[flat="true"] {{ background: transparent; border: none; color: {MUTED}; padding: 4px 8px; }}
QPushButton[flat="true"]:hover {{ color: {ACCENT_HI}; background: transparent; }}

QPushButton[nav="true"] {{ background: transparent; border: none; border-radius: 10px; text-align: left; padding: 11px 14px; color: {MUTED}; font-weight: 600; }}
QPushButton[nav="true"]:hover {{ background: {SURFACE_2}; color: {TEXT}; }}
QPushButton[nav="true"]:checked {{ background: {SURFACE_2}; color: {ACCENT_HI}; }}

QPushButton[segment="true"] {{ background: {BG}; border: 1px solid {BORDER}; border-radius: 0; padding: 6px 16px; color: {MUTED}; font-weight: 600; }}
QPushButton[segment="true"]:checked {{ background: {ACCENT}; color: #1a1204; border-color: {ACCENT}; }}

QCheckBox {{ spacing: 9px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid #3a4456; background: {BG}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: url({CHECK}); }}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2c3442; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #3b4658; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ height: 0; }}
QGraphicsView {{ background: #07090c; border: 1px solid {BORDER}; border-radius: 10px; }}
QDialog {{ background: {BG}; }}
QStatusBar {{ background: {BG}; color: {MUTED}; border-top: 1px solid {BORDER}; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    for role, color in ((QPalette.Window, BG), (QPalette.Base, BG), (QPalette.AlternateBase, SURFACE),
                        (QPalette.Text, TEXT), (QPalette.WindowText, TEXT), (QPalette.Button, SURFACE_2),
                        (QPalette.ButtonText, TEXT), (QPalette.Highlight, ACCENT), (QPalette.HighlightedText, "#1a1204"),
                        (QPalette.ToolTipBase, SURFACE_2), (QPalette.ToolTipText, TEXT), (QPalette.PlaceholderText, "#5b6475")):
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    try:  # dark native title bar on Windows 11 / Qt >= 6.8
        from PySide6.QtCore import Qt
        app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    except Exception:
        pass
    app.setStyleSheet(QSS)
