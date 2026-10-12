"""Crisp monochrome line icons drawn with QPainter.

Same approach as the reference Lunar UI: thin vector strokes in a 24x24 viewbox,
rendered at 2x and recoloured per state (dim / hover / selected), so the sidebar
keeps the single-colour "web app" look without shipping PNGs.
"""

from __future__ import annotations

from qt import QIcon, QPixmap, QPainter, QPen, QColor, QPainterPath, QPolygonF, Qt, QRectF, QPointF

_VIEW = 24.0


def _pen(p: QPainter, color: str, width: float = 1.8) -> None:
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)


def _draw(name: str, p: QPainter, color: str) -> None:
    _pen(p, color)

    if name == "aim":
        p.drawEllipse(QRectF(5, 5, 14, 14))
        p.drawLine(QPointF(12, 1), QPointF(12, 5))
        p.drawLine(QPointF(12, 19), QPointF(12, 23))
        p.drawLine(QPointF(1, 12), QPointF(5, 12))
        p.drawLine(QPointF(19, 12), QPointF(23, 12))
        p.setBrush(QColor(color))
        p.drawEllipse(QRectF(10.6, 10.6, 2.8, 2.8))

    elif name == "eye":
        path = QPainterPath()
        path.moveTo(2, 12)
        path.quadTo(12, 3, 22, 12)
        path.quadTo(12, 21, 2, 12)
        p.drawPath(path)
        p.drawEllipse(QRectF(9, 9, 6, 6))

    elif name == "bolt":
        p.drawPolygon(QPolygonF([
            QPointF(13, 2), QPointF(5, 13), QPointF(11, 13),
            QPointF(10, 22), QPointF(19, 9), QPointF(13, 9), QPointF(13, 2),
        ]))

    elif name == "monitor":
        p.drawRoundedRect(QRectF(3, 4, 18, 13), 2.5, 2.5)
        p.drawLine(QPointF(8, 21), QPointF(16, 21))
        p.drawLine(QPointF(12, 17), QPointF(12, 21))

    elif name == "mouse":
        p.drawRoundedRect(QRectF(7, 3, 10, 18), 5, 5)
        p.drawLine(QPointF(12, 4), QPointF(12, 9))

    elif name == "layers":
        p.drawPolygon(QPolygonF([QPointF(12, 3), QPointF(21, 8), QPointF(12, 13), QPointF(3, 8)]))
        p.drawPolyline(QPolygonF([QPointF(3, 13), QPointF(12, 18), QPointF(21, 13)]))

    elif name == "sliders":
        for y, kx in ((6, 8), (12, 16), (18, 11)):
            p.drawLine(QPointF(3, y), QPointF(21, y))
            p.setBrush(QColor("#0B0D1A"))
            p.drawEllipse(QRectF(kx - 2.6, y - 2.6, 5.2, 5.2))

    elif name == "terminal":
        p.drawRoundedRect(QRectF(3, 4, 18, 16), 3, 3)
        p.drawPolyline(QPolygonF([QPointF(7, 10), QPointF(10, 13), QPointF(7, 16)]))
        p.drawLine(QPointF(12, 16), QPointF(16, 16))

    elif name == "gauge":
        p.drawArc(QRectF(3, 5, 18, 18), 0, 180 * 16)
        p.drawLine(QPointF(12, 14), QPointF(16, 9))
        p.setBrush(QColor(color))
        p.drawEllipse(QRectF(10.8, 12.8, 2.4, 2.4))

    elif name in ("collapse", "expand"):
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


TAB_ICON = {
    "Dashboard": "gauge",
    "Aim": "aim",
    "Detection": "eye",
    "Triggerbot": "bolt",
    "Capture": "monitor",
    "Input & Device": "mouse",
    "Overlay": "layers",
    "Advanced": "sliders",
    "Console": "terminal",
}
