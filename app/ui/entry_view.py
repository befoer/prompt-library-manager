"""条目列表视图 + 自绘 delegate（复选框 / 行内编辑 / 拖拽排序）。"""
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

CHECKBOX_W = 18
TEXT_INDENT = 8


def checkbox_rect_for_rect(r: QRect) -> QRect:
    size = 14
    return QRect(r.left() + 4, r.center().y() - size // 2, size, size)


class EntryDelegate(QStyledItemDelegate):
    """绘制：复选框（镜像选中状态）+ 文本（超长省略）。"""

    def sizeHint(self, option, index) -> QSize:
        return QSize(0, 26)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        painter.save()
        view = self.parent()
        selected = bool(view is not None and view.selectionModel()
                        and view.selectionModel().isSelected(index))
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, QColor("#094771"))
        elif option.state & QStyle.State_MouseOver:
            painter.fillRect(option.rect, QColor("#2a2d2e"))

        cb = QStyleOptionButton()
        cb.rect = checkbox_rect_for_rect(option.rect)
        cb.state = QStyle.State_Enabled | (QStyle.State_On if selected else QStyle.State_Off)
        if view is not None:
            view.style().drawControl(QStyle.CE_CheckBox, cb, painter, view)

        text = index.data(Qt.DisplayRole) or ""
        text_rect = option.rect.adjusted(CHECKBOX_W + TEXT_INDENT, 0, -4, 0)
        painter.setFont(option.font)
        fm = QFontMetrics(option.font)
        elided = fm.elidedText(text, Qt.ElideRight, text_rect.width())
        painter.setPen(QColor("#ffffff") if selected else QColor("#d4d4d4"))
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, elided)
        painter.restore()

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
