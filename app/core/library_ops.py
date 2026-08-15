"""词库文件级批量操作：跨词库复制/移动、文件级批量替换。"""
from __future__ import annotations

import re
from pathlib import Path

from . import io


def compile_replacer(find: str, repl: str):
    """不区分大小写的查找/替换。返回 (apply(text)->text, count(text)->int)。"""
    if not find or not find.strip():
        raise ValueError("查找内容不能为空")
    pattern = re.compile(re.escape(find), re.IGNORECASE)

    def apply(text: str) -> str:
        return pattern.sub(lambda m: repl, text)

    def count(text: str) -> int:
        return len(pattern.findall(text))

    return apply, count


def append_lines_to_file(path: Path, texts: list[str]) -> int:
    """向目标 TXT 追加条目（读取-规范化-追加-原子写）。返回实际追加条数。"""
    existing, _ = io.read_lines(path)
    clean = [t.strip() for t in texts if t and t.strip()]
    merged = existing + clean
    if len(merged) != len(existing):
        io.write_text_atomic(path, merged, "utf-8")
    return len(merged) - len(existing)


def replace_in_file(path: Path, find: str, repl: str) -> int:
    """对整个 TXT 文件做不区分大小写的批量替换，内容变化才写回。返回匹配总数。"""
    apply, count = compile_replacer(find, repl)
    lines, _ = io.read_lines(path)
    new_lines = [apply(ln) for ln in lines]
    total = sum(count(ln) for ln in lines)
    if total and new_lines != lines:
        io.write_text_atomic(path, new_lines, "utf-8")
    return total


def library_replace_changes(lib, find: str, repl: str) -> list[tuple]:
    """当前词库批量替换：返回 [(entry_id, old, new, old_translation_dirty)]，供撤销命令使用。"""
    apply, _ = compile_replacer(find, repl)
    changes = []
    for e in lib.entries:
        new = apply(e.text)
        if new != e.text:
            changes.append((e.id, e.text, new, e.translation_dirty))
    return changes
