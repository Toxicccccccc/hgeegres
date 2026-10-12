"""Compact aim-settings overlay for DisabledAssistance.

A small, focused window holding only the aim controls a player adjusts
*mid-game*: movement shaping, flick, prediction and the action trigger. It is
deliberately not a second copy of the control center -- the advanced pages stay
in the main window.

Design constraints, all of which matter for usability in-game:

  * It is a real top-level window (``Qt.Tool``), so it can never be laid out
    inside the main window's content area.
  * It is frameless, compact (248px) and draggable by its header; it never
    resizes the main window and never appears in the taskbar.
  * It hides when it loses focus, so it cannot sit over a game stealing clicks.
  * The open/close shortcut is user-recordable and refused if it is invalid or
    already used by the app.
  * Closing it only hides it. The engine is never affected.
  * Every control it exposes **already exists on the main window**, and it reads
    and writes through that shared widget, so the two can never disagree.

Every colour, radius and size comes from ``theme``/``theme_tokens``; nothing is
hard-coded here.
"""

import theme
from theme_tokens import SP, UI_SIZES

if theme.BINDING == "PyQt6":
    from PyQt6.QtCore import Qt, QEvent, QPoint, QPropertyAnimation, QEasingCurve, pyqtSignal
    from PyQt6.QtGui import QKeySequence, QShortcut
    from PyQt6.QtWidgets import (
        QCheckBox,
        QFrame,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QSlider,
        QVBoxLayout,
        QWidget,
    )
else:
    from PySide6.QtCore import Qt, QEvent, QPoint, QPropertyAnimation, QEasingCurve, Signal as pyqtSignal
    from PySide6.QtGui import QKeySequence, QShortcut
    from PySide6.QtWidgets import (
        QCheckBox,
        QFrame,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QSlider,
        QVBoxLayout,
        QWidget,
    )


# Shortcuts the main window already owns; the quick menu must not take one.
RESERVED_SHORTCUTS = (
    "Ctrl+S", "Ctrl+R", "Ctrl+F", "Ctrl+Q", "Escape",
    "F1", "F2", "F3", "F4", "F5", "F6",
)

# The controls the quick menu mirrors, in display order. Each entry is
# (key, mode) where mode is "check" or "slider"; sliders carry (low, high, suffix).
QUICK_CONTROLS = (
    ("movement_smoothing_enabled", "check"),
    ("movement_max_step_px", "slider", 1, 400, " px"),
    ("movement_acceleration", "slider", 1, 100, "%"),
    ("movement_stop_tolerance_px", "slider", 0, 32, " px"),
    ("flick_enabled", "check"),
    ("flick_max_distance_px", "slider", 0, 600, " px"),
    ("flick_speed", "slider", 1, 100, "%"),
    ("prediction_enabled", "check"),
    ("prediction_horizon_ms", "slider", 0, 300, " ms"),
    ("shot_delay_ms", "slider", 0, 1000, " ms"),
)


def normalise_shortcut(text):
    """Return a canonical chord string, or None when it cannot be used.

    Rejects empty input, bare modifiers, and any chord already reserved by the
    main window, so re-recording can never silently shadow an existing action.
    """
    text = (text or "").strip()
    if not text:
        return None
    sequence = QKeySequence(text)
    if sequence.isEmpty():
        return None
    portable = sequence.toString(QKeySequence.SequenceFormat.PortableText)
    if not portable:
        return None
    if portable in RESERVED_SHORTCUTS:
        return None
    parts = portable.split("+")
    if len(parts) == 1 and parts[0] in ("Ctrl", "Alt", "Shift", "Meta"):
        return None
    return portable


class QuickMenu(QWidget):
    """A compact aim-settings panel, opened with a user-chosen shortcut."""

    closed = pyqtSignal()
    settings_changed = pyqtSignal()

    _HEADER_HEIGHT = 34

    def __init__(self, parent_window):
        # Qt.Tool keeps it out of the taskbar; it is still a top-level window so
        # it is never laid out inside the main window's content area.
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("QuickMenu")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setWindowTitle("DisabledAssistance aim settings")

        self.parent_window = parent_window
        self._shortcut = None
        self._drag_offset = None
        self._fade = None

        self._build()
        self.apply_shortcut(parent_window.controls["quick_menu_key"].text())

    # -- construction ------------------------------------------------------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())
        root.addWidget(self._build_body(), 1)
        self.setFixedWidth(UI_SIZES["quick_menu_width"])

    def _build_header(self):
        """Draggable header: title, status dot, close button."""
        bar = QFrame()
        theme.set_variant(bar, "quickmenu-header")
        bar.setFixedHeight(self._HEADER_HEIGHT)
        row = QHBoxLayout(bar)
        row.setContentsMargins(SP["3"], 0, SP["1"], 0)
        row.setSpacing(SP["2"])

        title = QLabel("AIM SETTINGS")
        title.setFont(theme.label_font(11, "bold", 0.8))
        title.setProperty("role", "label")
        row.addWidget(title)

        self.status_dot = QLabel("")
        theme.set_variant(self.status_dot, "dot")
        row.addWidget(self.status_dot)
        self.status_text = QLabel("Stopped")
        self.status_text.setProperty("role", "meta")
        row.addWidget(self.status_text)

        row.addStretch(1)

        close = QPushButton("\u2715")
        theme.set_variant(close, "icon")
        close.setAccessibleName("Close aim settings")
        close.setToolTip("Close (Esc)")
        close.clicked.connect(self.hide)
        row.addWidget(close)

        bar.mousePressEvent = self._header_press
        bar.mouseMoveEvent = self._header_move
        return bar

    def _build_body(self):
        body = QFrame()
        theme.set_variant(body, "quickmenu-body")
        column = QVBoxLayout(body)
        column.setContentsMargins(SP["3"], SP["3"], SP["3"], SP["3"])
        column.setSpacing(SP["2"])

        self.controls = {}
        for entry in QUICK_CONTROLS:
            key, mode = entry[0], entry[1]
            if key not in self.parent_window.controls:
                continue
            if mode == "check":
                widget = self._check(key, self._title_for(key))
                column.addWidget(widget)
            else:
                _, _, low, high, suffix = entry
                column.addLayout(self._slider(key, self._title_for(key), low, high, suffix))

        column.addWidget(self._divider())

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(SP["2"])
        self.start_button = QPushButton("Start")
        theme.set_variant(self.start_button, "primary")
        self.start_button.clicked.connect(self._start)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self._stop)
        buttons.addWidget(self.start_button, 1)
        buttons.addWidget(self.stop_button, 1)
        column.addLayout(buttons)

        self.hint = QLabel("")
        self.hint.setProperty("role", "help")
        self.hint.setWordWrap(True)
        column.addWidget(self.hint)

        column.addStretch(1)
        return body

    # -- small builders ----------------------------------------------------
    @staticmethod
    def _title_for(key):
        """A short, human label derived from the setting key."""
        return {
            "movement_smoothing_enabled": "Smooth, settled movement",
            "movement_max_step_px": "Max step",
            "movement_acceleration": "Acceleration",
            "movement_stop_tolerance_px": "Stop tolerance",
            "flick_enabled": "Enable flick correction",
            "flick_max_distance_px": "Flick distance",
            "flick_speed": "Flick speed",
            "prediction_enabled": "Enable prediction",
            "prediction_horizon_ms": "Look-ahead",
            "shot_delay_ms": "Action delay",
        }.get(key, key.replace("_", " ").capitalize())

    def _divider(self):
        line = QFrame()
        theme.set_variant(line, "divider")
        line.setFixedHeight(1)
        return line

    def _check(self, key, text):
        control = QCheckBox(text)
        control.setChecked(bool(self.parent_window.controls[key].isChecked()))
        control.toggled.connect(lambda value, k=key: self._push(k, value))
        self.controls[key] = control
        return control

    def _slider(self, key, title, low, high, suffix):
        """Label + value on one line, slim slider below -- compact but readable."""
        box = QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(SP["1"])

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        caption = QLabel(title)
        caption.setProperty("role", "qm-title")
        top.addWidget(caption, 1)
        value = QLabel("")
        value.setFont(theme.mono_font(11))
        value.setProperty("role", "qm-value")
        top.addWidget(value)
        box.addLayout(top)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(low, high)
        source = self.parent_window.controls[key]
        slider.setValue(int(source.value()))
        caption.setBuddy(slider)
        slider.valueChanged.connect(lambda v, k=key: self._push(k, v))
        slider.valueChanged.connect(lambda v, lbl=value, s=suffix: lbl.setText(f"{v}{s}"))
        value.setText(f"{int(source.value())}{suffix}")
        box.addWidget(slider)

        self.controls[key] = slider
        return box

    # -- shortcut ----------------------------------------------------------
    def apply_shortcut(self, shortcut_text):
        """(Re)register the open/close chord. Returns True when it was accepted."""
        if self._shortcut is not None:
            self._shortcut.setEnabled(False)
            self._shortcut.deleteLater()
            self._shortcut = None

        normalised = normalise_shortcut(shortcut_text)
        if normalised is None:
            self.hint.setText("Shortcut unavailable - open the menu from the app instead.")
            return False

        self._shortcut = QShortcut(QKeySequence(normalised), self.parent_window)
        self._shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._shortcut.activated.connect(self.toggle)
        self.hint.setText(f"Press {normalised} to open or close")
        return True

    def toggle(self):
        if self.isVisible():
            self.hide()
        else:
            self.refresh()
            self._place_near_parent()
            self.show()
            self.raise_()
            self._fade_in()

    def _place_near_parent(self):
        """Open beside the main window, never on top of its content."""
        parent = self.parent_window
        anchor = parent.geometry()
        self.adjustSize()
        x = anchor.right() + SP["2"]
        y = anchor.top() + SP["6"]
        screen = parent.screen()
        if screen is not None:
            available = screen.availableGeometry()
            if x + self.width() > available.right():
                x = anchor.left() - self.width() - SP["2"]
            x = max(available.left(), x)
            y = min(y, available.bottom() - self.height() - SP["2"])
        self.move(QPoint(x, y))

    def _fade_in(self):
        """Short opacity fade, for a less abrupt appearance."""
        # Drop any fade still in flight so a rapid hide/show cannot leak an
        # animation that keeps running against the hidden window.
        if self._fade is not None:
            self._fade.stop()
            self._fade.deleteLater()
            self._fade = None
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(UI_SIZES["page_fade_ms"])
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.start()

    # -- header drag -------------------------------------------------------
    def _header_press(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def _header_move(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    # -- state -------------------------------------------------------------
    def refresh(self):
        """Pull current values from the main window so the two never disagree."""
        controls = self.parent_window.controls
        for key, widget in self.controls.items():
            if key not in controls:
                continue
            widget.blockSignals(True)
            if isinstance(widget, QCheckBox):
                widget.setChecked(bool(controls[key].isChecked()))
            else:
                widget.setValue(int(controls[key].value()))
            widget.blockSignals(False)
        running = self.parent_window.running
        self.status_text.setText("Running" if running else "Stopped")
        theme.set_variant(self.status_dot, "dot-ok" if running else "dot")
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)

    def _push(self, key, value):
        """Write a value back to the main window control and persist it."""
        control = self.parent_window.controls.get(key)
        if control is None:
            return
        control.blockSignals(True)
        if isinstance(control, QCheckBox):
            control.setChecked(bool(value))
        elif isinstance(control, QSlider):
            control.setValue(int(value))
        control.blockSignals(False)
        self.settings_changed.emit()

    # -- slots -------------------------------------------------------------
    def _start(self):
        self.parent_window.start()
        self.refresh()

    def _stop(self):
        self.parent_window.stop()
        self.refresh()

    # -- window behaviour --------------------------------------------------
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)

    def changeEvent(self, event):
        # Hide when focus is lost so the panel cannot sit over another window.
        if event.type() == QEvent.Type.ActivationChange and not self.isActiveWindow():
            if self.isVisible():
                self.hide()
        super().changeEvent(event)

    def closeEvent(self, event):
        # Hiding only. Closing this panel must never stop an active session.
        event.ignore()
        self.hide()
        self.closed.emit()
