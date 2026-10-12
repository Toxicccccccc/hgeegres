"""Transparent, click-through, always-on-top FOV guide.

The Overlay page has offered *Show FOV Guide* and *FOV Colour* for a while, but
nothing ever drew them: the settings were stored and ignored, so toggling the
guide on did nothing. This is the missing surface.

It paints where the detector is actually looking -- the square (or circle) the
engine captures around the crosshair -- centred on the screen and drawn in the
configured colour. Because it is transparent to the mouse and never takes focus,
it can sit over a running game without stealing clicks or alt-tabbing the player
out. It reads the screen size, FOV, shape, offsets and colour from the live
settings, so resizing the FOV on the Detection page moves the guide immediately.
"""

from __future__ import annotations

from qt import (
    Qt, QColor, QPainter, QPen, QWidget, QApplication,
)


class FovGuide(QWidget):
    """Full-screen overlay that outlines the capture region."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        # Geometry/colour, refreshed from settings whenever they change.
        self._fov = 320
        self._shape = "Square"
        self._color = QColor("#2F4BFF")
        self._offset_x = 0
        self._offset_y = 0
        self._screen_w = 1920
        self._screen_h = 1080

    # ---- configuration ------------------------------------------------------
    def apply(self, *, fov=None, shape=None, color=None,
              offset_x=None, offset_y=None, screen_w=None, screen_h=None) -> None:
        """Update the guide from the current settings and repaint.

        Every argument is optional so the caller can push just the field that
        changed (for example the FOV slider) without recomputing the rest.
        """
        if fov is not None:
            try:
                self._fov = max(16, int(fov))
            except (TypeError, ValueError):
                pass
        if shape:
            self._shape = str(shape)
        if color:
            parsed = QColor(str(color))
            if parsed.isValid():
                self._color = parsed
        if offset_x is not None:
            try:
                self._offset_x = int(offset_x)
            except (TypeError, ValueError):
                pass
        if offset_y is not None:
            try:
                self._offset_y = int(offset_y)
            except (TypeError, ValueError):
                pass
        if screen_w is not None:
            try:
                self._screen_w = max(1, int(screen_w))
            except (TypeError, ValueError):
                pass
        if screen_h is not None:
            try:
                self._screen_h = max(1, int(screen_h))
            except (TypeError, ValueError):
                pass
        if self.isVisible():
            self._cover_primary_screen()
        self.update()

    def _cover_primary_screen(self) -> None:
        """Stretch the transparent window across the primary display."""
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.geometry()
        self.setGeometry(geometry)
        self._screen_w = geometry.width()
        self._screen_h = geometry.height()

    def showEvent(self, event):  # noqa: N802 (Qt naming)
        super().showEvent(event)
        self._cover_primary_screen()

    # ---- painting -----------------------------------------------------------
    def paintEvent(self, _event):  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # The guide is centred on the screen centre plus the configured offset,
        # which is exactly how the engine computes its capture origin.
        center_x = self.width() / 2 + self._offset_x
        center_y = self.height() / 2 + self._offset_y
        half = self._fov / 2.0

        # Outline only: no fill. A translucent fill tinted the whole capture
        # region, which both hid the game underneath and read as an opaque box.
        # Drawing just the bright outline marks exactly where the detector looks
        # while leaving the screen inside the guide completely clear.
        outline = QColor(self._color)
        outline.setAlpha(220)

        pen = QPen(outline)
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if self._shape.lower() == "circle":
            painter.drawEllipse(
                int(center_x - half), int(center_y - half),
                int(self._fov), int(self._fov),
            )
        else:
            painter.drawRect(
                int(center_x - half), int(center_y - half),
                int(self._fov), int(self._fov),
            )
        painter.end()
