"""Disabled AI look-and-feel.

The visual language is inspired by the bundled Lunar reference UI (dark base,
quiet sidebar, gradient sliders, round checkboxes, pill buttons) but is this
project's own theme, with its own tokens and masthead.

Everything here is PyQt6/PySide6 agnostic through the ``qt`` shim, so the same
package runs on whichever binding is installed.
"""

from __future__ import annotations

import os

from qt import (
    QApplication, QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap,
    Qt, Signal, QTimer, QPropertyAnimation, QEasingCurve, QParallelAnimationGroup,
)

# --- palette -----------------------------------------------------------------
BG = "#0B0D1A"
BG_CHROME = "#0F1224"
BG_PANEL = "#12152A"
BG_RAISED = "#171B33"
BG_INPUT = "#0E1122"
BG_HOVER = "#1A1F3A"
BORDER = "#232842"
BORDER_STRONG = "#2A2F4A"
TEXT = "#FFFFFF"
TEXT_DIM = "#8A90A8"
TEXT_MUTED = "#7A80A0"
TEXT_ACCENT = "#8FA6FF"
ACCENT = "#2F4BFF"
ACCENT_HOVER = "#4159FF"
ACCENT_ACTIVE = "#2440E6"
ACCENT_SOFT = "#171E4C"
ACCENT_LINE = "#22339F"
GOOD = "#3DD68C"
WARN = "#F5A623"
BAD = "#E5484D"

# Lunar-example accent hues used only for the slide fill and checkbox ticks, so
# the gradient reads the same as the reference UI without recolouring the app.
GRAD_FROM = "#3A8DDE"
GRAD_MID = "#4169E1"
GRAD_TO = "#7A6FF0"
CHECK = "#C66FFF"

ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
ICON_DIR = os.path.join(ASSET_DIR, "icons")
FONT_DIR = os.path.join(ASSET_DIR, "fonts")

os.makedirs(ASSET_DIR, exist_ok=True)
os.makedirs(FONT_DIR, exist_ok=True)
_ARROW = os.path.join(ASSET_DIR, "arrow-down.svg").replace("\\", "/")


def _ensure_arrow() -> str:
    """Create the combo-box chevron on disk if it is missing.

    The stylesheet below points QComboBox::down-arrow at this file, so it must
    exist before the sheet is built. It used to be written only on demand, and
    because nothing ever called this helper the SVG was never created: the first
    page with a combo box (the Aim page, via its preset dropdown) made Qt print
    "qt.svg: Cannot open file '...arrow-down.svg'" for every arrow it tried to
    draw. Calling it once at import time -- see below -- fixes that.
    """
    if not os.path.exists(_ARROW):
        try:
            os.makedirs(os.path.dirname(_ARROW), exist_ok=True)
            with open(_ARROW, "w", encoding="utf-8") as handle:
                handle.write(
                    '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" '
                    'viewBox="0 0 24 24" fill="none" stroke="#8A90A8" stroke-width="2.4" '
                    'stroke-linecap="round" stroke-linejoin="round">'
                    '<path d="M6 9l6 6 6-6"/></svg>'
                )
        except OSError:
            pass
    return _ARROW


# Materialise the arrow now, before the stylesheet that references it is built.
_ensure_arrow()


def icon(name: str) -> str:
    return os.path.join(ICON_DIR, name)


# --- widget-scoped stylesheets ----------------------------------------------
SIDEBAR = f"""
QFrame#sidebar {{
    background-color: {BG_CHROME};
    border-right: 1px solid {BORDER};
}}
QFrame#sidebar QLabel {{ background: transparent; }}
"""

SCROLL = "QScrollArea { border: none; background: transparent; }"


STYLE = f"""
QWidget {{
    background: transparent;
    color: {TEXT};
    font-size: 10.5pt;
}}
QWidget#root {{ background: {BG}; }}

QLabel {{ background: transparent; font-weight: 500; }}
QFrame {{ border: none; }}

QFrame[role="card"] {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QFrame[role="group"] {{
    background-color: {BG_RAISED};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QFrame[role="preview"] {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QLabel[role="preview"] {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QFrame[role="metric"] {{
    background-color: {BG_RAISED};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QFrame[role="accent-rule"] {{ background-color: {ACCENT}; border: 0; border-radius: 2px; }}

QLineEdit {{
    border: 1px solid {BORDER_STRONG};
    border-radius: 6px;
    padding: 6px 10px;
    background-color: {BG_INPUT};
    color: {TEXT};
    selection-background-color: {ACCENT};
}}
QLineEdit:focus {{ border: 1px solid {ACCENT}; }}

QPushButton {{
    background-color: {BG_RAISED};
    border: 1px solid {BORDER_STRONG};
    border-radius: 18px;
    padding: 8px 16px;
    font-weight: 600;
    color: {TEXT};
}}
QPushButton:hover {{ background-color: {BG_HOVER}; border-color: {ACCENT_LINE}; }}
QPushButton:pressed {{ background-color: {BG_HOVER}; border-color: {ACCENT}; }}
QPushButton:disabled {{ color: {TEXT_MUTED}; border-color: {BORDER}; }}

QLabel#brand {{ font-size: 12pt; font-weight: 800; color: #ffffff; }}

/* Full-width masthead: the logo banner across the very top of the window. */
QFrame#banner {{
    background-color: {BG_CHROME};
    border-bottom: 1px solid {BORDER};
}}
QLabel#bannerLogo {{ background: transparent; }}
QLabel#bannerTitle {{ font-size: 15pt; font-weight: 800; color: #ffffff; }}
QLabel#bannerSubtitle {{ color: {TEXT_MUTED}; font-size: 9.5pt; }}
/* Live telemetry pinned in the masthead: the figures that used to be on the
   removed Overview page stay visible on every page. */
QFrame[role="headerStat"] {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QLabel#headerStatCaption {{ color: {TEXT_MUTED}; font-size: 8pt; font-weight: 600; }}
QLabel#headerStatValue {{ color: {TEXT}; font-size: 12pt; font-weight: 800; }}
QLabel#navSection {{
    color: #6a6a6a; font-size: 8pt; font-weight: 700;
    letter-spacing: 1px; padding: 2px 12px;
}}
QPushButton#navItem {{
    background: transparent; border: none; border-radius: 8px;
    padding: 9px 12px; text-align: left; color: {TEXT_DIM};
    font-weight: 600; font-size: 10.5pt;
}}
QPushButton#navItem:hover {{ background-color: rgba(255,255,255,0.05); color: {TEXT}; }}
QPushButton#navItem[selected="true"] {{ background-color: rgba(255,255,255,0.09); color: #ffffff; }}
QPushButton#navItem[collapsed="true"] {{ text-align: center; padding: 9px 0; }}
QPushButton#collapseBtn {{
    background-color: rgba(255,255,255,0.04);
    border: 1px solid {BORDER};
    border-radius: 8px; padding: 0;
}}
QPushButton#collapseBtn:hover {{ background-color: rgba(255,255,255,0.09); }}
QFrame#navDivider {{ background-color: {BORDER}; max-height: 1px; min-height: 1px; border: none; }}

QPushButton#primary {{ background-color: {ACCENT}; border-color: {ACCENT}; color: #ffffff; font-weight: 700; }}
QPushButton#primary:hover {{ background-color: {ACCENT_HOVER}; }}
QPushButton#danger {{ background-color: {BG_RAISED}; border-color: {BAD}; color: {BAD}; }}
QPushButton#danger:hover {{ background-color: rgba(229,72,77,0.14); }}
QPushButton#ghost {{ background-color: transparent; border-color: {BORDER_STRONG}; }}
QPushButton#ghost:hover {{ border-color: {ACCENT}; }}

/* Click-to-bind keybind control. Idle it reads as a value you can press; armed
   (waiting for the next key) it glows with the accent so it is obvious the app
   is listening before the key is pressed. */
QPushButton#keybindCapture {{
    background-color: {BG_INPUT}; border: 1px solid {BORDER_STRONG};
    border-radius: 6px; padding: 6px 10px; text-align: left; font-weight: 600;
}}
QPushButton#keybindCapture:hover {{ border-color: {ACCENT_LINE}; }}
QPushButton#keybindCapture[armed="true"] {{
    border: 1px solid {ACCENT}; color: {TEXT_ACCENT}; background-color: {BG_HOVER};
}}

QCheckBox {{ background: transparent; padding: 3px; spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 9px; border: 2px solid #444;
    background-color: transparent;
}}
QCheckBox::indicator:checked {{ background-color: {CHECK}; border: 2px solid {CHECK}; }}
QCheckBox::indicator:hover {{ border-color: {CHECK}; }}

QSlider {{ padding: 4px 0; background: transparent; border: none; }}
QSlider::groove:horizontal {{ background: transparent; border-radius: 4px; height: 6px; margin: 0; }}
QSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {GRAD_FROM}, stop:0.5 {GRAD_MID}, stop:1 {GRAD_TO});
    border-radius: 4px;
}}
QSlider::add-page:horizontal {{ background: #2b2f45; border-radius: 4px; }}
QSlider::handle:horizontal {{
    background-color: #F2F2F2; border: none; width: 14px; height: 14px;
    border-radius: 7px; margin: -4px 0;
}}
QSlider::handle:horizontal:hover {{ background-color: #ffffff; }}

QComboBox {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER_STRONG};
    border-radius: 6px;
    padding: 6px 32px 6px 10px;
    color: {TEXT};
    font-weight: 500;
}}
QComboBox:hover {{ border: 1px solid {ACCENT}; background-color: {BG_RAISED}; }}
QComboBox:focus {{ border: 1px solid {ACCENT}; }}
QComboBox::drop-down {{
    subcontrol-origin: padding; subcontrol-position: top right; width: 28px;
    border-left: 1px solid {BORDER}; background-color: {BG_RAISED};
    border-top-right-radius: 6px; border-bottom-right-radius: 6px;
}}
QComboBox::down-arrow {{ image: url({_ARROW}); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{
    background-color: {BG_PANEL}; border: 1px solid {BORDER};
    border-radius: 6px; padding: 4px; color: {TEXT};
    selection-background-color: {ACCENT}; selection-color: #ffffff; outline: none;
}}
QComboBox QAbstractItemView::item {{ padding: 6px 10px; border-radius: 4px; }}
QComboBox QAbstractItemView::item:hover {{ background-color: {BG_RAISED}; }}

QSpinBox, QDoubleSpinBox {{
    background-color: {BG_INPUT}; border: 1px solid {BORDER_STRONG};
    border-radius: 6px; padding: 4px 8px; color: {TEXT};
}}
QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {ACCENT}; }}

QScrollBar:vertical {{ border: none; background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {GRAD_FROM}, stop:1 {GRAD_TO});
    border-radius: 3px; min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; background: none; border: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QLabel#cardTitle {{ font-weight: bold; font-size: 11pt; }}
QLabel#fieldLabel {{ color: {TEXT}; }}
QLabel#hint {{ color: {TEXT_MUTED}; font-size: 9pt; }}
QLabel#tabHeader {{ font-size: 16pt; font-weight: 800; }}
QLabel#statusRunning {{ color: {GOOD}; font-weight: 700; }}
QLabel#statusStopped {{ color: {TEXT_DIM}; font-weight: 700; }}
QLabel#metricValue {{ font-size: 20pt; font-weight: 800; }}
QLabel#metricUnit {{ color: {TEXT_MUTED}; font-size: 9pt; }}
QPlainTextEdit#console {{
    background: #070910; border: 1px solid {BORDER}; border-radius: 8px;
    font-family: "Cascadia Mono", "Consolas", monospace; font-size: 9.5pt; color: #cfe8ff;
}}
QToolTip {{
    background-color: {BG_RAISED}; color: {TEXT};
    border: 1px solid {BORDER}; border-radius: 6px; padding: 6px 8px; font-size: 9.5pt;
}}
"""


# --- application -------------------------------------------------------------
def load_fonts(directory: str = FONT_DIR) -> list:
    loaded = []
    if not os.path.isdir(directory):
        return loaded
    for name in sorted(os.listdir(directory)):
        if name.lower().endswith((".ttf", ".otf")):
            font_id = QFontDatabase.addApplicationFont(os.path.join(directory, name))
            if font_id != -1:
                loaded.extend(QFontDatabase.applicationFontFamilies(font_id))
    return loaded


def resolve_family() -> str:
    """Pick the UI font, preferring the one we bundle.

    The bundled face is registered first, so its real family name (whatever the
    file calls itself) is used when present. This keeps the look identical on
    every machine instead of depending on Inter/Segoe UI being installed.
    """
    bundled = load_fonts()
    if bundled:
        return bundled[0]
    families = set(QFontDatabase.families())
    for candidate in ("Inter", "Manrope", "Segoe UI", "Noto Sans", "Arial"):
        if candidate in families:
            return candidate
    app = QApplication.instance()
    return app.font().family() if app else "Arial"


def apply(app) -> None:
    app.setStyle("Fusion")
    family = resolve_family()
    font = QFont(family)
    font.setPointSizeF(10.5)
    app.setFont(font)
    app.setStyleSheet(STYLE)


# --- small shared helpers ----------------------------------------------------
def repolish(widget) -> None:
    """Re-evaluate QSS attribute selectors after a dynamic property changes."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def animate(widget, prop: bytes, start, end, ms: int = 180,
            curve=QEasingCurve.Type.InOutCubic, group=None):
    """Start one property animation, optionally joining a parallel group."""
    anim = QPropertyAnimation(widget, prop)
    anim.setDuration(ms)
    anim.setStartValue(start)
    anim.setEndValue(end)
    anim.setEasingCurve(curve)
    if group is not None:
        group.addAnimation(anim)
    else:
        anim.start()
    return anim


def fade_in(widget, ms: int = 140) -> None:
    """Fade a freshly shown page in — used on tab switches."""
    effect_cls = _opacity_class()
    effect = effect_cls(widget)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity")
    anim.setDuration(ms)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _cleanup():
        widget.setGraphicsEffect(None)

    anim.finished.connect(_cleanup)
    anim.start()
    widget._fade_anim = anim


def _opacity_class():
    from qt import QGraphicsOpacityEffect
    return QGraphicsOpacityEffect
