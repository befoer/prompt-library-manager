"""程序化绘制的工具栏图标（布尔运算风格 / 漏斗 / 排序箭头）。

不用文字字形，直接 QPainter 绘制，可控制颜色与大小，支持选中态配色。
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF

SIZE = 22
QSIZE = QSize(22, 22)
GRAY = "#c9c9c9"
ACTIVE = "#4fc3f7"


def _pixmap(kind: str, color: str, size: int = SIZE) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor(color)
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    cx = size / 2

    if kind == "single":
        # 实心正方形
        r = size * 0.44
        p.drawRect(QRectF(cx - r / 2, cx - r / 2, r, r))

    elif kind == "multi":
        # 两个重叠的实心正方形（后一个稍暗，前一个全亮）
        r = size * 0.42
        off = size * 0.15
        back = QColor(color)
        back.setAlpha(120)
        p.setBrush(back)
        p.drawRect(QRectF(cx - r / 2 - off, cx - r / 2 + off, r, r))
        p.setBrush(c)
        p.drawRect(QRectF(cx - r / 2 + off, cx - r / 2 - off, r, r))

    elif kind == "subtract":
        # 空心正方形叠加在实心正方形上面
        r = size * 0.44
        off = size * 0.12
        p.setBrush(c)
        p.drawRect(QRectF(cx - r / 2 - off, cx - r / 2 + off, r, r))  # 实心（左下）
        p.setBrush(Qt.NoBrush)
        pen = QPen(c)
        pen.setWidthF(size * 0.10)
        p.setPen(pen)
        p.drawRect(QRectF(cx - r / 2 + off, cx - r / 2 - off, r, r))  # 空心（右上）

    elif kind == "funnel":
        # 漏斗：上宽下窄的梯形 + 底部小矩形
        m = size * 0.15
        top_w = size - 2 * m
        narrow_w = size * 0.40
        stem_w = size * 0.16
        stem_h = size * 0.20
        top_y = m
        bot_y = size - m - stem_h
        poly = QPolygonF([
            QPointF(m, top_y),
            QPointF(m + top_w, top_y),
            QPointF(cx + narrow_w / 2, bot_y),
            QPointF(cx - narrow_w / 2, bot_y),
        ])
        p.drawPolygon(poly)
        p.drawRect(QRectF(cx - stem_w / 2, bot_y, stem_w, stem_h))

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


def make_icon(kind: str, size: int = SIZE) -> QIcon:
    """生成带 Off/On 两态的图标（Off 灰、On 蓝），供 checkable 按钮使用。"""
    icon = QIcon()
    icon.addPixmap(_pixmap(kind, GRAY, size), QIcon.Normal, QIcon.Off)
    icon.addPixmap(_pixmap(kind, ACTIVE, size), QIcon.Normal, QIcon.On)
    return icon


def make_static_icon(kind: str, size: int = SIZE) -> QIcon:
    """单色图标（菜单按钮用）。"""
    return QIcon(_pixmap(kind, GRAY, size))
