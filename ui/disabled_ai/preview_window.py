"""A small always-on-top window that mirrors the captured FOV.

The Overlay page exposes a *Show Floating Preview* toggle and a *Keep Preview On
Top* toggle, but until now nothing honoured them: the only preview was the label
on the Dashboard page, so the preview appeared to be missing whenever the user
was looking at any other page. This window is that missing surface.

It is deliberately dumb: the main window pushes encoded PNG bytes into it (the
same bytes it paints on the Dashboard), and it only handles showing them and
being moved/closed. No engine or capture logic lives here.
"""

from __future__ import annotations

from qt import Qt, QLabel, QPixmap, QVBoxLayout, QWidget


class FloatingPreview(QWidget):
    """Frameless, always-on-top preview pane."""

    def __init__(self, on_top: bool = True, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Disabled AI — Live Preview")
        flags = Qt.WindowType.Window
        if on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setMinimumSize(180, 200)
        self.resize(300, 340)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)

        self.image = QLabel("Waiting for the engine…")
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumSize(168, 168)
        self.image.setStyleSheet("background:#0B0D1A; border-radius:8px; color:#8A8FA8;")
        lay.addWidget(self.image, 1)

        self.caption = QLabel("Live detection preview")
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption.setStyleSheet("color:#8A8FA8; font-size:9pt;")
        lay.addWidget(self.caption)

    def set_on_top(self, on_top: bool) -> None:
        """Re-apply the always-on-top flag without disturbing the position."""
        flags = Qt.WindowType.Window
        if on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        was_visible = self.isVisible()
        self.setWindowFlags(flags)
        if was_visible:
            # Changing window flags hides the window on some platforms; show it
            # again at the same place.
            self.show()

    def set_image(self, data: bytes) -> None:
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            return
        self.image.setPixmap(
            pixmap.scaled(self.image.size(),
                          Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation))
