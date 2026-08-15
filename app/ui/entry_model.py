"""条目列表模型（QAbstractListModel）。

- 基于 QListView 的虚拟滚动：10 万行也不会一次性渲染 DOM/控件
- 支持实时过滤：包含（默认，不区分大小写）/ 前缀 / 精确 / 正则
- 复选框是装饰性的，镜像视图的选中状态（用于批量操作）
- 拖拽排序通过自定义 MIME 传递条目 id，重排由撤销命令驱动
"""
from __future__ import annotations

import json
import re

from PySide6.QtCore import QAbstractListModel, QMimeData, QModelIndex, Qt

from app.core.commands import ReorderCommand
from app.core.model import Library, PromptEntry

MIME_ENTRY_IDS = "application/x-promptlib-ids"

MODES = [
    ("contains", "包含"),
    ("prefix", "前缀"),
    ("exact", "精确"),
    ("regex", "正则"),
]


class EntryListModel(QAbstractListModel):
    def __init__(self, library: Library, parent=None):
        super().__init__(parent)
        self.library = library
        self.query = ""
        self.mode = "contains"
        self.visible: list[int] = []  # 可见行 -> library.entries 的下标
        library.structure_changed.connect(self._rebuild)
        library.order_changed.connect(self._on_order_changed)
        library.entry_updated.connect(self._on_entry_updated)
        self._rebuild()

    # ---------- 过滤 ----------

    def _match(self, text: str) -> bool:
        if not self.query:
            return True
        q = self.query
        if self.mode == "prefix":
            return text.casefold().startswith(q.casefold())
        if self.mode == "exact":
            return text.casefold() == q.casefold()
        if self.mode == "regex":
            try:
                return re.search(q, text, re.IGNORECASE) is not None
            except re.error:
                return False
        return q.casefold() in text.casefold()

    def set_filter(self, query: str, mode: str) -> None:
        if query == self.query and mode == self.mode:
            return
        self.query = query
        self.mode = mode
        self._rebuild()

    # ---------- 库信号处理 ----------

    def _rebuild(self) -> None:
        self.beginResetModel()
        self.visible = [i for i, e in enumerate(self.library.entries) if self._match(e.text)]
        self.endResetModel()

    def _on_order_changed(self) -> None:
        old = {}
        for row, li in enumerate(self.visible):
            old[self.library.entries[li].id] = self.index(row, 0)
        new_visible = [i for i, e in enumerate(self.library.entries) if self._match(e.text)]
        self.layoutAboutToBeChanged.emit()
        self.visible = new_visible
        row_of = {self.library.entries[i].id: r for r, i in enumerate(new_visible)}
        for eid, idx in old.items():
            new_row = row_of.get(eid)
            if new_row is not None:
                self.changePersistentIndex(idx, self.index(new_row, 0))
        self.layoutChanged.emit()

    def _on_entry_updated(self, entry_id: str) -> None:
        for row, li in enumerate(self.visible):
            if self.library.entries[li].id == entry_id:
                self.dataChanged.emit(self.index(row, 0), self.index(row, 0))
                return

    # ---------- 模型接口 ----------

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.visible)

    def entry_at(self, row: int) -> PromptEntry:
        return self.library.entries[self.visible[row]]

    def visible_texts(self) -> list[str]:
        return [self.library.entries[i].text for i in self.visible]

    def index_of_entry(self, entry_id: str) -> int:
        for row, li in enumerate(self.visible):
            if self.library.entries[li].id == entry_id:
                return row
        return -1

    def data(self, index: QModelIndex, role: int):
        if not index.isValid():
            return None
        entry = self.entry_at(index.row())
        if role == Qt.DisplayRole:
            return entry.text
        if role == Qt.ToolTipRole:
            return entry.text
        return None

    def setData(self, index: QModelIndex, value, role: int = Qt.EditRole) -> bool:
        if role == Qt.EditRole and index.isValid():
            entry = self.entry_at(index.row())
            new_text = str(value).strip()
            if new_text == entry.text:
                return True
            if new_text:
                from app.core.commands import EditEntryCommand

                self.library.undo_stack.push(
                    EditEntryCommand(self.library, entry.id, entry.text, new_text)
                )
            else:  # 提交空文本 = 删除该条目（可撤销）
                from app.core.commands import RemoveEntriesCommand

                self.library.undo_stack.push(RemoveEntriesCommand(self.library, [entry], "删除空条目"))
            return True
        return False

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        if not index.isValid():
            return Qt.ItemIsDropEnabled | Qt.ItemIsEnabled
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsDragEnabled

    # ---------- 拖拽排序 ----------

    def mimeTypes(self) -> list[str]:
        return [MIME_ENTRY_IDS]

    def mimeData(self, indexes) -> QMimeData:
        ids = [self.entry_at(i.row()).id for i in indexes if i.isValid()]
        md = QMimeData()
        md.setData(MIME_ENTRY_IDS, json.dumps(ids).encode("utf-8"))
        return md

    def supportedDropActions(self) -> Qt.DropActions:
        return Qt.MoveAction

    def canDropMimeData(self, data: QMimeData, action, row, column, parent) -> bool:
        return data.hasFormat(MIME_ENTRY_IDS)

    def dropMimeData(self, data: QMimeData, action, row, column, parent) -> bool:
        if action == Qt.IgnoreAction:
            return True
        if not data.hasFormat(MIME_ENTRY_IDS):
            return False
        try:
            ids = json.loads(bytes(data.data(MIME_ENTRY_IDS)).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return False
        if not ids:
            return False
        if parent.isValid():
            target = parent.row()
        elif row == -1:
            target = len(self.visible)
        else:
            target = row
        before = self.library.order_ids()
        id_set = set(ids)
        remaining = [i for i in before if i not in id_set]
        target = max(0, min(target, len(remaining)))
        after = remaining[:target] + ids + remaining[target:]
        if after == before:
            return True
        self.library.undo_stack.push(ReorderCommand(self.library, before, after, "拖动排序"))
        return True
