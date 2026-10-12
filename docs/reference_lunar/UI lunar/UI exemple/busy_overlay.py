"""Centered busy indicator covering a parent widget (content area)."""

from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QLabel, QProgressBar, QWidget

import theme


class BusyOverlay(QFrame):
    """Non-modal overlay child — must be parented to the content widget to cover."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("busyOverlay")
        self.hide()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        panel = QVBoxLayout()
        panel.setSpacing(14)
        panel.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._bar = QProgressBar()
        self._bar.setRange(0, 0)  # indeterminate
        self._bar.setFixedSize(240, 8)
        self._bar.setTextVisible(False)

        self._label = QLabel("Please wait…")
        self._label.setObjectName("busyLabel")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        panel.addWidget(self._bar, alignment=Qt.AlignmentFlag.AlignCenter)
        panel.addWidget(self._label, alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addLayout(panel)

        self.setStyleSheet(f"""
            QFrame#busyOverlay {{
                background-color: rgba(13, 13, 13, 215);
            }}
            QLabel#busyLabel {{
                color: {theme.TEXT};
                font-size: 11pt;
                background: transparent;
            }}
            QProgressBar {{
                border: none;
                background: #2a2a2a;
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background: {theme.ACCENT_BLUE};
                border-radius: 4px;
            }}
        """)

        parent.installEventFilter(self)

    def show_busy(self, message: str = "Please wait…"):
        self._label.setText(message)
        self._sync_geometry()
        self.raise_()
        self.show()

    def hide_busy(self):
        self.hide()

    def _sync_geometry(self):
        parent = self.parentWidget()
        if parent:
            self.setGeometry(0, 0, parent.width(), parent.height())

    def eventFilter(self, obj, event):
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self._sync_geometry()
        return super().eventFilter(obj, event)
