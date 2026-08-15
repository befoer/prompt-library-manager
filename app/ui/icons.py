"""程序化绘制的工具栏图标（漏斗 / 排序箭头）。

不用文字字形，直接 QPainter 绘制，可控制颜色与大小。
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QPolygonF

SIZE = 22
QSIZE = QSize(22, 22)
GRAY = "#c9c9c9"


def _pixmap(kind: str, color: str, size: int = SIZE) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor(color)
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    cx = size / 2

    if kind == "funnel":
        # 漏斗：宽沿 → 收窄 → 细管
        m = size * 0.14
        top_w = size * 0.78
        neck_w = size * 0.24
        stem_w = size * 0.13
        stem_h = size * 0.24
        top_y = m
        bot_y = size - m - stem_h
        poly = QPolygonF([
            QPointF(cx - top_w / 2, top_y),
            QPointF(cx + top_w / 2, top_y),
            QPointF(cx + neck_w / 2, bot_y),
            QPointF(cx - neck_w / 2, bot_y),
        ])
        p.drawPolygon(poly)
        p.drawRect(QRectF(cx - stem_w / 2, bot_y - 1, stem_w, stem_h + 1))

    elif kind == "sort":
        # 上三角（指上）+ 下三角（指下）
        m = size * 0.13
        w = size * 0.40
        h = size * 0.24
        up = QPolygonF([
            QPointF(cx, m),
            QPointF(cx - w / 2, m + h),
            QPointF(cx + w / 2, m + h),
        ])
        p.drawPolygon(up)
        down = QPolygonF([
            QPointF(cx, size - m),
            QPointF(cx - w / 2, size - m - h),
            QPointF(cx + w / 2, size - m - h),
        ])
        p.drawPolygon(down)

    p.end()
    return pm


def make_static_icon(kind: str, size: int = SIZE) -> QIcon:
    """单色图标（菜单按钮用）。"""
    return QIcon(_pixmap(kind, GRAY, size))
