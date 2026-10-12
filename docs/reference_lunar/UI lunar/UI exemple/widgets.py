"""Form controls styled like the original Lunar V2.

Lunar V2 shows a control's value inside its label ("Base Speed: 0.120") above a
gradient slider, uses round purple checkboxes, and dark comboboxes. These
widgets reproduce that while staying driven by the config schema.
"""

from PyQt6.QtCore import Qt, pyqtSignal, QObject, QEvent
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QHBoxLayout, QVBoxLayout, QSlider, QSpinBox,
    QDoubleSpinBox, QCheckBox, QComboBox, QLineEdit, QFrame,
)

from config_schema import KEYBIND_OPTIONS


# --- scroll-proof inputs (so scrolling the page doesn't change values) -------
class _ScrollPassthrough(QObject):
    """Forward wheel events to the parent so the page scrolls instead."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Wheel:
            parent = obj.parent()
            if parent:
                QApplication.sendEvent(parent, event)
            return True
        return False


class NoScrollSlider(QSlider):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._pt = _ScrollPassthrough(self)
        self.installEventFilter(self._pt)


class NoScrollComboBox(QComboBox):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._pt = _ScrollPassthrough(self)
        self.installEventFilter(self._pt)


class FieldRow(QWidget):
    """A single labeled config control. Emits `changed` whenever the value moves."""

    changed = pyqtSignal()

    def __init__(self, field: dict, parent=None):
        super().__init__(parent)
        self.field = field
        self.key = field["key"]
        self.type = field["type"]
        self._label_text = field["label"]
        self._build()

    # ------------------------------------------------------------------ build
    def _build(self):
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
        else:  # string
            self._build_string(root)

        tip = self.field.get("tooltip")
        if tip:
            self.setToolTip(tip)

    # ---- numeric: "Label: value" above a gradient slider -------------------
    def _build_numeric(self, root):
        is_float = self.type == "float"
        self._min = float(self.field.get("min", 0))
        self._max = float(self.field.get("max", 100))
        self._step = float(self.field.get("step", 1)) if is_float else 1.0
        self._decimals = int(self.field.get("decimals", 0))
        self._steps = max(1, int(round((self._max - self._min) / self._step)))

        self.label = QLabel(self._label_text)
        self.label.setObjectName("fieldLabel")
        root.addWidget(self.label)

        self.slider = NoScrollSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, self._steps)
        self.slider.valueChanged.connect(self._on_slider)
        root.addWidget(self.slider)

        self._value = self._min
        self._refresh_label()

    def _on_slider(self, sval):
        self._value = self._min + sval * self._step
        if self.type == "int":
            self._value = int(round(self._value))
        self._refresh_label()
        self.changed.emit()

    def _refresh_label(self):
        if self.type == "int":
            shown = f"{int(round(self._value))}"
        else:
            shown = f"{self._value:.{self._decimals}f}"
        self.label.setText(f"{self._label_text}: {shown}")

    # ---- bool: round purple checkbox with text -----------------------------
    def _build_bool(self, root):
        self.check = QCheckBox(self._label_text)
        self.check.stateChanged.connect(lambda *_: self.changed.emit())
        root.addWidget(self.check)

    # ---- choice / keybind: label + combo -----------------------------------
    def _build_choice(self, root):
        root.addWidget(self._head())
        self.combo = NoScrollComboBox()
        self.combo.addItems(self.field.get("choices", []))
        self.combo.currentIndexChanged.connect(lambda *_: self.changed.emit())
        root.addWidget(self.combo)

    def _build_keybind(self, root):
        root.addWidget(self._head())
        self.combo = NoScrollComboBox()
        self._vk_by_index = []
        for name, vk in KEYBIND_OPTIONS:
            fmt = f"0x{vk:X}" if vk >= 0x10000 else f"0x{vk:02X}"
            self.combo.addItem(f"{name}  ({fmt})")
            self._vk_by_index.append(vk)
        self.combo.currentIndexChanged.connect(lambda *_: self.changed.emit())
        root.addWidget(self.combo)

    # ---- string: label + line edit -----------------------------------------
    def _build_string(self, root):
        root.addWidget(self._head())
        self.edit = QLineEdit()
        self.edit.textChanged.connect(lambda *_: self.changed.emit())
        root.addWidget(self.edit)

    # ---- int as typed field (baud, ports, device ids — not sliders) ---------
    def _build_inttext(self, root):
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

    # --------------------------------------------------------------- value io
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
            idx = self.combo.currentIndex()
            return self._vk_by_index[idx] if 0 <= idx < len(self._vk_by_index) else 0
        return self.edit.text()

    def set_value(self, val):
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
            self.combo.blockSignals(True)
            try:
                i = self._vk_by_index.index(int(val))
            except (ValueError, TypeError):
                i = 0
            self.combo.setCurrentIndex(i)
            self.combo.blockSignals(False)
        else:
            self.edit.blockSignals(True)
            self.edit.setText(str(val))
            self.edit.blockSignals(False)


class Card(QFrame):
    """A transparent, titled section that stacks FieldRows (Lunar V2 style)."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(10, 10, 10, 10)
        self._layout.setSpacing(4)
        if title:
            header = QLabel(title)
            header.setObjectName("cardTitle")
            self._layout.addWidget(header)

    def add_row(self, row: QWidget):
        self._layout.addWidget(row)
