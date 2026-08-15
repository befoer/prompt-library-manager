"""Phase 1 冒烟测试（无界面模式运行）。

用法：
    python tests/smoke_test.py

覆盖：编码识别、行规范化、库 CRUD、撤销/重做、排序、去重、保存重载、
模型过滤（包含/前缀/精确/正则）、GUI 装配与基本操作。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])

from app.core import io  # noqa: E402
from app.core.commands import (AddEntriesCommand, EditEntryCommand,  # noqa: E402
                               RemoveEntriesCommand, ReorderCommand)
from app.core.model import Library  # noqa: E402
from app.ui.entry_model import EntryListModel  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, cond: bool) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)

        # ---------- 1. 编码识别 / 行规范化 ----------
        print("[1] 编码识别与行规范化")
        (d / "utf8.txt").write_bytes("a\nb\n".encode("utf-8"))
        (d / "bom.txt").write_bytes("a\nb\n".encode("utf-8-sig"))
        (d / "gbk.txt").write_bytes("中文词库\n第二行\n".encode("gbk"))
        (d / "crlf.txt").write_bytes("x\r\ny\r\n".encode("utf-8"))
        (d / "mac.txt").write_bytes("p\rm\r".encode("utf-8"))
        check("utf-8 识别", io.detect_encoding((d / "utf8.txt").read_bytes()) == "utf-8")
        check("BOM 识别", io.detect_encoding((d / "bom.txt").read_bytes()) == "utf-8-sig")
        check("GBK 识别", io.detect_encoding((d / "gbk.txt").read_bytes()) == "gb18030")
        lines, enc = io.read_lines(d / "crlf.txt")
        check("CRLF 规范化", lines == ["x", "y"] and enc == "utf-8")
        lines, _ = io.read_lines(d / "mac.txt")
        check("CR(Mac) 规范化", lines == ["p", "m"])
        check(
            "首尾空格/空行处理",
            io.normalize_lines("  a  \n\n  b\tc  \nd  e\n\n") == ["a", "b\tc", "d  e"],
        )
        check("保留行内空格", io.normalize_lines("Fantasy   Room") == ["Fantasy   Room"])

        # ---------- 2. 库 CRUD + 撤销 ----------
        print("[2] 库 CRUD 与撤销/重做")
        lib = Library.open(d / "utf8.txt")
        check("打开计数", len(lib.entries) == 2)
        lib.undo_stack.push(AddEntriesCommand(lib, ["c", "a"]))
        check("新增", [e.text for e in lib.entries] == ["a", "b", "c", "a"])
        lib.undo_stack.undo()
        check("撤销新增", len(lib.entries) == 2 and not lib.dirty)
        lib.undo_stack.redo()
        check("重做新增", len(lib.entries) == 4 and lib.dirty)

        first = lib.entries[0]
        lib.undo_stack.push(EditEntryCommand(lib, first.id, first.text, "AAA"))
        check("修改", lib.entries[0].text == "AAA")
        lib.undo_stack.undo()
        check("撤销修改", lib.entries[0].text == "a")

        before = lib.order_ids()
        lib.undo_stack.push(ReorderCommand(lib, before, lib.sorted_ids("alpha_asc"), "排序"))
        check("A→Z 排序", [e.text for e in lib.entries] == ["a", "a", "b", "c"])
        lib.undo_stack.push(
            ReorderCommand(lib, lib.order_ids(), lib.sorted_ids("original"), "原始顺序")
        )
        # 原始顺序 = 文件原有条目按原顺序，之后新增的条目（当前相对顺序）追加
        check("恢复原始顺序", [e.text for e in lib.entries] == ["a", "b", "a", "c"])
        lib.undo_stack.undo()  # 撤回到 A→Z
        lib.undo_stack.undo()  # 撤回到未排序
        check("连续撤销排序", [e.text for e in lib.entries] == ["a", "b", "c", "a"])

        lib.undo_stack.push(AddEntriesCommand(lib, ["b", "c"]))
        dups = lib.duplicate_ids()
        check("重复计数", len(dups) == 3)
        dup_set = set(dups)
        dup_entries = [e for e in lib.entries if e.id in dup_set]
        lib.undo_stack.push(RemoveEntriesCommand(lib, dup_entries, "去重"))
        check("去重后", [e.text for e in lib.entries] == ["a", "b", "c"])
        lib.undo_stack.undo()
        check("撤销去重", len(lib.entries) == 6)
        lib.undo_stack.redo()
        check("重做去重", len(lib.entries) == 3)

        lib.save()
        check("保存后未脏", not lib.dirty)
        saved, _ = io.read_lines(d / "utf8.txt")
        check("保存内容仅 text", saved == ["a", "b", "c"])
        lib2 = Library.open(d / "utf8.txt")
        check("重载一致", len(lib2.entries) == 3)

        # ---------- 3. 模型过滤 ----------
        print("[3] 搜索过滤")
        m = EntryListModel(lib2)
        m.set_filter("A", "contains")
        check("包含(不区分大小写)", m.rowCount() == 1)
        m.set_filter("b", "exact")
        check("精确", m.rowCount() == 1)
        m.set_filter("b", "prefix")
        check("前缀", m.rowCount() == 1)
        m.set_filter("^a$", "regex")
        check("正则", m.rowCount() == 1)
        m.set_filter("(", "regex")
        check("正则错误不崩溃", m.rowCount() == 0)
        m.set_filter("", "contains")
        check("清空筛选", m.rowCount() == 3)

        # ---------- 4. GUI 装配 + 基本操作 ----------
        print("[4] GUI 装配与基本操作")
        tmp_txt = d / "libs"
        shutil.copytree(ROOT / "txt", tmp_txt)
        win = MainWindow()
        win.show()
        app.processEvents()
        win.open_folder(tmp_txt, autoload_first=True)
        app.processEvents()
        check("打开词库文件夹", win.library is not None)
        check("侧栏文件数", win.sidebar.list.count() == 3)
        total0 = win.library.counts()["total"]
        check("示例词库非空", total0 > 0)

        win.add_entry()
        app.processEvents()
        check("新增空条目", win.library.entries[-1].text == "")

        # 编辑：直接把模型 setData 当作回车提交
        last_idx = win.model.index(win.model.rowCount() - 1, 0)
        win.model.setData(last_idx, "abandoned fantasy room", Qt.EditRole)
        app.processEvents()
        check("提交编辑", win.library.entries[-1].text == "abandoned fantasy room")
        win.model.setData(last_idx, "   ", Qt.EditRole)
        app.processEvents()
        check("空白提交=删除该条", len(win.library.entries) == total0)

        win.entry_view.selectAll()
        app.processEvents()
        n_sel = len(win.entry_view.selectionModel().selectedIndexes())
        check("Ctrl+A 等效全选", n_sel == win.model.rowCount())
        win.delete_selected(confirm_needed=False)
        app.processEvents()
        check("批量删除", len(win.library.entries) == 0)
        win.library.undo_stack.undo()
        app.processEvents()
        check("撤销批量删除", len(win.library.entries) == total0)

        win.search_edit.setText("room")
        app.processEvents()
        win._apply_filter()
        check("GUI 实时筛选", win.model.rowCount() > 0 and win.model.rowCount() < total0)

        # 外部修改：未保存时自动重载
        libp = win.library
        save_path = libp.path
        io.write_text_atomic(save_path, ["external line"], encoding="utf-8")
        win._handle_external_change()
        app.processEvents()
        check("外部修改自动重载", [e.text for e in libp.entries] == ["external line"])

        win.close()
        app.processEvents()

    print(f"\n结果：{PASS} 通过，{FAIL} 失败")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
