"""冒烟测试（无界面模式运行）。

用法：
    python tests/smoke_test.py

覆盖：编码识别、行规范化、库 CRUD、撤销/重做、排序、去重、保存重载、
模型过滤、GUI 装配、外部修改检测、离线词典、翻译命令、旁车文件、
翻译缓存、批量替换、跨词库复制/移动、AI 接口（本地 mock 服务器）、双语显示。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])

from app.core import io, library_ops  # noqa: E402
from app.core.ai_translate import (AIConfig, TranslateWorker,  # noqa: E402
                                   TranslationCache, translate_openai_batch)
from app.core.commands import (AddEntriesCommand,  # noqa: E402
                               BatchReplaceCommand, EditEntryCommand,
                               RemoveEntriesCommand, ReorderCommand,
                               SetTranslationsCommand)
from app.core.dictionary import OfflineDictionary  # noqa: E402
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


class _MockHandler(BaseHTTPRequestHandler):
    """模拟 OpenAI 兼容 /chat/completions。"""

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        if body.get("model") == "boom":
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"server error")
            return
        user = body["messages"][-1]["content"]
        texts = [t for t in user.split("\n\n") if t]
        content = "\n\n".join(t + " 的翻译" for t in texts)
        resp = json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)

    def log_message(self, *args):
        pass


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

        # ---------- 4. 离线词典 ----------
        print("[4] 离线词典（zh-CN.txt + 别名表）")
        tags = d / "Tags"
        tags.mkdir()
        (tags / "zh-CN.txt").write_text(
            "1girl=1个女性\nlong hair=长发\nlooking at viewer=看向阅图者\ncherry blossoms=樱花\n",
            encoding="utf-8",
        )
        (tags / "danbooru.csv").write_text(
            '1girl,0,1,"1girls,sole_female"\n', encoding="utf-8"
        )
        dic = OfflineDictionary([tags])
        dic.load()
        check("词典加载", dic.zh_count == 4 and dic.alias_count == 2)
        check("词典整行", dic.lookup("looking at viewer") == "看向阅图者")
        check("别名归一化", dic.lookup("1girls") == "1个女性")
        check("大小写不敏感", dic.lookup("Long Hair") == "长发")
        check("下划线转空格", dic.lookup("long_hair") == "长发")
        check("多tag部分翻译",
              dic.translate_entry("cherry blossoms, unknown_xyz") == "樱花, unknown_xyz")
        check("多tag全命中",
              dic.translate_entry("cherry blossoms, looking at viewer") == "樱花, 看向阅图者")
        check("整行命中优先", dic.translate_entry("looking at viewer") == "看向阅图者")
        check("无命中返回 None", dic.translate_entry("totally unknown") is None)

        # ---------- 5. 翻译命令 / 旁车 / 批量替换 / 复制移动 ----------
        print("[5] 翻译命令与文件级批量操作")
        e0 = lib2.entries[0]
        lib2.undo_stack.push(SetTranslationsCommand(lib2, [(e0.id, "", "翻译一")], "设置翻译"))
        check("设置翻译", e0.translation == "翻译一")
        check("翻译状态", lib2.translation_state(e0) == "translated")
        lib2.undo_stack.undo()
        check("撤销翻译", e0.translation == "")

        # 原文修改 → 翻译过期标记（不删除旧翻译）
        lib2.undo_stack.push(SetTranslationsCommand(lib2, [(e0.id, "", "旧翻译")], "设置翻译"))
        lib2.undo_stack.push(EditEntryCommand(lib2, e0.id, e0.text, "changed text"))
        check("原文修改标记过期", e0.translation == "旧翻译" and e0.translation_dirty)
        check("状态=需更新", lib2.translation_state(e0) == "stale")
        lib2.undo_stack.undo()  # 撤销修改
        check("撤销修改恢复状态", lib2.translation_state(e0) == "translated")

        # 旁车文件：翻译不写入 TXT，重启后可恢复
        lib2.save()
        check("TXT 不含翻译", io.read_lines(d / "utf8.txt")[0] == ["a", "b", "c"])
        lib2.save_sidecar()
        check("旁车文件存在", (d / "utf8.txt.zh.json").exists())
        lib3 = Library.open(d / "utf8.txt")
        e0b = lib3.entries[0]
        check("旁车恢复翻译", e0b.translation == "旧翻译")

        # 批量替换（当前库，可撤销）
        lib3.undo_stack.push(
            BatchReplaceCommand(lib3, library_ops.library_replace_changes(lib3, "a", "X"), "a", "X")
        )
        check("批量替换", [e.text for e in lib3.entries] == ["X", "b", "c"])
        lib3.undo_stack.undo()
        check("撤销批量替换", [e.text for e in lib3.entries] == ["a", "b", "c"])

        # 跨词库复制/移动（文件级）
        t2 = d / "t2.txt"
        t2.write_text("x\ny\n", encoding="utf-8")
        n = library_ops.append_lines_to_file(t2, ["a", "a", "  b  "])
        check("追加到目标词库", n == 3 and io.read_lines(t2)[0] == ["x", "y", "a", "a", "b"])
        n2 = library_ops.replace_in_file(t2, "a", "Q")
        check("文件级批量替换", n2 == 2 and io.read_lines(t2)[0] == ["x", "y", "Q", "Q", "b"])
        check("不区分大小写文件替换", library_ops.replace_in_file(t2, "q", "R") == 2)

        # ---------- 6. AI 接口（本地 mock 服务器）----------
        print("[6] AI 翻译接口与缓存")
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = server.server_address[1]
        base = f"http://127.0.0.1:{port}/v1"

        cfg = AIConfig(enabled=True, base_url=base, api_key="k", model="m")
        out = translate_openai_batch(["hello", "fantasy room"], cfg)
        check("OpenAI 批量接口", out == ["hello 的翻译", "fantasy room 的翻译"])

        cache = TranslationCache(d / "cache.json")
        got: dict = {}

        def on_finish(r, e):
            got.update(r)

        w1 = TranslateWorker(["hello", "novel tag"], cfg, cache=cache, dictionary=None)
        w1.finished.connect(on_finish)
        w1.run()
        check("Worker 批量翻译", got.get("hello") == "hello 的翻译")
        check("Worker 缓存写入", cache.get("hello") == "hello 的翻译")

        # 第二次：缓存命中，即使接口 500 也应成功
        bad = AIConfig(enabled=True, base_url=base, api_key="k", model="boom")
        got2: dict = {}
        w2 = TranslateWorker(["hello"], bad, cache=cache, dictionary=None)
        w2.finished.connect(lambda r, e: got2.update(r))
        w2.run()
        check("缓存命中不调接口", got2.get("hello") == "hello 的翻译")

        # 词典兜底：AI 之前先查词典
        got3: dict = {}
        w3 = TranslateWorker(["looking at viewer", "hello"], cfg, cache=cache, dictionary=dic)
        w3.finished.connect(lambda r, e: got3.update(r))
        w3.run()
        check("词典优先于 AI", got3.get("looking at viewer") == "看向阅图者")
        check("未命中进 AI", got3.get("hello") == "hello 的翻译")

        # 错误处理
        w4 = TranslateWorker(["doomed"], bad, cache=None, dictionary=None)
        errs: list = []
        w4.finished.connect(lambda r, e: errs.extend(e))
        w4.run()
        check("接口失败记录错误", len(errs) == 1)
        server.shutdown()

        # ---------- 7. GUI：双语显示 + 离线翻译 + 状态 ----------
        print("[7] GUI 双语与翻译流程")
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

        # 双语显示切换
        win.entry_view.set_show_translation(False)
        check("单行模式行高", win.entry_view.sizeHintForRow(0) <= 30)
        win.entry_view.set_show_translation(True)
        check("双行模式行高", win.entry_view.sizeHintForRow(0) >= 36)

        # 离线词典翻译（真实 Tags 词典已由 MainWindow 加载）
        win.search_edit.clear()
        app.processEvents()
        win._apply_filter()
        win.entry_view.selectAll()
        win._offline_translate(win.selected_texts())
        app.processEvents()
        check("离线翻译命中", win.library.counts()["translated"] > 0)

        # 翻译状态圆点逻辑：修改已翻译条目 → 需更新
        tr = next((e for e in win.library.entries if e.translation), None)
        if tr is not None:
            row = win.model.index_of_entry(tr.id)
            win.model.setData(win.model.index(row, 0), tr.text + " X", Qt.EditRole)
            app.processEvents()
            check("原文修改后翻译标记过期", win.library.translation_state(tr) == "stale")

        # 外部修改：先保存（清掉脏标记），再检测外部写入 → 自动重载
        win.save_library()
        libp = win.library
        save_path = libp.path
        io.write_text_atomic(save_path, ["external line"], encoding="utf-8")
        win._handle_external_change()
        app.processEvents()
        check("外部修改自动重载", [e.text for e in libp.entries] == ["external line"])

        win.close()
        app.processEvents()

        # ---------- 8. Phase 4：CSV / 合并 / Tag 统计 / 差异 ----------
        print("[8] Phase 4：CSV / 合并 / Tag 统计 / 差异")
        from app.core import csv_ops  # noqa: E402
        from app.core.commands import ImportCsvCommand  # noqa: E402
        from app.core.library_ops import merge_lines  # noqa: E402
        from app.ui.phase4_dialogs import compute_diff, compute_tag_stats  # noqa: E402

        csvp = d / "pairs.csv"
        csv_ops.write_translation_csv(csvp, [("a", "甲"), ("b", "乙"), ("新词", "新义")])
        pairs = csv_ops.read_translation_csv(csvp)
        check("CSV 往返", pairs == [("a", "甲"), ("b", "乙"), ("新词", "新义")])

        lib4 = Library.open(d / "utf8.txt")  # a, b, c
        lib4.undo_stack.push(ImportCsvCommand(lib4, pairs))
        check("CSV 导入更新翻译", lib4.find_by_text("a").translation == "甲")
        check("CSV 导入追加条目",
              len(lib4.entries) == 4 and lib4.entries[-1].text == "新词")
        check("CSV 新条目带翻译", lib4.entries[-1].translation == "新义")
        lib4.undo_stack.undo()
        # 撤销后恢复导入前的状态（此前旁车文件已为 a 恢复过"旧翻译"）
        check("撤销 CSV 导入",
              len(lib4.entries) == 3 and lib4.find_by_text("a").translation == "旧翻译")

        check("合并去重", merge_lines([["x", "y"], ["y", "z"]], dedupe=True) == ["x", "y", "z"])
        check("合并不去重", merge_lines([["x", "y"], ["y", "z"]], dedupe=False) == ["x", "y", "y", "z"])

        lib5 = Library.open(d / "utf8.txt")  # a, b, c
        lib5.undo_stack.push(
            AddEntriesCommand(lib5, ["fantasy room, messy room", "fantasy room"])
        )
        stats = dict(compute_tag_stats(lib5))
        check("Tag 统计", stats.get("fantasy room") == 2 and stats.get("messy room") == 1)

        added, removed, diff_lines = compute_diff(["a", "b", "c"], ["a", "x", "c", "d"])
        check("差异统计", added == 2 and removed == 1)
        check("差异行",
              any(ln.startswith("+ x") for ln in diff_lines)
              and any(ln.startswith("- b") for ln in diff_lines))

        big_old = [f"line{i}" for i in range(60000)]
        big_new = [f"line{i}" for i in range(1, 60001)]
        a2, r2, dl2 = compute_diff(big_old, big_new)
        check("大库集合统计", a2 == 1 and r2 == 1 and dl2 == [])

        print("\n结果：%d 通过，%d 失败" % (PASS, FAIL))
        return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
