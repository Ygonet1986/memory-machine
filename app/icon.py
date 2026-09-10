"""Runtime icon for the app (drawn, so it works with or without the bundle)."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap


def _draw(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Rounded background (whiteboard)
    bg = QColor("#1e2a3a")
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(bg)
    p.drawRoundedRect(QRectF(0, 0, size, size), size * 0.22, size * 0.22)

    # Three "memory" lines + a remembered dot
    margin = size * 0.24
    line_w = size - 2 * margin
    y = size * 0.30
    gap = size * 0.17
    p.setPen(QPen(QColor("#e8eef7"), size * 0.055, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for i in range(3):
        p.drawLine(int(margin), int(y + i * gap), int(margin + line_w), int(y + i * gap))

    # Dot (a remembered memory)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#5db9ff"))
    dot_r = size * 0.075
    p.drawEllipse(QRectF(margin, size * 0.72, dot_r * 2, dot_r * 2))

    p.end()
    return pm


def icon() -> QIcon:
    return QIcon(_draw(256))


def pixmap(size: int = 512) -> QPixmap:
    return _draw(size)
