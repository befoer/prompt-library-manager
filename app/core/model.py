"""核心数据模型：词库 Library 与条目 PromptEntry。

设计要点：
- 一个 TXT 对应一个 Library，一个 Library 包含多个 Entry。
- 每个 Entry 是"一整行文本"，绝不把行内逗号拆开。
- 内部可带 translation（中文翻译，Phase 3 使用），但导出 TXT 时只输出 text。
- 排序/撤销等操作都以"整行"为单位。
- 未保存标记基于"内容指纹"：撤销回已保存状态时自动清除，且能正确处理
  "撤销后又输入不同内容"的情况。
"""
from __future__ import annotations

import json
import os
import random
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoStack

from . import io


class PromptEntry:
    __slots__ = ("id", "text", "translation", "translation_dirty")

    def __init__(self, text: str, translation: str = ""):
        self.id = uuid.uuid4().hex
        self.text = text
        self.translation = translation
        self.translation_dirty = False  # 原文修改后翻译需更新（Phase 3 展示）


def _pinyin_key(s: str) -> tuple:
    """拼音排序键：按音节元组比较（xigua 应排在 xiangjiao 前）。"""
    try:
        from pypinyin import lazy_pinyin

        return tuple(x.casefold() for x in lazy_pinyin(s))
    except Exception:
        return (s.casefold(),)


class Library(QObject):
    """一个 TXT 词库：内存条目列表 + 未保存标记 + 原始顺序快照 + 撤销栈。"""

    structure_changed = Signal()   # 增删/导入/重载（行数变化，需要整体重建）
    order_changed = Signal()       # 仅顺序变化（排序 / 拖拽）
    entry_updated = Signal(str)    # 单条修改（参数为 entry id）
    translations_changed = Signal()  # 翻译字段变化（触发旁车文件自动保存）
    dirty_changed = Signal(bool)
    meta_changed = Signal()        # 统计信息变化

    def __init__(self, parent=None):
        super().__init__(parent)
        self.path: Path | None = None
        self.encoding: str = "utf-8"
        self.entries: list[PromptEntry] = []
        self.original_ids: list[str] = []  # 加载/保存时的顺序快照，用于恢复"原始顺序"
        self._dirty = False
        self._saved_fp: int | None = None  # 上次加载/保存时的内容指纹
        self._fp_cache = 0
        self._fp_valid = False
        self._sidecar_dirty = False  # 翻译旁车文件是否有未写入的修改
        self.undo_stack = QUndoStack(self)
        self.undo_stack.indexChanged.connect(self._refresh_dirty)

    # ---------- 打开 / 保存 ----------

    @classmethod
    def open(cls, path: Path, parent=None) -> "Library":
        lib = cls(parent)
        lib.load(path)
        return lib

    def load(self, path: Path) -> None:
        lines, enc = io.read_lines(path)
        self.path = path
        self.encoding = enc
        self.entries = [PromptEntry(t) for t in lines]
        self.load_sidecar()
        self.original_ids = [e.id for e in self.entries]
        self._invalidate_fp()
        self._saved_fp = self._fingerprint()
        self._dirty = False
        self.undo_stack.clear()
        self.dirty_changed.emit(False)
        self.structure_changed.emit()
        self.meta_changed.emit()

    def reload(self) -> None:
        if self.path:
            self.load(self.path)

    def save(self) -> bool:
        """导出 TXT：只写 text 字段，UTF-8，原子写入。"""
        if not self.path:
            return False
        io.write_text_atomic(self.path, [e.text for e in self.entries], encoding="utf-8")
        self.original_ids = [e.id for e in self.entries]
        self._saved_fp = self._fingerprint()
        self._refresh_dirty()
        self.meta_changed.emit()
        return True

    # ---------- 状态 ----------

    @property
    def dirty(self) -> bool:
        return self._dirty

    def name(self) -> str:
        return self.path.name if self.path else "未命名"

    def get(self, entry_id: str) -> PromptEntry | None:
        for e in self.entries:
            if e.id == entry_id:
                return e
        return None

    # ---------- 未保存标记 ----------

    def _invalidate_fp(self) -> None:
        self._fp_valid = False

    def _fingerprint(self) -> int:
        """64 位内容指纹（顺序敏感），带缓存：每次操作最多计算一次 O(n)。"""
        if not self._fp_valid:
            h = 0
            for e in self.entries:
                h = ((h * 1000003) ^ hash(e.text)) & 0xFFFFFFFFFFFFFFFF
            self._fp_cache = h
            self._fp_valid = True
        return self._fp_cache

    def _refresh_dirty(self, *_args) -> None:
        val = self._fingerprint() != self._saved_fp
        if val != self._dirty:
            self._dirty = val
            self.dirty_changed.emit(val)

    # ---------- 增删改 ----------

    def add_entries(self, texts: list[str], index: int | None = None) -> list[PromptEntry]:
        new = [PromptEntry(t) for t in texts]
        if new:
            if index is None:
                self.entries.extend(new)
            else:
                self.entries[index:index] = new
            self._invalidate_fp()
            self.structure_changed.emit()
            self.meta_changed.emit()
        return new

    def remove_entries(self, ids: list[str]) -> int:
        id_set = set(ids)
        before = len(self.entries)
        self.entries = [e for e in self.entries if e.id not in id_set]
        removed = before - len(self.entries)
        if removed:
            self._invalidate_fp()
            self.structure_changed.emit()
            self.meta_changed.emit()
        return removed

    def restore_entries(self, placed: list[tuple[int, PromptEntry]]) -> None:
        """撤销删除：按原位置插回。placed = [(index, entry), ...]，index 为删除前位置。"""
        if not placed:
            return
        out: list[PromptEntry] = []
        cur = 0
        for index, entry in sorted(placed, key=lambda p: p[0]):
            out.extend(self.entries[cur:index])
            out.append(entry)
            cur = index
        out.extend(self.entries[cur:])
        self.entries = out
        self._invalidate_fp()
        self.structure_changed.emit()
        self.meta_changed.emit()

    def update_entry(self, entry_id: str, text: str, restore_tdirty: bool | None = None) -> bool:
        """修改原文。restore_tdirty 用于撤销：恢复删除前的翻译过期标记。"""
        for e in self.entries:
            if e.id == entry_id:
                if e.text == text:
                    return False
                if restore_tdirty is None:
                    if e.translation:  # 已有翻译且原文变化 → 标记翻译需更新（不删除旧翻译）
                        e.translation_dirty = True
                else:
                    e.translation_dirty = restore_tdirty
                e.text = text
                self._invalidate_fp()
                self.entry_updated.emit(entry_id)
                self.meta_changed.emit()
                return True
        return False

    # ---------- 翻译 ----------

    def set_translation(self, entry_id: str, chinese: str) -> bool:
        """设置/清除翻译。翻译只作为管理信息，不影响 TXT 导出。"""
        for e in self.entries:
            if e.id == entry_id:
                if e.translation == chinese and not e.translation_dirty:
                    return False
                e.translation = chinese
                e.translation_dirty = False
                self._sidecar_dirty = True
                self.entry_updated.emit(entry_id)
                self.meta_changed.emit()
                self.translations_changed.emit()
                return True
        return False

    def translation_state(self, entry: PromptEntry) -> str:
        """翻译状态：untranslated / translated / stale。"""
        if not entry.translation:
            return "untranslated"
        return "stale" if entry.translation_dirty else "translated"

    # ---------- 翻译旁车文件（<name>.txt.zh.json）----------
    # TXT 保持纯文本；翻译单独存旁车文件，重启后仍可恢复。

    def sidecar_path(self) -> Path | None:
        if not self.path:
            return None
        return self.path.with_name(self.path.name + ".zh.json")

    def load_sidecar(self) -> None:
        p = self.sidecar_path()
        if not p or not p.exists():
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return
        entries = data.get("entries") if isinstance(data, dict) else None
        if not isinstance(entries, dict):
            return
        for e in self.entries:
            if e.text in entries:
                e.translation = entries[e.text]
                e.translation_dirty = False

    def save_sidecar(self) -> None:
        p = self.sidecar_path()
        if p is None:
            return
        data = {
            "version": 1,
            "entries": {e.text: e.translation for e in self.entries if e.translation},
        }
        tmp = p.with_name(p.name + ".tmp")
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, p)
            self._sidecar_dirty = False
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    # ---------- 顺序 / 排序 ----------

    def order_ids(self) -> list[str]:
        return [e.id for e in self.entries]

    def apply_order(self, ids: list[str]) -> None:
        """按 id 列表重排；列表外的条目（理论上不会出现）追加到末尾。"""
        by_id = {e.id: e for e in self.entries}
        id_set = set(ids)
        ordered = [by_id[i] for i in ids if i in by_id]
        rest = [e for e in self.entries if e.id not in id_set]
        if ordered + rest != self.entries:
            self.entries = ordered + rest
            self._invalidate_fp()
            self.order_changed.emit()

    def sorted_ids(self, mode: str) -> list[str]:
        """计算排序后的 id 顺序（不修改状态），供撤销命令使用。"""
        if mode == "original":
            known = set(self.original_ids)
            return list(self.original_ids) + [e.id for e in self.entries if e.id not in known]
        items = list(self.entries)
        if mode == "alpha_asc":
            items.sort(key=lambda e: e.text.casefold())
        elif mode == "alpha_desc":
            items.sort(key=lambda e: e.text.casefold(), reverse=True)
        elif mode == "pinyin":
            items.sort(key=lambda e: _pinyin_key(e.text))
        elif mode == "length":
            items.sort(key=lambda e: (len(e.text), e.text.casefold()))
        elif mode == "random":
            random.shuffle(items)
        return [e.id for e in items]

    def sort_by(self, mode: str) -> None:
        self.apply_order(self.sorted_ids(mode))

    # ---------- 去重 / 统计 ----------

    def duplicate_ids(self) -> list[str]:
        """按整行精确匹配（区分大小写），保留首次出现的条目。"""
        seen: set[str] = set()
        dups: list[str] = []
        for e in self.entries:
            if e.text in seen:
                dups.append(e.id)
            else:
                seen.add(e.text)
        return dups

    def duplicate_count(self) -> int:
        return len(self.duplicate_ids())

    def counts(self) -> dict:
        return {
            "total": len(self.entries),
            "duplicates": self.duplicate_count(),
            "empty": sum(1 for e in self.entries if not e.text),
            "translated": sum(1 for e in self.entries if bool(e.translation)),
            "chars": sum(len(e.text) for e in self.entries),
        }
