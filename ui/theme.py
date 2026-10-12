"""theme.py — dark launcher theme for PyQt6 / PySide6.

One place for every colour, radius and size. Widget code should import the
constants from here (or use the QSS classes) and never hard-code a hex value.

    from PyQt6.QtWidgets import QApplication
    import theme

    app = QApplication(sys.argv)
    theme.apply(app)          # Fusion + palette + font + stylesheet
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

Works with either binding: the import shim below picks whichever is installed.
"""

from __future__ import annotations

import sys
from pathlib import Path
from string import Template

# --------------------------------------------------------------------------
# binding shim — PyQt6 first, then PySide6
# --------------------------------------------------------------------------
BINDING = ""

try:
    from PyQt6.QtCore import QPointF, QRectF, Qt, qInstallMessageHandler
    from PyQt6.QtGui import (
        QColor, QFont, QFontDatabase, QIcon, QLinearGradient, QPainter,
        QPainterPath, QPalette, QPen, QPixmap,
    )
    from PyQt6.QtWidgets import QApplication, QWidget

    import PyQt6.QtSvg  # noqa: F401  (registers the SVG image plugin)
    BINDING = "PyQt6"
except ModuleNotFoundError as pyqt_error:  # pragma: no cover
    if pyqt_error.name != "PyQt6":
        raise
    try:
        from PySide6.QtCore import QPointF, QRectF, Qt, qInstallMessageHandler
        from PySide6.QtGui import (
            QColor, QFont, QFontDatabase, QIcon, QLinearGradient, QPainter,
            QPainterPath, QPalette, QPen, QPixmap,
        )
        from PySide6.QtWidgets import QApplication, QWidget

        import PySide6.QtSvg  # noqa: F401
        BINDING = "PySide6"
    except ModuleNotFoundError as pyside_error:
        if pyside_error.name != "PySide6":
            raise
        raise ModuleNotFoundError(
            "The desktop GUI requires PyQt6 or PySide6. Install one with "
            "'python -m pip install PyQt6' using the same Python interpreter "
            "that launches the GUI."
        ) from pyside_error


# --------------------------------------------------------------------------
# shared design tokens
# --------------------------------------------------------------------------
from theme_tokens import FONT_FAMILIES, FONT_MONO, RADIUS, SP, TOKENS

BG_APP = TOKENS["bg_app"]
BG_PANEL = TOKENS["bg_panel"]
BORDER = TOKENS["border"]
TEXT_PRIMARY = TOKENS["text_primary"]
TEXT_SECONDARY = TOKENS["text_secondary"]
TEXT_TERTIARY = TOKENS["text_tertiary"]
TEXT_ACCENT = TOKENS["text_accent"]
ACCENT = TOKENS["accent"]
OK = TOKENS["ok"]
WARN = TOKENS["warn"]
DANGER = TOKENS["danger"]

ASSETS_DIR = Path(__file__).resolve().parent / "assets" / "icons"
FONT_DIR = Path(__file__).resolve().parent / "assets" / "fonts"

_ICONS = {
    "check.svg": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" '
        'fill="none" stroke="#ffffff" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M20 6L9 17l-5-5"/></svg>'
    ),
    "chevron-down.svg": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" '
        'fill="none" stroke="#8A90A8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M6 9l6 6 6-6"/></svg>'
    ),
    "plus.svg": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" '
        'fill="none" stroke="#8A90A8" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M12 5v14M5 12h14"/></svg>'
    ),
    "bell.svg": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" '
        'fill="none" stroke="#8A90A8" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M12 3a5 5 0 0 0-5 5v4l-2 3h14l-2-3V8a5 5 0 0 0-5-5z"/><path d="M10 19a2 2 0 0 0 4 0"/></svg>'
    ),
    "play.svg": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
        'fill="none" stroke="#ffffff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M8 5l11 7-11 7z"/></svg>'
    ),
}


def ensure_assets(directory: Path | str = ASSETS_DIR) -> Path:
    """Write the small SVG assets (check, chevron, plus, bell, play) if missing."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for name, svg in _ICONS.items():
        path = directory / name
        if not path.exists():
            path.write_text(svg, encoding="utf-8")
    return directory


# --------------------------------------------------------------------------
# stylesheet — generated from the tokens above
# --------------------------------------------------------------------------
QSS = Template("""
/* ---------- base ---------- */
QWidget { color: $text_primary; font-size: 13px; font-family: "$font_family"; }
QMainWindow, QDialog, QWidget#AppRoot { background-color: $bg_app; }
QToolTip {
    background-color: $bg_raised; color: $text_primary;
    border: 1px solid $border; border-radius: 6px; padding: 6px 8px; font-size: 12px;
}

/* ---------- structural ---------- */
QFrame[role="titlebar"] { background-color: $bg_chrome; border: 0; border-bottom: 1px solid $border; }
QFrame[role="header"]   { background-color: $bg_chrome; border: 0; border-bottom: 1px solid $border; }
/* Persistent status banner under the header: the live figures, on every page. */
QFrame[role="banner"]   { background-color: $bg_panel; border: 0; border-bottom: 1px solid $border; }
QFrame[role="sidebar"]  { background-color: $bg_panel;  border: 1px solid $border; border-radius: 6px; }
QFrame[role="panel"]    { background-color: $bg_panel;  border: 1px solid $border; border-radius: 6px; }
QFrame[role="card"]     { background-color: $bg_raised; border: 1px solid $border; border-radius: 6px; }
QFrame[role="divider"]  { background-color: $border; border: 0; }
/* Grouped settings container inside a panel: one bordered block per topic. */
QFrame[role="group"]    { background-color: $bg_raised; border: 1px solid $border; border-radius: 6px; }
QFrame[role="section"]  { background-color: $bg_panel;  border: 1px solid $border; border-radius: 6px; }
/* The 240px preview surface. Near-black so detection overlays read clearly. */
QFrame[role="preview"]  { background-color: $bg_input;  border: 1px solid $border; border-radius: 6px; }
QLabel[role="preview"]  { background-color: $bg_input; border: 1px solid $border; border-radius: 6px; }
QFrame[role="swatch"]   { border: 1px solid $border_strong; border-radius: 4px; }
/* Sidebar navigation rail: grouped, quiet, one active row. */
QFrame[role="rail"]     { background-color: $bg_panel; border: 1px solid $border; border-radius: 6px; }
/* Right-hand telemetry/inspector column. */
QFrame[role="inspector"]{ background-color: $bg_panel; border: 1px solid $border; border-radius: 6px; }
/* Hero band behind the page head. Painted only as a thin 2px accent rule. */
QFrame[role="accent-rule"] { background-color: $accent; border: 0; border-radius: 2px; }
/* Grouped settings block inside a panel: one bordered topic per group. */
QFrame[role="subsection"] { background-color: $bg_input; border: 1px solid $border; border-radius: 6px; }

/* ---------- quick menu (separate top-level window) ---------- */
QWidget#QuickMenu { background-color: $bg_panel; border: 1px solid $border_strong; border-radius: 6px; }
QFrame[variant="quickmenu-header"] {
    background-color: $bg_chrome; border: 0; border-bottom: 1px solid $border;
    border-top-left-radius: 6px; border-top-right-radius: 6px;
}
QFrame[variant="quickmenu-body"] { background-color: $bg_panel; border: 0; }
/* Compact rows inside the quick menu: a label, a value and a slim slider. */
QLabel[role="qm-section"] {
    color: $text_tertiary; font-size: 11px; font-weight: bold; padding-top: 2px;
}
QLabel[role="qm-title"] { color: $text_primary; font-size: 12px; }
QLabel[role="qm-value"] { color: $text_secondary; font-size: 11px; }

/* ---------- text ---------- */
QLabel { background: transparent; }
QLabel[role="page-title"] { font-size: 22px; font-weight: bold; }
QLabel[role="panel-title"] { font-size: 13px; font-weight: bold; }
QLabel[role="stat"] { font-size: 22px; font-weight: bold; }
QLabel[role="stat-ok"] { font-size: 22px; font-weight: bold; color: $ok; }
QLabel[role="label"] { font-size: 11px; color: $text_tertiary; }
QLabel[role="meta"] { font-size: 12px; color: $text_tertiary; }
QLabel[role="secondary"] { color: $text_secondary; }
QLabel[role="link"] { color: $text_accent; }
QLabel[role="dot"] {
    min-width: 6px; max-width: 6px; min-height: 6px; max-height: 6px;
    border-radius: 3px; background-color: $text_tertiary;
}
QLabel[role="dot-ok"] {
    min-width: 6px; max-width: 6px; min-height: 6px; max-height: 6px;
    border-radius: 3px; background-color: $ok;
}
QLabel[role="dot-warn"] {
    min-width: 6px; max-width: 6px; min-height: 6px; max-height: 6px;
    border-radius: 3px; background-color: $warn;
}
QLabel[role="dot-danger"] {
    min-width: 6px; max-width: 6px; min-height: 6px; max-height: 6px;
    border-radius: 3px; background-color: $danger;
}
QLabel[role="badge"] {
    background-color: $danger; color: #FFFFFF; border-radius: 4px;
    padding: 1px 5px; font-size: 10px; font-weight: bold;
}
QLabel[role="chip"] {
    background-color: $bg_raised; border: 1px solid $border; border-radius: 4px;
    padding: 4px 10px; font-size: 12px; color: $text_secondary;
}
QPushButton[variant="chip"] {
    background-color: $bg_raised; border: 1px solid $border; border-radius: 4px;
    padding: 0 10px; min-height: 26px; max-height: 26px; font-size: 12px; color: $text_secondary;
}
QPushButton[variant="chip"]:hover { color: $text_primary; }
QPushButton[variant="chip"]:checked {
    background-color: $accent_soft; border-color: $accent_line; color: $text_accent;
}

/* Section header inside a card: 11px uppercase, muted, tight tracking. */
QLabel[role="section"] {
    color: $text_tertiary; font-size: 11px; font-weight: bold; padding-top: 2px;
}
/* Metric tile used by the overview grid. */
QFrame[role="metric"] { background-color: $bg_raised; border: 1px solid $border; border-radius: 6px; }
QLabel[role="metric-value"] { font-size: 22px; font-weight: bold; }
QLabel[role="metric-unit"] { color: $text_tertiary; font-size: 12px; }
QLabel[role="avatar"] {
    background-color: $bg_raised; border: 1px solid $border_strong; border-radius: 14px;
    min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px;
    font-size: 11px; font-weight: bold; color: $text_secondary;
}
/* 11px uppercase group header used in the sidebar and inside cards. */
QLabel[role="group-header"] { color: $text_tertiary; font-size: 11px; font-weight: bold; }
/* Muted uppercase tag in the title bar. */
QLabel[role="tag"] { color: $text_tertiary; font-size: 11px; }
/* Status pill: colour is always paired with a text label. */
QLabel[role="pill"] {
    background-color: $bg_raised; border: 1px solid $border; border-radius: 4px;
    padding: 3px 9px; font-size: 11px; font-weight: bold; color: $text_secondary;
}
QLabel[role="pill-ok"] {
    background-color: $ok_soft; border: 1px solid $ok; border-radius: 4px;
    padding: 3px 9px; font-size: 11px; font-weight: bold; color: $ok;
}
QLabel[role="pill-warn"] {
    background-color: $bg_raised; border: 1px solid $warn; border-radius: 4px;
    padding: 3px 9px; font-size: 11px; font-weight: bold; color: $warn;
}
QLabel[role="pill-danger"] {
    background-color: $danger_soft; border: 1px solid $danger; border-radius: 4px;
    padding: 3px 9px; font-size: 11px; font-weight: bold; color: $danger;
}
/* Numeric / id columns read as data, not prose. */
QLabel[role="mono"] { font-size: 12px; color: $text_secondary; }
/* Small inline help line under a field. */
QLabel[role="help"] { font-size: 11px; color: $text_tertiary; }

/* ---------- buttons ---------- */
QPushButton {
    background-color: transparent; color: $text_primary;
    border: 1px solid $border_strong; border-radius: 4px;
    padding: 0 14px; min-height: 32px; font-size: 13px;
}
QPushButton:hover { background-color: $bg_raised; }
QPushButton:pressed { background-color: $bg_hover; }
QPushButton:focus { border-color: $accent; }
QPushButton:disabled { color: $text_tertiary; border-color: $border; }

QPushButton[variant="primary"] {
    background-color: $accent; border-color: $accent; color: #FFFFFF; font-weight: bold;
}
QPushButton[variant="primary"]:hover {
    background-color: $accent_hover; border-color: $accent_hover;
}
QPushButton[variant="primary"]:pressed {
    background-color: $accent_active; border-color: $accent_active;
}
QPushButton[variant="primary"]:disabled {
    background-color: $accent_disabled; border-color: $accent_disabled; color: $text_secondary;
}
QPushButton[variant="primary"]:focus { border-color: $text_primary; }

QPushButton[variant="dashed"] {
    border: 1px dashed $border_strong; color: $text_secondary; background: transparent;
}
QPushButton[variant="dashed"]:hover { border-color: $accent_line; color: $text_accent; }

QPushButton[variant="icon"] {
    min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px;
    padding: 0; border: 0; border-radius: 4px; background: transparent;
}
QPushButton[variant="icon"]:hover { background-color: $bg_raised; }

QPushButton[variant="navitem"] {
    border: 0; border-radius: 4px; background: transparent;
    color: $text_secondary; text-align: left; padding: 0 10px; min-height: 32px;
}
QPushButton[variant="navitem"]:hover { background-color: $bg_raised; color: $text_primary; }
QPushButton[variant="navitem"]:checked { background-color: $bg_raised; color: $text_primary; }
QPushButton[variant="navitem"]:pressed { background-color: $bg_hover; }
QPushButton[variant="navitem"]:focus { border: 1px solid $accent_line; }
QPushButton[variant="navitem"]:disabled { color: $text_tertiary; }

QPushButton[variant="windowtab"] {
    border: 0; border-radius: 4px; background: transparent;
    color: $text_tertiary; font-size: 11px; min-height: 24px; padding: 0 10px;
}
QPushButton[variant="windowtab"]:hover { background-color: $bg_raised; color: $text_primary; }
QPushButton[variant="windowtab"]:checked { background-color: $bg_raised; color: $text_primary; }

/* Sidebar navigation row: 32px, quiet, active row lifts one surface step. */
QPushButton[variant="navitem"] {
    border: 0; border-radius: 4px; background: transparent;
    color: $text_secondary; text-align: left; padding: 0 10px; min-height: 32px; font-size: 13px;
}
QPushButton[variant="navitem"]:hover { background-color: $bg_raised; color: $text_primary; }
QPushButton[variant="navitem"]:checked { background-color: $bg_raised; color: $text_primary; }
QPushButton[variant="navitem"]:pressed { background-color: $bg_hover; }
QPushButton[variant="navitem"]:focus { border: 1px solid $accent_line; }
QPushButton[variant="navitem"]:disabled { color: $text_tertiary; }

/* Ghost button: borderless until hover, for low-priority inline actions. */
QPushButton[variant="ghost"] {
    border: 1px solid transparent; border-radius: 4px; background: transparent;
    color: $text_secondary; padding: 0 10px; min-height: 28px; font-size: 12px;
}
QPushButton[variant="ghost"]:hover { background-color: $bg_raised; color: $text_primary; }
QPushButton[variant="ghost"]:pressed { background-color: $bg_hover; }
QPushButton[variant="ghost"]:focus { border-color: $accent; }
QPushButton[variant="ghost"]:disabled { color: $text_tertiary; }

/* Destructive action, used sparingly (emergency stop / remove profile). */
QPushButton[variant="danger"] {
    background-color: $danger_soft; border-color: $danger; color: #FFFFFF; font-weight: bold;
}
QPushButton[variant="danger"]:hover { background-color: $danger; border-color: $danger; }
QPushButton[variant="danger"]:pressed { background-color: $danger; border-color: $danger; }
QPushButton[variant="danger"]:focus { border-color: $text_primary; }
QPushButton[variant="danger"]:disabled { background-color: $bg_raised; border-color: $border; color: $text_tertiary; }

/* Segmented control: two or three mutually exclusive modes in one strip.
   Exclusive, so :checked is the only state that needs to read as active. */
QPushButton[variant="segment"] {
    border: 1px solid $border_strong; border-radius: 4px; background: transparent;
    color: $text_secondary; font-size: 12px; min-height: 28px; padding: 0 12px;
}
QPushButton[variant="segment"]:hover { background-color: $bg_raised; color: $text_primary; }
QPushButton[variant="segment"]:checked {
    background-color: $accent; border-color: $accent; color: #FFFFFF; font-weight: bold;
}
QPushButton[variant="segment"]:pressed { background-color: $accent_active; border-color: $accent_active; }
QPushButton[variant="segment"]:focus { border-color: $accent; }
QPushButton[variant="segment"]:disabled { color: $text_tertiary; border-color: $border; }

/* Icon-only button that sits in a toolbar row. */
QPushButton[variant="tool"] {
    border: 1px solid $border_strong; border-radius: 4px; background: transparent;
    color: $text_secondary; min-height: 28px; padding: 0 10px; font-size: 12px;
}
QPushButton[variant="tool"]:hover { background-color: $bg_raised; color: $text_primary; }
QPushButton[variant="tool"]:pressed { background-color: $bg_hover; }
QPushButton[variant="tool"]:focus { border-color: $accent; }
QPushButton[variant="tool"]:checked { background-color: $bg_raised; border-color: $accent_line; color: $text_primary; }
QPushButton[variant="tool"]:disabled { color: $text_tertiary; border-color: $border; }

/* ---------- tabs ---------- */
QTabWidget::pane { border: 0; }
QTabBar::tab {
    background: transparent; color: $text_secondary;
    padding: 6px 12px; margin-right: 4px; border: 0; border-radius: 4px; font-size: 13px;
}
QTabBar::tab:hover { background-color: $bg_raised; color: $text_primary; }
QTabBar::tab:selected { background-color: $accent; color: #FFFFFF; }

/* ---------- inputs ---------- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: $bg_input; color: $text_primary;
    border: 1px solid $border_strong; border-radius: 4px;
    padding: 0 10px; min-height: 32px;
    selection-background-color: $accent; selection-color: #FFFFFF;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: $accent; }
QLineEdit:disabled, QComboBox:disabled { color: $text_tertiary; border-color: $border; }
QComboBox::drop-down { border: 0; width: 22px; }
QComboBox::down-arrow { image: url("$chevron"); width: 12px; height: 12px; }
QComboBox QAbstractItemView {
    background-color: $bg_panel; color: $text_primary;
    border: 1px solid $border; padding: 4px;
    selection-background-color: $bg_raised; selection-color: $text_primary;
    outline: 0;
}
QComboBox QAbstractItemView::item { min-height: 28px; padding: 0 8px; border-radius: 4px; }
QComboBox QAbstractItemView::item:hover { background-color: $bg_raised; color: $text_primary; }

/* Numeric fields: restyle the stock Qt arrows, which otherwise sit on a
   pale system background and break the dark surface. */
QSpinBox, QDoubleSpinBox { padding: 0 6px 0 10px; }
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border; width: 16px; border: 0; background: transparent;
}
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-position: top right; margin: 3px 3px 0 0; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-position: bottom right; margin: 0 3px 3px 0; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    image: url("$chevron"); width: 10px; height: 10px;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: url("$chevron"); width: 10px; height: 10px;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {
    background-color: $bg_raised; border-radius: 3px;
}

QCheckBox { spacing: 10px; font-size: 13px; color: $text_primary; }
QCheckBox::indicator {
    width: 16px; height: 16px; border: 1px solid $border_strong;
    border-radius: 3px; background-color: $bg_input;
}
QCheckBox::indicator:hover { border-color: $accent_line; }
QCheckBox::indicator:checked { background-color: $accent; border-color: $accent; image: url("$check"); }
QCheckBox::indicator:disabled { border-color: $border; background-color: $bg_panel; }
QCheckBox:focus::indicator { border-color: $accent; }
QCheckBox:disabled { color: $text_tertiary; }

QRadioButton { spacing: 10px; font-size: 13px; }
QRadioButton::indicator {
    width: 16px; height: 16px; border: 1px solid $border_strong;
    border-radius: 8px; background-color: $bg_input;
}
QRadioButton::indicator:checked { border: 5px solid $accent; background-color: $text_primary; }
QSlider:horizontal { min-height: 20px; }
QSlider::groove:horizontal { height: 4px; background-color: $border; border-radius: 2px; }
QSlider::sub-page:horizontal { background-color: $accent; border-radius: 2px; }
QSlider::add-page:horizontal { background-color: $bg_input; border-radius: 2px; }
QSlider::handle:horizontal { background-color: $text_primary; border: 2px solid $accent; width: 12px; height: 12px; margin: -5px 0; border-radius: 4px; }
QSlider::handle:horizontal:hover { background-color: $text_accent; }
QSlider::handle:horizontal:pressed { background-color: $accent_hover; }
QSlider:focus::handle:horizontal { border-color: $text_primary; }
QSlider:disabled::handle:horizontal { background-color: $text_tertiary; border-color: $border; }

/* ---------- scrollbars ---------- */
QScrollBar:vertical { background: transparent; width: 10px; margin: 0; border: 0; }
QScrollBar::handle:vertical {
    background-color: $border_strong; border-radius: 5px; min-height: 32px;
}
QScrollBar::handle:vertical:hover { background-color: $bg_hover; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; border: 0; }
QScrollBar::handle:horizontal {
    background-color: $border_strong; border-radius: 5px; min-width: 32px;
}
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; border: 0; background: transparent; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* ---------- item views ---------- */
QListWidget, QListView, QTreeWidget, QTreeView {
    background-color: transparent; border: 0; padding: 2px; font-size: 13px;
}
QListWidget::item { min-height: 32px; padding-left: 10px; border-radius: 4px; color: $text_secondary; }
QListWidget::item:hover { background-color: $bg_raised; color: $text_primary; }
QListWidget::item:selected { background-color: $bg_raised; color: $text_primary; }

QTableView, QTableWidget {
    background-color: $bg_panel; alternate-background-color: $bg_panel;
    border: 1px solid $border; border-radius: 6px; font-size: 12px;
    gridline-color: $border;
    selection-background-color: $bg_raised; selection-color: $text_primary;
}
QHeaderView::section {
    background-color: $bg_panel; color: $text_tertiary;
    border: 0; border-bottom: 1px solid $border;
    padding: 8px 10px; font-size: 11px; font-weight: bold;
}
QTableCornerButton::section { background-color: $bg_panel; border: 0; }

/* ---------- chrome ---------- */
QMenu {
    background-color: $bg_panel; color: $text_primary;
    border: 1px solid $border; border-radius: 6px; padding: 4px;
}
QMenu::item { padding: 6px 12px; border-radius: 4px; font-size: 13px; }
QMenu::item:selected { background-color: $bg_raised; }
QMenu::separator { height: 1px; background: $border; margin: 4px 8px; }

QProgressBar {
    background-color: $bg_input; border: 1px solid $border;
    border-radius: 4px; min-height: 6px; max-height: 6px; color: transparent;
}
QProgressBar::chunk { background-color: $accent; border-radius: 3px; }

QSplitter::handle { background-color: $border; width: 1px; }

QStatusBar { background-color: $bg_chrome; color: $text_secondary; border-top: 1px solid $border; }
""")


def qss(assets_dir: Path | str | None = None, family: str | None = None) -> str:
    """Return the generated stylesheet. Generates the icons if they are missing."""
    directory = ensure_assets(assets_dir or ASSETS_DIR)
    values = dict(TOKENS)
    values["font_family"] = family or FONT_FAMILIES[0]
    values["check"] = (directory / "check.svg").as_posix()
    values["chevron"] = (directory / "chevron-down.svg").as_posix()
    return QSS.substitute(values)


# --------------------------------------------------------------------------
# palette, font, application
# --------------------------------------------------------------------------
def _palette() -> QPalette:
    p = QPalette()
    role = QPalette.ColorRole
    pairs = {
        role.Window: BG_APP,
        role.WindowText: TEXT_PRIMARY,
        role.Base: TOKENS["bg_input"],
        role.AlternateBase: TOKENS["bg_raised"],
        role.Text: TEXT_PRIMARY,
        role.Button: BG_PANEL,
        role.ButtonText: TEXT_PRIMARY,
        role.BrightText: "#FFFFFF",
        role.Highlight: ACCENT,
        role.HighlightedText: "#FFFFFF",
        role.ToolTipBase: TOKENS["bg_raised"],
        role.ToolTipText: TEXT_PRIMARY,
        role.PlaceholderText: TEXT_TERTIARY,
        role.Link: TEXT_ACCENT,
    }
    for r, colour in pairs.items():
        p.setColor(r, QColor(colour))
    for r in (role.Text, role.WindowText, role.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, r, QColor(TEXT_TERTIARY))
    return p


def load_fonts(directory: Path | str = FONT_DIR) -> list:
    """Register the bundled font files so Inter ships with the app.

    Inter is installed under ``assets/fonts/`` as four static faces
    (Regular/Medium/SemiBold/Bold) so each weight resolves to the right face
    instead of a synthesised one. Qt6 cannot open ``.woff2``, so only TrueType
    and OpenType files are picked up here.

    Without these files ``resolve_family()`` falls back to the first family
    from FONT_FAMILIES the machine actually has.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return []
    loaded = []
    patterns = ("*.ttf", "*.otf")
    paths = sorted({path for pattern in patterns for path in directory.glob(pattern)})
    for path in paths:
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id != -1:
            loaded.extend(QFontDatabase.applicationFontFamilies(font_id))
    return loaded


def resolve_family() -> str:
    """First available family from FONT_FAMILIES, else whatever Qt picked."""
    available = set(QFontDatabase.families())
    for family in FONT_FAMILIES:
        if family in available:
            return family
    return QApplication.font().family() if QApplication.instance() else FONT_FAMILIES[0]


def label_font(pixel_size: int = 13, weight: str = "regular", tracking: float = 0.0) -> QFont:
    """QFont with pixel sizing and optional letter-spacing (QSS cannot do either)."""
    weights = {
        "regular": QFont.Weight.Normal,
        "medium": QFont.Weight.Medium,
        "semibold": QFont.Weight.DemiBold,
        "bold": QFont.Weight.Bold,
    }
    font = QFont(resolve_family())
    font.setPixelSize(pixel_size)
    font.setWeight(weights.get(weight, QFont.Weight.Normal))
    if tracking:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, tracking)
    return font


def mono_font(pixel_size: int = 12) -> QFont:
    available = set(QFontDatabase.families())
    family = next((f for f in FONT_MONO if f in available), FONT_MONO[-1])
    font = QFont(family)
    font.setPixelSize(pixel_size)
    return font


def apply(app: QApplication, assets_dir: Path | str | None = None) -> QApplication:
    """Fusion + palette + font + stylesheet. Call before creating any window."""
    app.setStyle("Fusion")
    load_fonts()
    app.setPalette(_palette())
    family = resolve_family()
    font = QFont(family)
    font.setPixelSize(13)
    app.setFont(font)
    app.setStyleSheet(qss(assets_dir=assets_dir, family=family))
    return app


def set_variant(widget, value, prop: str = "variant") -> None:
    """Set a dynamic property and repaint — required for QSS attribute selectors."""
    widget.setProperty(prop, value)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def tinted_icon(path: Path | str, colour: str = TEXT_SECONDARY, size: int = 16) -> QIcon:
    """Recolour an SVG icon to any token — QtSVG has no currentColor."""
    src = QPixmap(str(path))
    if src.isNull():
        return QIcon()
    src = src.scaled(
        size, size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    out = QPixmap(src.size())
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.drawPixmap(0, 0, src)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(out.rect(), QColor(colour))
    painter.end()
    return QIcon(out)


# The graphics-effect class is imported lazily in apply(), but the shadow helper
# needs it at call time, so it is resolved through the active binding here.
def _shadow_effect_class():
    if BINDING == "PyQt6":
        from PyQt6.QtWidgets import QGraphicsDropShadowEffect
    else:
        from PySide6.QtWidgets import QGraphicsDropShadowEffect
    return QGraphicsDropShadowEffect


def drop_shadow(widget, blur: int = 24, dy: int = 8) -> None:
    """Floating layers only: dialogs, menus, tooltips."""
    effect = _shadow_effect_class()(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, dy)
    effect.setColor(QColor(0, 0, 0, 140))
    widget.setGraphicsEffect(effect)


# --------------------------------------------------------------------------
# chart — hand-painted, matches the house style
# --------------------------------------------------------------------------
class LineChart(QWidget):
    """Blue line with a translucent gradient fill, thin gridlines, hover readout."""

    def __init__(self, values=None, labels=None, parent=None):
        super().__init__(parent)
        self._values = list(values or [1, 2, 3])
        self._labels = list(labels or [])
        self._hover = -1
        self._pad = (46, 10, 14, 26)  # left, right, top, bottom
        self.setMinimumHeight(200)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    def set_values(self, values, labels=None) -> None:
        self._values = list(values)
        if labels is not None:
            self._labels = list(labels)
        self.update()

    def _points(self):
        w, h = self.width(), self.height()
        pl, pr, pt, pb = self._pad
        values = self._values
        lo, hi = min(values), max(values)
        span = (hi - lo) or 1
        step = (w - pl - pr) / max(len(values) - 1, 1)
        pts = [
            QPointF(pl + i * step, pt + (h - pt - pb) * (1 - (v - lo) / span))
            for i, v in enumerate(values)
        ]
        return pts, lo, hi

    def mouseMoveEvent(self, event):
        pts, _, _ = self._points()
        x = event.position().x()
        self._hover = min(range(len(pts)), key=lambda i: abs(pts[i].x() - x)) if pts else -1
        self.update()

    def leaveEvent(self, event):
        self._hover = -1
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        pts, lo, hi = self._points()
        if len(pts) < 2:
            painter.end()
            return
        pl, pr, pt, pb = self._pad
        plot_h = h - pt - pb

        # gridlines
        painter.setPen(QPen(QColor(255, 255, 255, 15), 1))
        for i in range(5):
            y = pt + plot_h * i / 4
            painter.drawLine(int(pl), int(y), int(w - pr), int(y))

        # y labels
        painter.setFont(label_font(10))
        painter.setPen(QColor(TEXT_TERTIARY))
        for i in range(5):
            y = pt + plot_h * i / 4
            value = hi - (hi - lo) * i / 4
            painter.drawText(
                QRectF(0, y - 8, pl - 10, 16),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                f"{value:,.0f}".replace(",", " "),
            )

        baseline = h - pb

        # area
        area = QPainterPath()
        area.moveTo(pts[0].x(), baseline)
        for pt_ in pts:
            area.lineTo(pt_)
        area.lineTo(pts[-1].x(), baseline)
        area.closeSubpath()
        gradient = QLinearGradient(0, pt, 0, baseline)
        gradient.setColorAt(0.0, QColor(47, 75, 255, 97))
        gradient.setColorAt(1.0, QColor(47, 75, 255, 0))
        painter.fillPath(area, gradient)

        # line
        line = QPainterPath()
        line.moveTo(pts[0])
        for pt_ in pts[1:]:
            line.lineTo(pt_)
        pen = QPen(QColor(ACCENT), 2)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawPath(line)

        # x labels — at most 5 ticks
        if self._labels:
            painter.setPen(QColor(TEXT_TERTIARY))
            painter.setFont(label_font(10))
            count = min(len(self._labels), 5)
            idxs = [round(i * (len(self._labels) - 1) / (count - 1)) for i in range(count)] if count > 1 else [0]
            for i in sorted(set(idxs)):
                x = pts[i].x()
                painter.drawText(
                    QRectF(x - 30, baseline + 6, 60, 16),
                    int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
                    str(self._labels[i]),
                )

        # hover
        if 0 <= self._hover < len(pts):
            hover_point = pts[self._hover]
            painter.setPen(QPen(QColor(255, 255, 255, 40), 1))
            painter.drawLine(int(hover_point.x()), int(pt), int(hover_point.x()), int(baseline))
            painter.setPen(QPen(QColor(ACCENT), 2))
            painter.setBrush(QColor("#FFFFFF"))
            painter.drawEllipse(hover_point, 4, 4)

            text = f"{self._values[self._hover]:,.0f}".replace(",", " ")
            painter.setFont(label_font(11, "medium"))
            box_w = painter.fontMetrics().horizontalAdvance(text) + 16
            box_x = min(max(hover_point.x() - box_w / 2, pl), w - pr - box_w)
            box_y = max(hover_point.y() - 30, 0)
            box = QRectF(box_x, box_y, box_w, 22)
            painter.setPen(QPen(QColor(BORDER), 1))
            painter.setBrush(QColor(TOKENS["bg_raised"]))
            painter.drawRoundedRect(box, 4, 4)
            painter.setPen(QColor(TEXT_PRIMARY))
            painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), text)

        painter.end()
