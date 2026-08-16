"""条目列表视图 + 自绘 delegate（状态圆点 / 复选框 / 英文·中文两栏 / 搜索高亮 / 行内编辑 / 拖拽排序）。

两栏布局：左侧英文原文（等宽字体），右侧中文翻译（微软雅黑，正常非斜体）。
"""
from __future__ import annotations

import re

from PySide6.QtCore import QItemSelectionModel, QModelIndex, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLineEdit,
    QListView,
    QStyle,
    QStyleOptionButton,
    QStyledItemDelegate,
)

from app import resources
from app.core.model import PromptEntry
from app.ui.entry_model import ENTRY_ROLE

ROW_H = 26          # 单行高度
DOT_X = 6
DOT_SIZE = 8
CHECKBOX_X = 18
TEXT_X = 38
SPLIT_RATIO = 0.52  # 英文栏占文本区比例，剩余为中文栏
DIVIDER_GAP = 16    # 两栏之间分隔线占用的宽度

STATE_COLORS = {
    "untranslated": "#5f5f5f",
    "translated": "#4ec9b0",
    "stale": "#d19a66",
}

HL_BG = "#5a4a00"
HL_FG = "#ffd54f"


def match_range(text: str, query: str, mode: str):
    """返回命中子串在原文本中的 [start, end)，无命中返回 None。与模型过滤逻辑一致。"""
    if not query or not text:
        return None
    try:
        if mode == "regex":
            m = re.search(query, text, re.IGNORECASE)
        elif mode == "prefix":
            m = re.match(re.escape(query), text, re.IGNORECASE)
        elif mode == "exact":
            m = re.fullmatch(re.escape(query), text, re.IGNORECASE)
        else:  # contains
            m = re.search(re.escape(query), text, re.IGNORECASE)
    except re.error:
        return None
    return (m.start(), m.end()) if m else None


def checkbox_rect_for_rect(r: QRect) -> QRect:
    size = 14
    return QRect(r.left() + CHECKBOX_X, r.center().y() - size // 2, size, size)


def checkbox_click_rect(r: QRect) -> QRect:
    """复选框的点击命中区（比绘制框略大，方便点选）。"""
    return checkbox_rect_for_rect(r).adjusted(-3, -4, 3, 4)


def translate_button_rect(rect: QRect, text: str, layout: str, font) -> QRect:
    """未翻译条目中文栏起始处的翻译按钮位置（绘制与点击检测共用）。"""
    total = rect.adjusted(TEXT_X, 0, -4, 0)
    size = 14
    y = rect.center().y() - size // 2
    if layout == "compact":
        probe = QFont(font)
        probe.setPointSizeF(10.5)
        en_w = min(QFontMetrics(probe).horizontalAdvance(text), int(total.width() * 0.6))
        sep_w = QFontMetrics(probe).horizontalAdvance(" | ")
        x = total.left() + en_w + sep_w + 2
    else:
        left_w = int(total.width() * SPLIT_RATIO) - DIVIDER_GAP // 2
        x = total.left() + left_w + DIVIDER_GAP + 2
    return QRect(int(x), int(y), size, size)


def is_partial_translation(text: str) -> bool:
    """判断翻译是否含英文残留（离线词典部分命中，中英混杂）。"""
    if not text:
        return False
    has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in text)
    has_alpha = any(ch.isascii() and ch.isalpha() for ch in text)
    return has_cjk and has_alpha


class EntryDelegate(QStyledItemDelegate):
    """绘制：状态圆点 + 复选框（镜像选中）+ 英文 + 中文翻译（分栏 / 紧凑两种布局）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = "split"  # "split" = 分栏, "compact" = 紧凑
        self.translate_icon = None
        p = resources.resource_path("翻译.svg")
        if p is not None:
            self.translate_icon = QIcon(str(p))

    def sizeHint(self, option, index) -> QSize:
        return QSize(0, ROW_H)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        painter.save()
        view = self.parent()
        entry: PromptEntry | None = index.data(ENTRY_ROLE) if index.isValid() else None
        selected = bool(view is not None and view.selectionModel()
                        and view.selectionModel().isSelected(index))

        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, QColor("#094771"))
        elif option.state & QStyle.State_MouseOver:
            painter.fillRect(option.rect, QColor("#2a2d2e"))

        # 状态圆点
        if entry is not None:
            state = "untranslated"
            if entry.translation:
                state = "stale" if entry.translation_dirty else "translated"
            dot = QRect(option.rect.left() + DOT_X,
                        option.rect.center().y() - DOT_SIZE // 2, DOT_SIZE, DOT_SIZE)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(STATE_COLORS[state]))
            painter.drawEllipse(dot)

        # 复选框
        cb = QStyleOptionButton()
        cb.rect = checkbox_rect_for_rect(option.rect)
        cb.state = QStyle.State_Enabled | (QStyle.State_On if selected else QStyle.State_Off)
        if view is not None:
            view.style().drawControl(QStyle.CE_CheckBox, cb, painter, view)

        # 文本
        text = index.data(Qt.DisplayRole) or ""
        model = index.model()
        query = getattr(model, "query", "") or ""
        mode = getattr(model, "mode", "contains")
        hl = match_range(text, query, mode) if query else None
        en_color = "#ffffff" if selected else "#e8e8e8"
        zh_color = "#d8e6ee" if selected else "#93a7b3"

        total = option.rect.adjusted(TEXT_X, 0, -4, 0)

        if self.layout == "compact":
            # 紧凑布局：英文自然宽度 + "|" + 中文紧随其后，减少短条目间隙
            probe = QFont(option.font)
            probe.setPointSizeF(10.5)
            en_w = min(QFontMetrics(probe).horizontalAdvance(text), int(total.width() * 0.6))
            en_rect = QRect(total.left(), total.top(), en_w, total.height())
            self._draw_line(painter, option, en_rect, text, 10.5, en_color, hl=hl)

            sep = " | "
            sepf = QFont(option.font)
            sepf.setPointSizeF(10)
            sep_w = QFontMetrics(sepf).horizontalAdvance(sep)
            sep_rect = QRect(en_rect.right(), total.top(), sep_w, total.height())
            painter.setFont(sepf)
            painter.setPen(QColor("#4a4d52"))
            painter.drawText(sep_rect, Qt.AlignVCenter | Qt.AlignLeft, sep)

            zh_rect = QRect(en_rect.right() + sep_w, total.top(),
                            max(0, total.right() - en_rect.right() - sep_w), total.height())
            if entry is not None and entry.translation:
                zh = entry.translation + (" ⚠ 需更新" if entry.translation_dirty else "")
                self._draw_line(painter, option, zh_rect, zh, 10, zh_color,
                                family="Microsoft YaHei UI")
        else:
            # 分栏布局：英文左栏 + 中文右栏（固定比例 + 分隔线）
            left_w = max(0, int(total.width() * SPLIT_RATIO) - DIVIDER_GAP // 2)
            left_rect = QRect(total.left(), total.top(), left_w, total.height())
            right_rect = QRect(total.left() + left_w + DIVIDER_GAP, total.top(),
                               max(0, total.width() - left_w - DIVIDER_GAP), total.height())

            painter.setPen(QColor("#33363b"))
            dx = total.left() + left_w + DIVIDER_GAP // 2
            painter.drawLine(dx, option.rect.top() + 5, dx, option.rect.bottom() - 5)

            self._draw_line(painter, option, left_rect, text, 10.5, en_color, hl=hl)

            if entry is not None and entry.translation:
                zh = entry.translation + (" ⚠ 需更新" if entry.translation_dirty else "")
                self._draw_line(painter, option, right_rect, zh, 10, zh_color,
                                family="Microsoft YaHei UI")

        # 未翻译 / 部分翻译：中文栏起始处显示翻译按钮
        if entry is not None and self.translate_icon is not None:
            if not entry.translation or is_partial_translation(entry.translation):
                btn_rect = translate_button_rect(option.rect, text, self.layout, option.font)
                self.translate_icon.paint(painter, btn_rect)

        painter.restore()

    @staticmethod
    def _draw_line(painter, option, rect, text, pt, color, family=None, hl=None):
        f = QFont(option.font)
        if family:
            f.setFamily(family)
        f.setPointSizeF(pt)
        painter.setFont(f)
        fm = QFontMetrics(f)
        elided = fm.elidedText(text, Qt.ElideRight, rect.width())
        painter.setPen(QColor(color))
        painter.drawText(rect, Qt.AlignVCenter | Qt.AlignLeft, elided)
        # 搜索命中高亮（仅当命中段完全可见、未被省略时）
        if hl is not None and elided == text:
            start, end = hl
            if 0 <= start < end <= len(text):
                before_w = fm.horizontalAdvance(text[:start])
                hit_w = fm.horizontalAdvance(text[start:end])
                hl_rect = QRect(rect.left() + int(before_w), rect.top(), int(hit_w), rect.height())
                painter.fillRect(hl_rect, QColor(HL_BG))
                painter.setPen(QColor(HL_FG))
                painter.drawText(hl_rect, Qt.AlignVCenter | Qt.AlignLeft, text[start:end])

    def createEditor(self, parent, option, index):
        ed = QLineEdit(parent)
        ed.setFrame(False)
        ed.setStyleSheet(
            "QLineEdit { background:#2d2d2d; color:#ffffff; "
            "selection-background-color:#094771; selection-color:#ffffff; "
            "padding:2px 4px; border:1px solid #4fc3f7; }"
        )
        pal = ed.palette()
        pal.setColor(QPalette.Text, QColor("#ffffff"))
        pal.setColor(QPalette.Base, QColor("#2d2d2d"))
        ed.setPalette(pal)
        return ed

    def setEditorData(self, editor, index):
        editor.setText(index.data(Qt.DisplayRole) or "")
        editor.selectAll()

    def setModelData(self, editor, model, index):
        model.setData(index, editor.text(), Qt.EditRole)


class EntryListView(QListView):
    """快捷键：Enter 编辑、Delete 删除、Esc 清空搜索、双击编辑、Esc 取消（编辑器默认）。"""

    delete_requested = Signal()
    clear_search_requested = Signal()
    translate_requested = Signal(str)   # entry_id
    selection_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.setUniformItemSizes(True)  # 虚拟滚动性能关键
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setWordWrap(False)
        self.setMouseTracking(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.setFont(QFont("Consolas", 10))
        self.setItemDelegate(EntryDelegate(self))
        # 点击手动切换选中（多选）；拖拽排序与自定义选择冲突，故禁用
        self.setDragDropMode(QAbstractItemView.NoDragDrop)
        self.setDragEnabled(False)
        self.setAcceptDrops(False)

    def set_drag_enabled(self, enabled: bool) -> None:
        """拖拽排序已禁用（与手动多选冲突），保留接口兼容。"""
        return

    def set_layout(self, layout: str) -> None:
        """split=分栏布局；compact=紧凑布局（英文紧邻中文）。"""
        self.itemDelegate().layout = layout
        self.viewport().update()

    def selectionChanged(self, selected, deselected) -> None:
        super().selectionChanged(selected, deselected)
        self.viewport().update()  # 刷新复选框镜像
        self.selection_changed.emit()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key_Return, Qt.Key_Enter) and self.state() != QAbstractItemView.EditingState:
            idx = self.currentIndex()
            if idx.isValid():
                self.edit(idx)
                return
        if key == Qt.Key_Delete and self.state() != QAbstractItemView.EditingState:
            self.delete_requested.emit()
            return
        if key == Qt.Key_Escape and self.state() != QAbstractItemView.EditingState:
            self.clear_search_requested.emit()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            idx = self.indexAt(event.pos())
            sel = self.selectionModel()
            if not idx.isValid():
                return  # 点击空白处不清空选择
            entry = idx.data(ENTRY_ROLE)
            text = idx.data(Qt.DisplayRole) or ""
            # 1) 点击翻译按钮 → 翻译该条（未翻译走词典+AI；部分翻译走 AI 替换）
            if entry is not None:
                if not entry.translation or is_partial_translation(entry.translation):
                    btn = translate_button_rect(self.visualRect(idx), text,
                                                self.itemDelegate().layout, self.font())
                    if btn.contains(event.pos()):
                        self.translate_requested.emit(entry.id)
                        return
            # 2) 只有点击前面的复选框才切换选中
            cb = checkbox_click_rect(self.visualRect(idx))
            if cb.contains(event.pos()):
                if sel.isSelected(idx):
                    sel.select(idx, QItemSelectionModel.Deselect | QItemSelectionModel.Rows)
                else:
                    sel.select(idx, QItemSelectionModel.Select | QItemSelectionModel.Rows)
                sel.setCurrentIndex(idx, QItemSelectionModel.NoUpdate)
                return
            # 3) 点击英文等其他区域：只设为当前项，不改选择
            sel.setCurrentIndex(idx, QItemSelectionModel.NoUpdate)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        # 禁用按住左键拖动的框选/拖选（快速点击会误选一片），选择只由 mousePressEvent 控制
        if event.buttons() & Qt.LeftButton:
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        # 选择已在 mousePressEvent 处理，这里不交给默认（避免默认释放又改选择）
        if event.button() == Qt.LeftButton:
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        # 双击英文/任意区域直接进入编辑（不依赖基类的 pressedIndex，因为点击逻辑已自绘）
        if event.button() == Qt.LeftButton:
            idx = self.indexAt(event.pos())
            if idx.isValid():
                self.edit(idx)
                return
        super().mouseDoubleClickEvent(event)
