"""条目列表视图 + 自绘 delegate（状态圆点 / 复选框 / 双语双行 / 行内编辑 / 拖拽排序）。"""
from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, QModelIndex, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLineEdit,
    QListView,
    QStyle,
    QStyleOptionButton,
    QStyledItemDelegate,
)

from app.core.model import PromptEntry
from app.ui.entry_model import ENTRY_ROLE

ROW_H = 26          # 单行模式
ROW_H_BI = 40       # 双语双行模式
DOT_X = 6
DOT_SIZE = 8
CHECKBOX_X = 18
TEXT_X = 38

STATE_COLORS = {
    "untranslated": "#5f5f5f",
    "translated": "#4ec9b0",
    "stale": "#d19a66",
}


def checkbox_rect_for_rect(r: QRect) -> QRect:
    size = 14
    return QRect(r.left() + CHECKBOX_X, r.center().y() - size // 2, size, size)


class EntryDelegate(QStyledItemDelegate):
    """绘制：状态圆点 + 复选框（镜像选中）+ 英文文本（+ 中文翻译第二行）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.show_translation = True

    def sizeHint(self, option, index) -> QSize:
        return QSize(0, ROW_H_BI if self.show_translation else ROW_H)

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
        if self.show_translation and entry is not None and entry.translation:
            text_rect = option.rect.adjusted(TEXT_X, 3, -4, 0)
            sub_rect = option.rect.adjusted(TEXT_X, ROW_H_BI // 2 + 1, -4, -2)
            self._draw_line(painter, option, text_rect, text, 10.5,
                            "#ffffff" if selected else "#e8e8e8")
            sub = entry.translation + ("  ⚠ 需更新" if entry.translation_dirty else "")
            self._draw_line(painter, option, sub_rect, sub, 9.5,
                            "#9db4c0" if selected else "#7a8a94", italic=True)
        elif self.show_translation:
            text_rect = option.rect.adjusted(TEXT_X, 3, -4, 0)
            sub_rect = option.rect.adjusted(TEXT_X, ROW_H_BI // 2 + 1, -4, -2)
            self._draw_line(painter, option, text_rect, text, 10.5,
                            "#ffffff" if selected else "#e8e8e8")
            self._draw_line(painter, option, sub_rect, "未翻译", 9.5, "#4a4a4a")
        else:
            text_rect = option.rect.adjusted(TEXT_X, 0, -4, 0)
            self._draw_line(painter, option, text_rect, text, 10.5,
                            "#ffffff" if selected else "#d4d4d4")
        painter.restore()

    @staticmethod
    def _draw_line(painter, option, rect, text, pt, color, italic=False):
        f = QFont(option.font)
        f.setPointSizeF(pt)
        if italic:
            f.setItalic(True)
        painter.setFont(f)
        fm = QFontMetrics(f)
        elided = fm.elidedText(text, Qt.ElideRight, rect.width())
        painter.setPen(QColor(color))
        painter.drawText(rect, Qt.AlignVCenter | Qt.AlignLeft, elided)

    def createEditor(self, parent, option, index):
        ed = QLineEdit(parent)
        ed.setFrame(False)
        ed.setStyleSheet(
            "QLineEdit { background:#3c3c3c; color:#ffffff; "
            "selection-background-color:#094771; padding:2px 4px; border:none; }"
        )
        return ed

    def setEditorData(self, editor, index):
        editor.setText(index.data(Qt.DisplayRole) or "")
        editor.selectAll()

    def setModelData(self, editor, model, index):
        model.setData(index, editor.text(), Qt.EditRole)


class EntryListView(QListView):
    """快捷键：Enter 编辑、Delete 删除、双击编辑、Esc 取消（编辑器默认）。"""

    delete_requested = Signal()

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

    def set_drag_enabled(self, enabled: bool) -> None:
        """有筛选时禁用拖拽排序（避免拖拽与过滤行号冲突）。"""
        if enabled:
            self.setDragEnabled(True)
            self.setDragDropMode(QAbstractItemView.InternalMove)
            self.setDefaultDropAction(Qt.MoveAction)
        else:
            self.setDragEnabled(False)
            self.setDragDropMode(QAbstractItemView.NoDragDrop)

    def set_show_translation(self, show: bool) -> None:
        d = self.itemDelegate()
        if isinstance(d, EntryDelegate) and d.show_translation != show:
            d.show_translation = show
            self.doItemsLayout()
        self.viewport().update()

    def selectionChanged(self, selected, deselected) -> None:
        super().selectionChanged(selected, deselected)
        self.viewport().update()  # 刷新复选框镜像

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
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            idx = self.indexAt(event.pos())
            if idx.isValid():
                cb = checkbox_rect_for_rect(self.visualRect(idx))
                if cb.contains(event.pos()):
                    sel = self.selectionModel()
                    if sel.isSelected(idx):
                        sel.select(idx, QItemSelectionModel.Deselect | QItemSelectionModel.Rows)
                    else:
                        sel.select(idx, QItemSelectionModel.Select | QItemSelectionModel.Rows)
                    return
        super().mousePressEvent(event)
