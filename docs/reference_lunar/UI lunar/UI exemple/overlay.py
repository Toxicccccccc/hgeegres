"""
Transparent, click-through, always-on-top overlay.

Draws the FOV box and crosshair (purely from config, works today) and, when the
C++ backend publishes a detection stream, the live detection / locked / predicted
boxes mapped around the screen center. Without the stream it just shows FOV +
crosshair, so it is useful immediately and gets richer once streaming is wired.
"""

import time

from PyQt6.QtCore import Qt, QTimer, QRectF
from PyQt6.QtGui import QPainter, QPen, QColor, QBrush
from PyQt6.QtWidgets import QWidget, QApplication

from stream import DetectionStream, KIND_LOCKED, KIND_PREDICTED

# Keep showing the last detections this long after a frame with none, so brief
# detector drop-outs (a missed frame or two) don't make boxes flicker.
HOLD_MS = 140

FOV_COLOR = QColor(124, 92, 255, 180)
CROSS_COLOR = QColor(255, 255, 255, 200)
DET_COLOR = QColor(61, 220, 132, 220)
LOCK_COLOR = QColor(255, 84, 112, 240)
PRED_COLOR = QColor(255, 196, 0, 220)


class Overlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self.show_fov = True
        self.show_crosshair = True
        self.show_detections = True
        self.fov_size = 256

        self.stream = DetectionStream()
        self._snapshot = None
        self._snapshot_time = 0.0

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

    # ---- control -----------------------------------------------------------
    def set_options(self, *, show_fov=None, show_crosshair=None,
                    show_detections=None, fov_size=None):
        if show_fov is not None:
            self.show_fov = show_fov
        if show_crosshair is not None:
            self.show_crosshair = show_crosshair
        if show_detections is not None:
            self.show_detections = show_detections
        if fov_size is not None:
            self.fov_size = int(fov_size)
        self.update()

    def start(self):
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)
        self.showFullScreen()
        self.timer.start(16)  # ~60 Hz

    def stop(self):
        self.timer.stop()
        self.hide()

    # ---- loop --------------------------------------------------------------
    def _tick(self):
        # read() lazily (re)opens the mapping, so this keeps retrying until the
        # backend creates it — handles the backend being started after the overlay.
        if self.show_detections:
            snap = self.stream.read()
            if snap is not None and snap["boxes"]:
                self._snapshot = snap
                self._snapshot_time = time.monotonic()
            elif (time.monotonic() - self._snapshot_time) * 1000.0 > HOLD_MS:
                # No fresh detections for a while → let them fade out.
                self._snapshot = None
        else:
            self._snapshot = None
        self.update()

    # ---- paint -------------------------------------------------------------
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        cx = self.width() / 2.0
        cy = self.height() / 2.0

        if self.show_fov and self.fov_size > 0:
            half = self.fov_size / 2.0
            p.setPen(QPen(FOV_COLOR, 1.5))
            p.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            p.drawRect(QRectF(cx - half, cy - half, self.fov_size, self.fov_size))

        if self.show_crosshair:
            p.setPen(QPen(CROSS_COLOR, 1.5))
            p.drawLine(int(cx - 8), int(cy), int(cx + 8), int(cy))
            p.drawLine(int(cx), int(cy - 8), int(cx), int(cy + 8))

        if self.show_detections and self._snapshot:
            # Stream coords are crosshair-origin in NET pixels (frameW/frameH).
            # Scale them to the on-screen FOV so boxes line up with the FOV square.
            fw = self._snapshot.get("frameW") or 0
            fh = self._snapshot.get("frameH") or 0
            sx = (self.fov_size / fw) if (fw and self.fov_size > 0) else 1.0
            sy = (self.fov_size / fh) if (fh and self.fov_size > 0) else 1.0
            for (x1, y1, x2, y2, conf, kind) in self._snapshot["boxes"]:
                if kind == KIND_LOCKED:
                    color = LOCK_COLOR
                elif kind == KIND_PREDICTED:
                    color = PRED_COLOR
                else:
                    color = DET_COLOR
                p.setPen(QPen(color, 2.0))
                p.setBrush(QBrush(Qt.BrushStyle.NoBrush))
                p.drawRect(QRectF(cx + x1 * sx, cy + y1 * sy,
                                  (x2 - x1) * sx, (y2 - y1) * sy))

        p.end()

    def closeEvent(self, e):
        self.stream.close()
        super().closeEvent(e)
