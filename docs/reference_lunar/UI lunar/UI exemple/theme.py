"""Lunar V2 look-and-feel — ported 1:1 from the original Lunar V2 (aim.py /
lib/config/style.py) so this UI matches it visually, just with different
settings.

The original split styling across many small stylesheets that were applied
per-widget. We keep that structure (SIDEBAR, CARD, FLOATING, ...) so the
window code reads like the original, and expose one global STYLE for the
QApplication/root.
"""

import os

# --- asset locations (absolute so QSS url() works from any cwd) --------------
ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib", "assets")
ICON_DIR = os.path.join(ASSET_DIR, "icons")
FONT_PATH = os.path.join(ASSET_DIR, "fonts", "font.ttf")
WINDOW_ICON = os.path.join(ASSET_DIR, "icon.png")
_ARROW = os.path.join(ASSET_DIR, "arrow-down-light.svg").replace("\\", "/")


def icon(name: str) -> str:
    return os.path.join(ICON_DIR, name)


# --- Lunar V2 palette --------------------------------------------------------
BG = "#0d0d0d"            # window base (so the translucent sidebar reads grey)
ACCENT_BLUE = "#4169E1"
ACCENT_BLUE_HI = "#3a8dde"
ACCENT_VIOLET = "#7a6ff0"
ACCENT_PURPLE = "#c66fff"  # checkboxes
ACCENT_SELECT = "#b74aff"  # selected sidebar entry
TEXT = "#eaeaea"
TEXT_DIM = "#b0b0b0"
GOOD = "#3ddc84"
BAD = "#ff5470"


# --- per-widget stylesheets (mirror lib/config/style.py) ---------------------
SIDEBAR = """
QFrame#sidebar {
    background-color: #0b0b0b;
    border-right: 1px solid #1b1b1b;
}
QFrame#sidebar QLabel { background: transparent; }
"""

SIDEBAR_BTN = "QWidget { background: transparent; }"

DISCORD_BTN = "QWidget { background: transparent; border: none; }"

CARD = """
QFrame {
    background: transparent;
    border-radius: 12px;
    padding: 10px;
}
QLabel { background: transparent; }
"""

CARD_TITLE = """
QLabel {
    font-weight: bold;
    font-size: 11pt;
    background: transparent;
}
"""

FLOATING = """
QPushButton {
    border-radius: 26px;
    background-color: #222;
}
QPushButton:hover { background-color: #333; }
"""

SCROLL = """
QScrollArea { border: none; background: transparent; }
"""


# --- global stylesheet (mirror lib/config/style.py "style") ------------------
STYLE = f"""
QWidget {{
    background: transparent;
    color: {TEXT};
    font-size: 10.5pt;
}}

QWidget#root {{
    background: {BG};
}}

QLabel {{
    background: transparent;
    font-weight: 500;
}}

QFrame {{ border: none; }}

QLineEdit {{
    border: 1px solid #2e2e2e;
    border-radius: 6px;
    padding: 6px 10px;
    background-color: #151515;
    color: {TEXT};
    selection-background-color: {ACCENT_BLUE};
}}
QLineEdit:focus {{ border: 1px solid {ACCENT_BLUE}; }}

QPushButton {{
    background-color: #1c1c1c;
    border: 2px solid #2c2c2c;
    border-radius: 18px;
    padding: 8px 16px;
    font-weight: 600;
    color: {TEXT};
}}
QPushButton:hover {{
    background-color: #242424;
    border-color: #3a3a3a;
}}
QPushButton:pressed {{
    background-color: #303030;
    border-color: {ACCENT_BLUE};
}}

/* Website-style sidebar nav items (icon + label) */
QLabel#brand {{
    font-size: 12pt;
    font-weight: 800;
    color: #ffffff;
}}
QLabel#navSection {{
    color: #6a6a6a;
    font-size: 8pt;
    font-weight: 700;
    letter-spacing: 1px;
    padding: 2px 12px;
}}
QPushButton#navItem {{
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 9px 12px;
    text-align: left;
    color: {TEXT_DIM};
    font-weight: 600;
    font-size: 10.5pt;
}}
QPushButton#navItem:hover {{
    background-color: rgba(255, 255, 255, 0.05);
    color: {TEXT};
}}
QPushButton#navItem[selected="true"] {{
    background-color: rgba(255, 255, 255, 0.09);
    color: #ffffff;
}}
QPushButton#navItem[collapsed="true"] {{
    text-align: center;
    padding: 9px 0;
}}
QPushButton#collapseBtn {{
    background-color: rgba(255, 255, 255, 0.04);
    border: 1px solid #1f1f1f;
    border-radius: 8px;
    padding: 0;
}}
QPushButton#collapseBtn:hover {{
    background-color: rgba(255, 255, 255, 0.09);
    border-color: #2c2c2c;
}}
QFrame#navDivider {{
    background-color: #1b1b1b;
    max-height: 1px;
    min-height: 1px;
    border: none;
}}

/* Primary / danger / ghost action buttons */
QPushButton#primary {{
    background-color: {ACCENT_SELECT};
    border: 2px solid {ACCENT_BLUE};
    color: #ffffff;
    font-weight: 700;
}}
QPushButton#primary:hover {{ background-color: #c45cff; }}
QPushButton#danger {{
    background-color: #1c1c1c;
    border: 2px solid {BAD};
    color: {BAD};
}}
QPushButton#danger:hover {{ background-color: rgba(255, 84, 112, 0.12); }}
QPushButton#ghost {{
    background-color: #1c1c1c;
    border: 2px solid #2c2c2c;
}}
QPushButton#ghost:hover {{ border-color: {ACCENT_BLUE}; }}

QCheckBox {{
    background: transparent;
    padding: 3px;
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 10px;
    border: 2px solid #444;
}}
QCheckBox::indicator:checked {{
    background-color: {ACCENT_PURPLE};
    border: 2px solid {ACCENT_PURPLE};
}}

QSlider {{
    padding: 4px 0;
    background: transparent;
    border: none;
}}
QSlider::groove:horizontal {{
    background: transparent;
    border-radius: 4px;
    padding: 1px;
    height: 6px;
    margin: 0px;
}}
QSlider::sub-page:horizontal {{
    background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0,
                stop: 0 {ACCENT_BLUE_HI},
                stop: 0.5 {ACCENT_BLUE},
                stop: 1 {ACCENT_VIOLET});
    border-radius: 4px;
}}
QSlider::add-page:horizontal {{
    background: #333333;
    border-radius: 4px;
}}
QSlider::handle:horizontal {{
    background-color: #F2F2F2;
    border: none;
    width: 14px;
    height: 14px;
    border-radius: 7px;
    margin: -4px 0;
}}
QSlider::handle:horizontal:hover {{ background-color: #F2F2F2; }}

NoScrollComboBox, QComboBox {{
    background-color: #151515;
    border: 1px solid #2e2e2e;
    border-radius: 6px;
    padding: 6px 32px 6px 10px;
    color: {TEXT};
    font-weight: 500;
}}
NoScrollComboBox:hover, QComboBox:hover {{
    border: 1px solid {ACCENT_BLUE};
    background-color: #1b1b1b;
}}
NoScrollComboBox:focus, QComboBox:focus {{
    border: 1px solid {ACCENT_VIOLET};
    background-color: #1c1c1c;
}}
NoScrollComboBox::drop-down, QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 28px;
    border-left: 1px solid #2e2e2e;
    background-color: #1c1c1c;
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
}}
NoScrollComboBox::down-arrow, QComboBox::down-arrow {{
    image: url({_ARROW});
    width: 12px;
    height: 12px;
}}
NoScrollComboBox QAbstractItemView, QComboBox QAbstractItemView {{
    background-color: #202020;
    border: 1px solid #2e2e2e;
    border-radius: 6px;
    padding: 4px;
    color: {TEXT};
    selection-background-color: {ACCENT_VIOLET};
    selection-color: #ffffff;
    outline: none;
}}
NoScrollComboBox QAbstractItemView::item, QComboBox QAbstractItemView::item {{
    padding: 6px 10px;
    border-radius: 4px;
}}
NoScrollComboBox QAbstractItemView::item:hover, QComboBox QAbstractItemView::item:hover {{
    background-color: #2a2a2a;
}}

QSpinBox, QDoubleSpinBox {{
    background-color: #151515;
    border: 1px solid #2e2e2e;
    border-radius: 6px;
    padding: 4px 8px;
    color: {TEXT};
}}
QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {ACCENT_BLUE}; }}

QScrollBar:vertical {{
    border: none;
    background: #151515;
    width: 10px;
}}
QScrollBar::handle:vertical {{
    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                stop: 0 {ACCENT_BLUE_HI},
                stop: 0.5 {ACCENT_BLUE},
                stop: 1 {ACCENT_BLUE});
    border-radius: 3px;
    min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px; background: none; border: none;
}}

/* Section title (card header) */
QLabel#cardTitle {{ font-weight: bold; font-size: 11pt; }}
QLabel#fieldLabel {{ color: {TEXT}; }}
QLabel#hint {{ color: {TEXT_DIM}; font-size: 9pt; }}

/* Status + console */
QLabel#statusRunning {{ color: {GOOD}; font-weight: 700; }}
QLabel#statusStopped {{ color: {TEXT_DIM}; font-weight: 700; }}
QPlainTextEdit#console {{
    background: #0a0a0a;
    border: 1px solid #2e2e2e;
    border-radius: 8px;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 10pt;
    color: #cfe8ff;
}}
"""
