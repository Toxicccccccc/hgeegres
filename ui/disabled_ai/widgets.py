"""Form controls for the Lunar V3 UI, with the animations the reference UI uses.

Each control is driven by a schema field dict (see ``config_schema.py``), so the
pages stay declarative. Animations are deliberately short (120-200 ms) and
eased, never bouncy, so they read as polish rather than decoration.
"""

from __future__ import annotations

from qt import (
    Qt, Signal, Property, QObject, QEvent, QTimer, QPointF, QRectF,
    QEasingCurve, QPropertyAnimation, QParallelAnimationGroup,
    QApplication, QWidget, QLabel, QHBoxLayout, QVBoxLayout, QSlider,
    QSpinBox, QDoubleSpinBox, QCheckBox, QComboBox, QLineEdit, QFrame,
    QPainter, QColor, QFont, QPixmap, QFileDialog, QColorDialog, QPushButton,
)

import theme
from config_schema import list_models, keybind_display_name

from pathlib import Path


class _ScrollPassthrough(QObject):
    """Let the page scroll instead of the widget changing on a wheel event."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Wheel:
            parent = obj.parent()
            if parent is not None:
                QApplication.sendEvent(parent, event)
            return True
        return False


class NoScrollSlider(QSlider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._passthrough = _ScrollPassthrough(self)
        self.installEventFilter(self._passthrough)


class NoScrollComboBox(QComboBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._passthrough = _ScrollPassthrough(self)
        self.installEventFilter(self._passthrough)


class ValueChip(QLabel):
    """The small right-aligned readout that animates when its value changes."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setObjectName("valueChip")
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setMinimumWidth(56)
        self.setStyleSheet(
            f"QLabel#valueChip {{ color: {theme.TEXT_ACCENT}; font-weight: 700; }}"
        )

    def set_text_pulse(self, text: str) -> None:
        if self.text() == text:
            return
        self.setText(text)
        # Quick opacity pulse so a change is noticed without being loud.
        effect = _opacity_effect(self)
        self.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity")
        anim.setDuration(180)
        anim.setStartValue(0.45)
        anim.setKeyValueAt(0.5, 1.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _done():
            self.setGraphicsEffect(None)

        anim.finished.connect(_done)
        anim.start()
        self._anim = anim


def _opacity_effect(widget):
    from qt import QGraphicsOpacityEffect
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(1.0)
    return effect


# Windows virtual-key codes for the mouse buttons. Qt only delivers the left,
# right and middle buttons as mouse events (and only as press/release, which a
# click-to-capture control would swallow); every button, including the side
# buttons, is readable as a VK through GetAsyncKeyState. Polling these while the
# control is armed is what lets a click on "X1" record the real 0x05 instead of
# falling through to a menu pick.
MOUSE_CAPTURE_KEYS = (
    (0x01, "Left Mouse"),
    (0x02, "Right Mouse"),
    (0x04, "Middle Mouse"),
    (0x05, "Mouse 4 (X1)"),
    (0x06, "Mouse 5 (X2)"),
)

# Qt reports its special keys as 0x01000000 + n, which is NOT the Windows
# virtual-key code the engine polls. Letters, digits and the top-row keys line up
# (Qt reuses the ASCII code), but F-keys, arrows, Enter and the rest do not, so
# they need this translation. Capturing a key the engine cannot read is worse
# than not capturing it at all, so anything unmapped is ignored rather than
# stored as a bogus code.
QT_KEY_TO_VK = {
    0x01000000: 0x1B,  # Escape
    0x01000001: 0x09,  # Tab
    0x01000004: 0x0D,  # Enter / Return
    0x01000005: 0x0D,  # Return (numeric keypad)
    0x01000003: 0x08,  # Backspace
    0x01000006: 0x2D,  # Insert
    0x01000007: 0x2E,  # Delete
    0x01000013: 0x26,  # Up
    0x01000015: 0x28,  # Down
    0x01000012: 0x25,  # Left
    0x01000014: 0x27,  # Right
    0x01000010: 0x24,  # Home
    0x01000011: 0x23,  # End
    0x01000016: 0x21,  # Page Up
    0x01000017: 0x22,  # Page Down
    0x01000030: 0x70,  # F1
    0x01000031: 0x71,  # F2
    0x01000032: 0x72,  # F3
    0x01000033: 0x73,  # F4
    0x01000034: 0x74,  # F5
    0x01000035: 0x75,  # F6
    0x01000036: 0x76,  # F7
    0x01000037: 0x77,  # F8
    0x01000038: 0x78,  # F9
    0x01000039: 0x79,  # F10
    0x0100003A: 0x7A,  # F11
    0x0100003B: 0x7B,  # F12
    0x0100003C: 0x7C,  # F13
    0x0100003D: 0x7D,  # F14
    0x0100003E: 0x7E,  # F15
    0x0100003F: 0x7F,  # F16
    0x01000040: 0x80,  # F17
    0x01000041: 0x81,  # F18
    0x01000042: 0x82,  # F19
    0x01000043: 0x83,  # F20
    0x01000044: 0x84,  # F21
    0x01000045: 0x85,  # F22
    0x01000046: 0x86,  # F23
    0x01000047: 0x87,  # F24
    0x01000021: 0x11,  # Ctrl (generic modifier; use the left VK)
    0x01000020: 0x10,  # Shift
    0x01000023: 0x12,  # Alt
    0x01000024: 0x14,  # Caps Lock
    0x01000055: 0x5D,  # Menu / application key
    0x01000022: 0x5B,  # Windows / Meta
}


def qt_key_to_vk(key: int) -> int | None:
    """Translate a Qt key code into a Windows virtual-key code, or None.

    Qt's letters/digits already equal their VK, so they are returned unchanged;
    special keys go through ``QT_KEY_TO_VK``. Anything unrecognised returns
    None so the caller can keep listening instead of binding a code the engine
    would never match.
    """
    value = int(key)
    if value in QT_KEY_TO_VK:
        return QT_KEY_TO_VK[value]
    if 0x20 <= value <= 0x7E:  # letters, digits, punctuation, space
        return value
    return None


class KeybindCapture(QPushButton):
    """A click-to-bind control: press it, then press the key you want.

    Replaces the old keybind dropdown. Clicking the button arms it; the next key
    or mouse button that goes down is read straight from the operating system
    (its real Windows virtual-key code, so left mouse is exactly 0x01) and shown
    as ``Name (0xNN)``. This is what the engine already speaks, so what the user
    pressed is exactly what the engine polls -- no name table in between that
    could disagree.

    Mouse side buttons (X1/X2) are not delivered as ordinary Qt events, so while
    armed the control polls ``GetAsyncKeyState`` for every button; keyboard keys
    are caught from ``keyPressEvent``. Escape cancels the capture.
    """

    captured = Signal(int)

    def __init__(self, value: int = 0x12, parent=None):
        super().__init__(parent)
        self._value = int(value) if isinstance(value, int) else 0x12
        self._armed = False
        # The click that arms the control is still "down" on the first poll
        # tick; wait for it to be released before accepting any button, so
        # clicking to start does not immediately capture itself.
        self._primed = False
        self._seen_buttons = set()
        self.setObjectName("keybindCapture")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(32)
        self.clicked.connect(self._arm)
        self._poll = QTimer(self)
        self._poll.setInterval(30)
        self._poll.timeout.connect(self._poll_mouse)
        self._refresh_text()

    # ---- value io -----------------------------------------------------------
    def value(self) -> int:
        return int(self._value)

    def set_value(self, val) -> None:
        try:
            self._value = int(val)
        except (TypeError, ValueError):
            self._value = 0x12
        self._refresh_text()

    def _refresh_text(self) -> None:
        if self._armed:
            self.setText("Press a key or mouse button…")
            self.setProperty("armed", True)
            self.setToolTip("Press the key or mouse button to bind. Escape cancels.")
        else:
            name = keybind_display_name(self._value)
            self.setText(f"{name}    (0x{self._value:02X})")
            self.setProperty("armed", False)
            self.setToolTip(
                f"Bound to {name} (0x{self._value:02X}). Click, then press the key "
                "you want to use."
            )
        theme.repolish(self)

    # ---- capture ------------------------------------------------------------
    def _arm(self) -> None:
        if self._armed:
            return
        self._armed = True
        self._primed = False
        self._seen_buttons = set()
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self.grabKeyboard()
        self._poll.start()
        self._refresh_text()

    def _disarm(self) -> None:
        self._armed = False
        self._poll.stop()
        self.releaseKeyboard()
        self._refresh_text()

    def _commit(self, code: int) -> None:
        self._value = int(code)
        self._disarm()
        self.captured.emit(self._value)

    def _poll_mouse(self) -> None:
        import ctypes
        get_state = ctypes.windll.user32.GetAsyncKeyState
        get_state.argtypes = (ctypes.c_int,)
        get_state.restype = ctypes.c_short
        if not self._primed:
            # Wait for every button to be up once, so the arming click's own
            # press/release is not mistaken for the binding.
            if all(not (get_state(vk) & 0x8000) for vk, _name in MOUSE_CAPTURE_KEYS):
                self._primed = True
            return
        for vk, _name in MOUSE_CAPTURE_KEYS:
            if get_state(vk) & 0x8000 and vk not in self._seen_buttons:
                self._commit(vk)
                return

    def keyPressEvent(self, event) -> None:
        if not self._armed:
            super().keyPressEvent(event)
            return
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._disarm()
            return
        # Qt reuses the Windows VK for letters and digits but not for special
        # keys (F-keys, arrows, Enter…), so translate rather than store the raw
        # Qt code. None means the key has no VK and must be ignored.
        vk = qt_key_to_vk(key)
        if vk is not None:
            self._commit(vk)

    def focusOutEvent(self, event) -> None:
        # Losing focus (alt-tab, clicking elsewhere) must not leave the control
        # stuck in "press a key" with the keyboard grabbed.
        if self._armed:
            self._disarm()
        super().focusOutEvent(event)

    def hideEvent(self, event) -> None:
        if self._armed:
            self._disarm()
        super().hideEvent(event)


class FieldRow(QWidget):
    """One schema-driven control. Emits ``changed`` whenever the value moves."""

    changed = Signal()

    def __init__(self, field: dict, parent=None):
        super().__init__(parent)
        self.field = field
        self.key = field["key"]
        self.type = field["type"]
        self._label_text = field["label"]
        self._build()
        tip = field.get("tooltip")
        if tip:
            self.setToolTip(tip)

    # ---- construction -------------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 6, 0, 6)
        root.setSpacing(4)

        if self.type in ("float", "int"):
            self._build_numeric(root)
        elif self.type == "inttext":
            self._build_inttext(root)
        elif self.type == "bool":
            self._build_bool(root)
        elif self.type == "choice":
            self._build_choice(root)
        elif self.type == "keybind":
            self._build_keybind(root)
        elif self.type == "model":
            self._build_model(root)
        elif self.type == "color":
            self._build_color(root)
        elif self.type == "resolution":
            self._build_resolution(root)
        else:
            self._build_string(root)

        # A plain-language description line under every control, so even someone
        # who has never used the app knows what the setting does and when to
        # change it. This is intentionally always visible, not a hover tooltip.
        self._add_description(root)

    def _add_description(self, root) -> None:
        goal = self.field.get("goal")
        if not goal:
            return
        description = QLabel(goal)
        description.setObjectName("hint")
        description.setWordWrap(True)
        description.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 9pt;")
        root.addWidget(description)
        self._description = description

    def _build_numeric(self, root) -> None:
        is_float = self.type == "float"
        self._min = float(self.field.get("min", 0))
        self._max = float(self.field.get("max", 100))
        self._step = float(self.field.get("step", 1)) if is_float else 1.0
        self._decimals = int(self.field.get("decimals", 0))
        self._steps = max(1, int(round((self._max - self._min) / self._step)))

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel(self._label_text)
        self.label.setObjectName("fieldLabel")
        head.addWidget(self.label)
        head.addStretch(1)
        self.chip = ValueChip()
        head.addWidget(self.chip)
        goal = self.field.get("goal")
        if goal:
            self.chip.setToolTip(goal)
        root.addLayout(head)

        self.slider = NoScrollSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, self._steps)
        self.slider.valueChanged.connect(self._on_slider)
        root.addWidget(self.slider)

        self._value = self._min
        self._refresh_label()

    def _on_slider(self, sval: int) -> None:
        # Smoothly animate the numeric chip to the new value.
        target = self._min + sval * self._step

        def _sync(v):
            self._value = int(round(v)) if self.type == "int" else v
            self._refresh_label()

        start = self._value
        anim = QPropertyAnimation(self, b"animatedValue")
        anim.setDuration(120)
        anim.setStartValue(float(start))
        anim.setEndValue(float(target))
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(lambda v: _sync(v))
        anim.start()
        self._anim = anim
        self.changed.emit()

    # ``animatedValue`` must be a *Qt* property (a meta-object property), not a
    # plain Python ``property``: QPropertyAnimation resolves the name through
    # Qt's meta-object system, so a Python-only property made every slider emit
    # "QPropertyAnimation: you're trying to animate a non-existing property
    # animatedValue of your QObject" and the value chip never animated.
    def _get_animated_value(self):
        return float(getattr(self, "_anim_value", self._value))

    def _set_animated_value(self, v):
        self._anim_value = v
        self._value = int(round(v)) if self.type == "int" else v
        self._refresh_label()

    animatedValue = Property(float, _get_animated_value, _set_animated_value)

    def _display(self) -> str:
        if self.type == "int":
            return f"{int(round(self._value))}"
        return f"{self._value:.{self._decimals}f}"

    def _refresh_label(self) -> None:
        text = self._display()
        if getattr(self, "chip", None) is not None:
            self.chip.set_text_pulse(text)

    def _build_bool(self, root) -> None:
        self.check = QCheckBox(self._label_text)
        self.check.stateChanged.connect(lambda *_: self.changed.emit())
        root.addWidget(self.check)

    def _build_choice(self, root) -> None:
        root.addWidget(self._head())
        self.combo = NoScrollComboBox()
        self.combo.addItems(self.field.get("choices", []))
        self.combo.currentIndexChanged.connect(lambda *_: self.changed.emit())
        root.addWidget(self.combo)

    def _build_model(self, root) -> None:
        """Dropdown of the weights found in models/, plus a custom-path escape hatch.

        The list is read from the models/ folder EACH time the control is filled,
        never from a list baked into the schema. A weight copied into models/ is
        therefore offered without touching code or restarting, which a frozen
        import-time list could not do. A Refresh button re-scans on demand, so a
        model added while the app is open still appears.
        """
        root.addWidget(self._head())
        self._custom_label = "Custom path…"
        # _model_path must exist before the list is filled, because populating
        # calls _refresh_model_hint(), which reads it.
        self._model_path = ""
        self.combo = NoScrollComboBox()
        self.combo.currentIndexChanged.connect(self._on_model_index)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.combo, 1)
        refresh = QPushButton("Refresh")
        refresh.setObjectName("ghost")
        refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh.setToolTip("Re-scan the models/ folder for new weights")
        refresh.clicked.connect(self._refresh_models)
        row.addWidget(refresh)
        browse = QPushButton("Browse…")
        browse.setObjectName("ghost")
        browse.setCursor(Qt.CursorShape.PointingHandCursor)
        browse.clicked.connect(self._browse_model)
        row.addWidget(browse)
        host = QWidget()
        host.setLayout(row)
        root.addWidget(host)

        # A read-only line under the dropdown shows the full path of the selected
        # model, so a custom file elsewhere on disk is always visible.
        self.model_hint = QLabel("")
        self.model_hint.setObjectName("hint")
        self.model_hint.setWordWrap(True)
        root.addWidget(self.model_hint)
        # Fill the dropdown only now that every widget it touches exists.
        self._populate_models()

    def _populate_models(self) -> None:
        """Fill the dropdown from the models/ folder on disk, preserving choice.

        ``list_models()`` scans the folder live, so this is the single source of
        truth for what is selectable; nothing is hard-coded. The previously
        selected path is restored when it still exists, otherwise the control
        keeps whatever data it had so _load_into_ui can set it afterwards.
        """
        previous = self.combo.currentData() if self.combo.count() else None
        self.combo.blockSignals(True)
        self.combo.clear()
        # Show just the file name; keep the full path as the item's data so a
        # long 'C:\\Users\\...' prefix does not swamp the control. Duplicate
        # names still resolve to distinct paths because the data differs.
        for path in list_models():
            self.combo.addItem(Path(path).name, path)
        self.combo.addItem(self._custom_label, "")
        if previous:
            index = self.combo.findData(previous)
            if index >= 0:
                self.combo.setCurrentIndex(index)
        self.combo.blockSignals(False)
        self._refresh_model_hint()

    def _refresh_models(self) -> None:
        self._populate_models()
        self.changed.emit()

    def _on_model_index(self, _index: int) -> None:
        # The "Custom path…" entry carries no data and must not clear the current
        # selection: the user still has to pick a file through Browse.
        data = self.combo.currentData()
        if not data:
            return
        self._model_path = str(data)
        self._refresh_model_hint()
        self.changed.emit()

    def _browse_model(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select a model", "",
            "Models (*.engine *.onnx *.pt);;All files (*.*)")
        if not path:
            return
        self.set_value(path)
        self.changed.emit()

    def _refresh_model_hint(self) -> None:
        import os
        path = getattr(self, "_model_path", "")
        if path and os.path.isfile(path):
            self.model_hint.setText(os.path.basename(path))
            self.model_hint.setToolTip(path)
        else:
            self.model_hint.setText(path or "No model selected")
            self.model_hint.setToolTip(path)

    def _build_color(self, root) -> None:
        """A clickable swatch that opens the native colour picker."""
        root.addWidget(self._head())
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.swatch = QPushButton()
        self.swatch.setObjectName("colorSwatch")
        self.swatch.setCursor(Qt.CursorShape.PointingHandCursor)
        self.swatch.setFixedSize(72, 30)
        self.swatch.clicked.connect(self._pick_color)
        row.addWidget(self.swatch)
        self.color_hex = QLabel("")
        self.color_hex.setObjectName("hint")
        row.addWidget(self.color_hex)
        row.addStretch(1)
        host = QWidget()
        host.setLayout(row)
        root.addWidget(host)
        self._color = self.field.get("default", "#2F4BFF")
        self._apply_swatch()

    def _pick_color(self) -> None:
        chosen = QColorDialog.getColor(QColor(self._color), self, "FOV colour")
        if not chosen.isValid():
            return
        self._color = chosen.name()
        self._apply_swatch()
        self.changed.emit()

    def _apply_swatch(self) -> None:
        colour = QColor(self._color)
        if not colour.isValid():
            colour = QColor("#2F4BFF")
        self._color = colour.name()
        text_colour = "#0B0D1A" if colour.lightness() > 140 else "#FFFFFF"
        self.swatch.setStyleSheet(
            f"QPushButton#colorSwatch {{ background-color: {self._color}; "
            f"border: 1px solid {theme.BORDER_STRONG}; border-radius: 6px; "
            f"color: {text_colour}; }}"
        )
        self.color_hex.setText(self._color.upper())

    def _build_resolution(self, root) -> None:
        """A preset resolution dropdown with a Custom… escape hatch.

        The field covers two config keys (width and height). Its value is a
        ``(width, height)`` tuple; ``set_value`` accepts that tuple or a
        ``"2560x1440"`` string so a profile written by an older build still
        loads. Choosing Custom reveals two spinboxes for an arbitrary size.
        """
        root.addWidget(self._head())
        self._presets = list(self.field.get("presets", []))
        self._custom_label = "Custom resolution…"

        self.combo = NoScrollComboBox()
        for width, height in self._presets:
            self.combo.addItem(f"{width} × {height}", (int(width), int(height)))
        self.combo.addItem(self._custom_label, None)
        self.combo.currentIndexChanged.connect(self._on_resolution_index)
        root.addWidget(self.combo)

        # The custom size row stays hidden until Custom is chosen, so the common
        # case is a single click and the page does not grow two extra inputs.
        self._custom_row = QWidget()
        custom = QHBoxLayout(self._custom_row)
        custom.setContentsMargins(0, 0, 0, 0)
        custom.setSpacing(6)
        self.width_edit = QSpinBox()
        self.width_edit.setRange(320, 7680)
        self.width_edit.setValue(2560)
        self.height_edit = QSpinBox()
        self.height_edit.setRange(240, 4320)
        self.height_edit.setValue(1440)
        custom.addWidget(QLabel("W"))
        custom.addWidget(self.width_edit, 1)
        custom.addWidget(QLabel("H"))
        custom.addWidget(self.height_edit, 1)
        self.width_edit.valueChanged.connect(lambda *_: self.changed.emit())
        self.height_edit.valueChanged.connect(lambda *_: self.changed.emit())
        root.addWidget(self._custom_row)
        self._custom_row.setVisible(False)

        self._width = self.width_edit.value()
        self._height = self.height_edit.value()

    def _on_resolution_index(self, _index: int) -> None:
        data = self.combo.currentData()
        if data is None:
            # Custom: reveal the W/H inputs, seeded from the current size.
            self.width_edit.blockSignals(True)
            self.height_edit.blockSignals(True)
            self.width_edit.setValue(max(320, min(7680, self._width)))
            self.height_edit.setValue(max(240, min(4320, self._height)))
            self.width_edit.blockSignals(False)
            self.height_edit.blockSignals(False)
            self._custom_row.setVisible(True)
        else:
            self._width, self._height = int(data[0]), int(data[1])
            self._custom_row.setVisible(False)
        self.changed.emit()

    def _build_keybind(self, root) -> None:
        """A click-to-bind control instead of a fixed list of keys.

        A menu can only ever offer the handful of keys it was built with, and it
        stores a menu choice rather than the key the user actually wants. This
        control is pressed and records the real virtual-key code the operating
        system reports for the next key or mouse button (left mouse is exactly
        0x01), so any key works and the value is what the engine polls.
        """
        root.addWidget(self._head())
        self.capture = KeybindCapture(self.field.get("default", 0x12))
        self.capture.captured.connect(lambda *_: self.changed.emit())
        root.addWidget(self.capture)

    def _build_string(self, root) -> None:
        root.addWidget(self._head())
        self.edit = QLineEdit()
        self.edit.textChanged.connect(lambda *_: self.changed.emit())
        root.addWidget(self.edit)

    def _build_inttext(self, root) -> None:
        self._min = int(self.field.get("min", 0))
        self._max = int(self.field.get("max", 2_147_483_647))
        self._default = int(self.field.get("default", self._min))
        root.addWidget(self._head())
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(str(self._default))
        self.edit.textChanged.connect(lambda *_: self.changed.emit())
        root.addWidget(self.edit)

    def _head(self) -> QLabel:
        lbl = QLabel(self._label_text)
        lbl.setObjectName("fieldLabel")
        return lbl

    # ---- value io -----------------------------------------------------------
    def value(self):
        if self.type in ("float", "int"):
            return int(round(self._value)) if self.type == "int" else float(self._value)
        if self.type == "inttext":
            text = self.edit.text().strip()
            try:
                v = int(text)
            except ValueError:
                return self._default
            return max(self._min, min(self._max, v))
        if self.type == "bool":
            return self.check.isChecked()
        if self.type == "choice":
            return self.combo.currentText()
        if self.type == "keybind":
            return self.capture.value()
        if self.type == "model":
            return self._model_path
        if self.type == "color":
            return self._color
        if self.type == "resolution":
            width = self.width_edit.value() if self.combo.currentData() is None else self._width
            height = self.height_edit.value() if self.combo.currentData() is None else self._height
            return (int(width), int(height))
        return self.edit.text()

    def set_value(self, val) -> None:
        if self.type in ("float", "int"):
            try:
                v = float(val)
            except (TypeError, ValueError):
                v = self._min
            v = max(self._min, min(self._max, v))
            self._value = int(round(v)) if self.type == "int" else v
            sval = int(round((v - self._min) / self._step))
            self.slider.blockSignals(True)
            self.slider.setValue(max(0, min(self._steps, sval)))
            self.slider.blockSignals(False)
            self._refresh_label()
        elif self.type == "inttext":
            try:
                v = int(val)
            except (TypeError, ValueError):
                v = self._default
            v = max(self._min, min(self._max, v))
            self.edit.blockSignals(True)
            self.edit.setText(str(v))
            self.edit.blockSignals(False)
        elif self.type == "bool":
            self.check.blockSignals(True)
            self.check.setChecked(bool(val))
            self.check.blockSignals(False)
        elif self.type == "choice":
            self.combo.blockSignals(True)
            i = self.combo.findText(str(val))
            self.combo.setCurrentIndex(i if i >= 0 else 0)
            self.combo.blockSignals(False)
        elif self.type == "keybind":
            self.capture.set_value(val)
        elif self.type == "model":
            self._model_path = str(val or "")
            # Select the matching entry by its stored path. When the path is one
            # of the listed models the filename is highlighted; otherwise the
            # "Custom path…" entry is shown so the dropdown reflects that a file
            # outside models/ is in use.
            self.combo.blockSignals(True)
            index = self.combo.findData(self._model_path) if self._model_path else -1
            if index < 0 and self._model_path:
                index = self.combo.count() - 1  # the "Custom path…" entry
            self.combo.setCurrentIndex(index if index >= 0 else 0)
            self.combo.blockSignals(False)
            self._refresh_model_hint()
        elif self.type == "color":
            self._color = str(val or self.field.get("default", "#2F4BFF"))
            self._apply_swatch()
        elif self.type == "resolution":
            width, height = self._parse_resolution(val)
            self._width, self._height = width, height
            self.combo.blockSignals(True)
            # Compare the preset tuples ourselves: Qt's findData() does not
            # reliably match a Python tuple, so it always reported "not found"
            # and the dropdown showed Custom even for a listed preset.
            index = -1
            for i in range(self.combo.count()):
                data = self.combo.itemData(i)
                if isinstance(data, (tuple, list)) and len(data) == 2 \
                        and int(data[0]) == width and int(data[1]) == height:
                    index = i
                    break
            if index < 0:
                # Not a listed preset: show Custom with the exact W/H filled in.
                index = self.combo.count() - 1
                self.width_edit.blockSignals(True)
                self.height_edit.blockSignals(True)
                self.width_edit.setValue(max(320, min(7680, width)))
                self.height_edit.setValue(max(240, min(4320, height)))
                self.width_edit.blockSignals(False)
                self.height_edit.blockSignals(False)
                self._custom_row.setVisible(True)
            else:
                self._custom_row.setVisible(False)
            self.combo.setCurrentIndex(index)
            self.combo.blockSignals(False)
        else:
            self.edit.blockSignals(True)
            self.edit.setText(str(val))
            self.edit.blockSignals(False)

    @staticmethod
    def _parse_resolution(val):
        """Accept a (w, h) tuple/list or a "WxH" string; default 1920x1080."""
        if isinstance(val, (tuple, list)) and len(val) >= 2:
            try:
                return int(val[0]), int(val[1])
            except (TypeError, ValueError):
                return 1920, 1080
        if isinstance(val, str) and ("x" in val.lower()):
            parts = val.lower().replace(" ", "").split("x")
            if len(parts) == 2:
                try:
                    return int(parts[0]), int(parts[1])
                except ValueError:
                    pass
        return 1920, 1080


class Card(QFrame):
    """A titled section that stacks FieldRows, with a soft show-in animation."""

    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setProperty("role", "card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 14, 16, 16)
        self._layout.setSpacing(6)
        if title:
            header = QLabel(title)
            header.setObjectName("cardTitle")
            self._layout.addWidget(header)
        if subtitle:
            hint = QLabel(subtitle)
            hint.setObjectName("hint")
            hint.setWordWrap(True)
            self._layout.addWidget(hint)

    def add_row(self, row: QWidget) -> None:
        self._layout.addWidget(row)

    def add_widget(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)


class MetricTile(QFrame):
    """A compact live-number tile for the dashboard grid."""

    def __init__(self, label: str, unit: str = "", parent=None):
        super().__init__(parent)
        self.setProperty("role", "metric")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(2)
        self._caption = QLabel(label)
        self._caption.setObjectName("hint")
        self._value = QLabel("--")
        self._value.setObjectName("metricValue")
        self._unit = QLabel(unit)
        self._unit.setObjectName("metricUnit")
        lay.addWidget(self._caption)
        lay.addWidget(self._value)
        lay.addWidget(self._unit)

    def set_value(self, text: str) -> None:
        self._value.setText(text)


class HeaderStat(QFrame):
    """A compact inline stat for the masthead: ``Caption  value``.

    The live figures (frame rate, capture-to-detection latency, target state and
    frame number) used to live on their own Overview/Dashboard page. They are far
    more useful pinned in the header, visible while any settings page is open, so
    this is the small right-aligned readout that replaces that page.
    """

    def __init__(self, caption: str, value: str = "--", parent=None):
        super().__init__(parent)
        self.setProperty("role", "headerStat")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 4, 12, 4)
        lay.setSpacing(0)
        self._caption = QLabel(caption)
        self._caption.setObjectName("headerStatCaption")
        self._value = QLabel(value)
        self._value.setObjectName("headerStatValue")
        self._value.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self._caption)
        lay.addWidget(self._value)

    def set_value(self, text: str) -> None:
        self._value.setText(text)


class ToggleSwitch(QCheckBox):
    """A pill toggle that animates its knob — the Lunar-style on/off control."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._offset = 0.0
        self.stateChanged.connect(self._animate)
        self.setStyleSheet(f"""
            QCheckBox {{ spacing: 10px; font-weight: 600; }}
            QCheckBox::indicator {{
                width: 38px; height: 20px; border-radius: 10px;
                border: 1px solid {theme.BORDER_STRONG};
                background-color: {theme.BG_INPUT};
            }}
            QCheckBox::indicator:checked {{
                background-color: {theme.ACCENT};
                border-color: {theme.ACCENT};
            }}
        """)

    # ``knob`` must be a real Qt property for the same reason as ``animatedValue``
    # on FieldRow: QPropertyAnimation only drives properties exposed through Qt's
    # meta-object, and a plain attribute produced the "non-existing property knob"
    # warning and a toggle that never moved.
    def _get_knob(self):
        return float(self._offset)

    def _set_knob(self, value):
        self._offset = float(value)

    knob = Property(float, _get_knob, _set_knob)

    def _animate(self, _state):
        anim = QPropertyAnimation(self, b"knob")
        anim.setDuration(160)
        anim.setStartValue(self._offset)
        anim.setEndValue(1.0 if self.isChecked() else 0.0)
        anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        anim.valueChanged.connect(self._set_knob)
        anim.start()
        self._anim = anim
