"""Crisp monochrome line icons for the sidebar, drawn with QPainter.

Using vector strokes (instead of the bundled colored PNGs) gives the thin,
single-color "web app" look and lets us recolor per state (dim / hover /
selected). Each icon is drawn in a 24x24 viewbox and rendered at 2x for
sharpness.
"""

from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor, QPainterPath, QPolygonF


_VIEW = 24.0


def _pen(p: QPainter, color: str, width: float = 1.8):
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)


def _draw(name: str, p: QPainter, color: str):
    _pen(p, color)

    if name == "aim":  # crosshair
        p.drawEllipse(QRectF(5, 5, 14, 14))
        p.drawLine(QPointF(12, 1), QPointF(12, 5))
        p.drawLine(QPointF(12, 19), QPointF(12, 23))
        p.drawLine(QPointF(1, 12), QPointF(5, 12))
        p.drawLine(QPointF(19, 12), QPointF(23, 12))
        p.setBrush(QColor(color))
        p.drawEllipse(QRectF(10.6, 10.6, 2.8, 2.8))

    elif name == "eye":  # detection
        path = QPainterPath()
        path.moveTo(2, 12)
        path.quadTo(12, 3, 22, 12)
        path.quadTo(12, 21, 2, 12)
        p.drawPath(path)
        p.drawEllipse(QRectF(9, 9, 6, 6))

    elif name == "tracker":  # bracketed target + dot
        for (sx, sy, ex, ey) in [
            (4, 8, 4, 4), (4, 4, 8, 4),         # top-left
            (20, 8, 20, 4), (20, 4, 16, 4),     # top-right
            (4, 16, 4, 20), (4, 20, 8, 20),     # bottom-left
            (20, 16, 20, 20), (20, 20, 16, 20), # bottom-right
        ]:
            p.drawLine(QPointF(sx, sy), QPointF(ex, ey))
        p.setBrush(QColor(color))
        p.drawEllipse(QRectF(10.5, 10.5, 3, 3))

    elif name == "bolt":  # triggerbot
        poly = QPolygonF([
            QPointF(13, 2), QPointF(5, 13), QPointF(11, 13),
            QPointF(10, 22), QPointF(19, 9), QPointF(13, 9), QPointF(13, 2),
        ])
        p.drawPolygon(poly)

    elif name == "monitor":  # capture
        p.drawRoundedRect(QRectF(3, 4, 18, 13), 2.5, 2.5)
        p.drawLine(QPointF(8, 21), QPointF(16, 21))
        p.drawLine(QPointF(12, 17), QPointF(12, 21))

    elif name == "mouse":  # input & device
        p.drawRoundedRect(QRectF(7, 3, 10, 18), 5, 5)
        p.drawLine(QPointF(12, 4), QPointF(12, 9))

    elif name == "layers":  # overlay
        p.drawPolygon(QPolygonF([
            QPointF(12, 3), QPointF(21, 8), QPointF(12, 13), QPointF(3, 8),
        ]))
        p.drawPolyline(QPolygonF([
            QPointF(3, 13), QPointF(12, 18), QPointF(21, 13),
        ]))

    elif name == "sliders":  # advanced / tune
        for y, kx in ((6, 8), (12, 16), (18, 11)):
            p.drawLine(QPointF(3, y), QPointF(21, y))
            p.setBrush(QColor("#0d0d0d"))
            p.drawEllipse(QRectF(kx - 2.6, y - 2.6, 5.2, 5.2))

    elif name == "terminal":  # backend
        p.drawRoundedRect(QRectF(3, 4, 18, 16), 3, 3)
        p.drawPolyline(QPolygonF([QPointF(7, 10), QPointF(10, 13), QPointF(7, 16)]))
        p.drawLine(QPointF(12, 16), QPointF(16, 16))

    elif name == "bug":  # debug
        p.drawEllipse(QRectF(8, 8, 8, 11))
        p.drawArc(QRectF(9, 4, 6, 6), 0, 180 * 16)  # head
        p.drawLine(QPointF(10, 5), QPointF(8.5, 2.5))   # antennae
        p.drawLine(QPointF(14, 5), QPointF(15.5, 2.5))
        for ly in (10.5, 13.5, 16.5):                   # legs
            p.drawLine(QPointF(8, ly), QPointF(4, ly - 1.5))
            p.drawLine(QPointF(16, ly), QPointF(20, ly - 1.5))

    elif name == "human":  # humanization — smooth wave / hand
        path = QPainterPath()
        path.moveTo(3, 14)
        path.cubicTo(6, 6, 10, 6, 12, 10)
        path.cubicTo(14, 14, 18, 14, 21, 8)
        p.drawPath(path)
        p.drawLine(QPointF(12, 10), QPointF(12, 20))
        p.drawLine(QPointF(8, 12), QPointF(6, 18))
        p.drawLine(QPointF(16, 12), QPointF(18, 17))

    elif name == "discord":  # chat bubble
        p.drawRoundedRect(QRectF(3, 4, 18, 12), 4, 4)
        p.drawPolygon(QPolygonF([
            QPointF(8, 16), QPointF(8, 20), QPointF(13, 16),
        ]))
        p.setBrush(QColor(color))
        p.drawEllipse(QRectF(8.5, 9, 2, 2))
        p.drawEllipse(QRectF(13.5, 9, 2, 2))

    elif name == "configs":  # stacked cards
        p.drawRoundedRect(QRectF(5, 6, 14, 16), 3, 3)
        p.drawRoundedRect(QRectF(8, 3, 14, 16), 3, 3)
        p.drawLine(QPointF(11, 8), QPointF(19, 8))
        p.drawLine(QPointF(11, 11), QPointF(17, 11))
        p.drawLine(QPointF(11, 14), QPointF(19, 14))

    elif name in ("collapse", "expand"):  # panel toggle (like the example)
        p.drawRoundedRect(QRectF(3, 4, 18, 16), 2.5, 2.5)
        p.drawLine(QPointF(15, 4), QPointF(15, 20))
        if name == "collapse":
            p.drawPolyline(QPolygonF([QPointF(11, 9), QPointF(8, 12), QPointF(11, 15)]))
        else:
            p.drawPolyline(QPolygonF([QPointF(8, 9), QPointF(11, 12), QPointF(8, 15)]))


def make_icon(name: str, color: str, size: int = 22) -> QIcon:
    scale = 2
    pm = QPixmap(size * scale, size * scale)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.scale(size * scale / _VIEW, size * scale / _VIEW)
    _draw(name, p, color)
    p.end()
    pm.setDevicePixelRatio(scale)
    return QIcon(pm)


# Tab name -> icon key
TAB_ICON = {
    "Configs": "configs",
    "Settings": "sliders",
    "Aim": "aim",
    "Detection": "eye",
    "Triggerbot": "bolt",
    "Capture": "monitor",
    "Input & Device": "mouse",
    "Overlay": "layers",
    "Discord Overlay": "discord",
    "Debug": "bug",
    "Backend": "terminal",
}
