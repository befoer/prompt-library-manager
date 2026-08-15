"""撤销/重做命令（QUndoCommand 子类）。

覆盖：新增、删除（单条/批量/去重）、修改、排序、拖拽排序、导入。
所有命令以"整行 Entry"为单位操作，重做/撤销都会恢复精确状态。
"""
from __future__ import annotations

from PySide6.QtGui import QUndoCommand

from .model import Library, PromptEntry


class AddEntriesCommand(QUndoCommand):
    def __init__(self, lib: Library, texts: list[str], index: int | None = None, label: str = "新增条目"):
        super().__init__(label)
        self.lib = lib
        self.texts = list(texts)
        self.index = index
        self.added: list[PromptEntry] | None = None
        self.positions: list[int] = []

    def redo(self) -> None:
        if self.added is None:
            self.added = self.lib.add_entries(self.texts, self.index)
            added_ids = {e.id for e in self.added}
            self.positions = [i for i, e in enumerate(self.lib.entries) if e.id in added_ids]
        else:
            self.lib.restore_entries(list(zip(self.positions, self.added)))

    def undo(self) -> None:
        self.lib.remove_entries([e.id for e in self.added or []])


class RemoveEntriesCommand(QUndoCommand):
    def __init__(self, lib: Library, entries: list[PromptEntry], label: str = "删除条目"):
        super().__init__(label)
        self.lib = lib
        pos = {e.id: i for i, e in enumerate(lib.entries)}
        self.removed = sorted(((pos[e.id], e) for e in entries if e.id in pos), key=lambda p: p[0])

    def redo(self) -> None:
        self.lib.remove_entries([e.id for _, e in self.removed])

    def undo(self) -> None:
        self.lib.restore_entries(self.removed)


class EditEntryCommand(QUndoCommand):
    def __init__(self, lib: Library, entry_id: str, old_text: str, new_text: str):
        super().__init__("修改条目")
        self.lib = lib
        self.entry_id = entry_id
        self.old_text = old_text
        self.new_text = new_text
        entry = lib.get(entry_id)
        self.old_translation_dirty = entry.translation_dirty if entry else False

    def redo(self) -> None:
        self.lib.update_entry(self.entry_id, self.new_text)

    def undo(self) -> None:
        self.lib.update_entry(self.entry_id, self.old_text)
        entry = self.lib.get(self.entry_id)
        if entry:
            entry.translation_dirty = self.old_translation_dirty


class ReorderCommand(QUndoCommand):
    """排序 / 拖拽排序共用：记录操作前后的完整 id 顺序。"""

    def __init__(self, lib: Library, before_ids: list[str], after_ids: list[str], label: str = "调整顺序"):
        super().__init__(label)
        self.lib = lib
        self.before = list(before_ids)
        self.after = list(after_ids)

    def redo(self) -> None:
        self.lib.apply_order(self.after)

    def undo(self) -> None:
        self.lib.apply_order(self.before)


class SetTranslationsCommand(QUndoCommand):
    """批量设置/清除翻译（一次撤销）。changes = [(entry_id, old, new), ...]"""

    def __init__(self, lib: Library, changes: list[tuple[str, str, str]], label: str = "设置翻译"):
        super().__init__(label)
        self.lib = lib
        self.changes = [(eid, old, new) for eid, old, new in changes if old != new]

    def redo(self) -> None:
        for eid, _old, new in self.changes:
            self.lib.set_translation(eid, new)

    def undo(self) -> None:
        for eid, old, _new in self.changes:
            self.lib.set_translation(eid, old)


class BatchReplaceCommand(QUndoCommand):
    """批量替换：整次替换作为一个撤销步骤。
    changes = [(entry_id, old_text, new_text, old_translation_dirty), ...]
    """

    def __init__(self, lib: Library, changes: list[tuple], find: str, repl: str):
        super().__init__(f"批量替换 {len(changes)} 处")
        self.lib = lib
        self.changes = changes
        self.find = find
        self.repl = repl

    def redo(self) -> None:
        for eid, _old, new, _td in self.changes:
            self.lib.update_entry(eid, new)

    def undo(self) -> None:
        for eid, old, _new, td in reversed(self.changes):
            self.lib.update_entry(eid, old, restore_tdirty=td)
