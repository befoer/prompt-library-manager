"""主窗口：布局、菜单、快捷键、文件夹模式、外部修改检测、拖拽打开。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.core import io
from app.core.commands import AddEntriesCommand, RemoveEntriesCommand, ReorderCommand
from app.core.model import Library
from app.ui.dialogs import DiffDialog, RandomBatchDialog, RandomPickDialog, confirm
from app.ui.entry_model import EntryListModel, MODES
from app.ui.entry_view import EntryListView
from app.ui.sidebar import SidebarPanel

SORT_MODES = [
    ("original", "原始顺序"),
    ("alpha_asc", "A → Z"),
    ("alpha_desc", "Z → A"),
    ("pinyin", "中文拼音"),
    ("length", "长度（短 → 长）"),
    ("random", "随机排序"),
]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Prompt Library Manager")
        self.setMinimumSize(960, 600)
        self.resize(1280, 800)
        self.setAcceptDrops(True)

        self.library: Library | None = None
        self._bound_lib: Library | None = None
        self.model: EntryListModel | None = None
        self.current_folder: Path | None = None
        self._saving = False

        self.settings = QSettings("PromptLib", "PromptLibraryManager")

        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_watch_event)
        self._watcher.directoryChanged.connect(self._on_watch_event)
        self._change_timer = QTimer(self)
        self._change_timer.setSingleShot(True)
        self._change_timer.setInterval(400)
        self._change_timer.timeout.connect(self._handle_external_change)

        self._build_ui()
        self._build_actions()
        self._restore_settings()

        last = self.settings.value("last_folder", "")
        if last and Path(last).is_dir():
            self.open_folder(Path(last), autoload_first=True)

    # ================= UI =================

    def _build_ui(self) -> None:
        self.sidebar = SidebarPanel(self)

        # ---- 右侧：搜索/工具栏 + 列表 + 统计 ----
        right = QWidget(self)
        rlay = QVBoxLayout(right)
        rlay.setContentsMargins(8, 8, 8, 8)
        rlay.setSpacing(6)

        row1 = QHBoxLayout()
        row1.setSpacing(6)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索（不区分大小写，Ctrl+F 聚焦）…")
        self.search_edit.setClearButtonEnabled(True)
        self.mode_combo = QComboBox()
        for _key, label in MODES:
            self.mode_combo.addItem(label)
        self.btn_random = QToolButton(text="🎲 随机")
        self.btn_random.setToolTip("随机抽取一条（Ctrl+R）")
        self.btn_new_entry = QToolButton(text="新增")
        self.btn_new_entry.setToolTip("在列表底部新增条目（Ctrl+N）")
        row1.addWidget(self.search_edit, 1)
        row1.addWidget(self.mode_combo)
        row1.addWidget(self.btn_random)
        row1.addWidget(self.btn_new_entry)
        rlay.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(6)
        self.btn_save = QToolButton(text="保存")
        self.btn_save.setToolTip("保存到 TXT（Ctrl+S）")
        self.btn_import = QToolButton(text="导入")
        self.btn_export = QToolButton(text="导出")
        self.btn_dedupe = QToolButton(text="去重")
        self.btn_sort = QToolButton(text="排序 ▾")
        self.btn_sort.setPopupMode(QToolButton.InstantPopup)
        self.btn_delete = QToolButton(text="删除选中")
        row2.addWidget(self.btn_save)
        row2.addWidget(self.btn_import)
        row2.addWidget(self.btn_export)
        row2.addWidget(self.btn_dedupe)
        row2.addWidget(self.btn_sort)
        row2.addStretch(1)
        row2.addWidget(self.btn_delete)
        rlay.addLayout(row2)

        self.entry_view = EntryListView()
        rlay.addWidget(self.entry_view, 1)

        self.stats_label = QLabel("未打开词库")
        self.stats_label.setObjectName("statsLabel")
        rlay.addWidget(self.stats_label)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([240, 1040])
        self.setCentralWidget(self.splitter)

        # 状态栏
        self.status_dirty = QLabel("")
        self.status_encoding = QLabel("")
        self.statusBar().addPermanentWidget(self.status_encoding)
        self.statusBar().addPermanentWidget(self.status_dirty)

        # 信号
        self.search_edit.textChanged.connect(self._on_search_debounce)
        self.mode_combo.currentIndexChanged.connect(self._apply_filter)
        self.btn_random.clicked.connect(self.random_pick)
        self.btn_new_entry.clicked.connect(self.add_entry)
        self.btn_save.clicked.connect(self.save_library)
        self.btn_import.clicked.connect(self.import_txt)
        self.btn_export.clicked.connect(self.export_txt)
        self.btn_dedupe.clicked.connect(self.dedupe)
        self.btn_delete.clicked.connect(self.delete_selected)
        self.entry_view.delete_requested.connect(self.delete_selected)
        self.entry_view.customContextMenuRequested.connect(self._entry_context_menu)

        self.sidebar.open_folder_requested.connect(self._choose_folder)
        self.sidebar.new_library_requested.connect(self.new_library)
        self.sidebar.refresh_requested.connect(self.sidebar.refresh)
        self.sidebar.open_requested.connect(lambda p: self.open_file(Path(p)))
        self.sidebar.rename_requested.connect(self.rename_library)
        self.sidebar.delete_requested.connect(self.delete_library)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(120)
        self._search_timer.timeout.connect(self._apply_filter)

    def _build_actions(self) -> None:
        mb = self.menuBar()
        m_file = mb.addMenu("文件(&F)")
        m_edit = mb.addMenu("编辑(&E)")
        m_tool = mb.addMenu("工具(&T)")
        m_help = mb.addMenu("帮助(&H)")

        def act(parent, text, shortcut, handler):
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            a.triggered.connect(handler)
            parent.addAction(a)
            return a

        act(m_file, "打开词库文件夹…", "Ctrl+Shift+O", self._choose_folder)
        act(m_file, "打开 TXT…", "Ctrl+O", self.open_file_dialog)
        act(m_file, "导入 TXT…", "Ctrl+I", self.import_txt)
        act(m_file, "导出 TXT…", "Ctrl+E", self.export_txt)
        m_file.addSeparator()
        act(m_file, "退出", "Ctrl+Q", self.close)

        act(m_edit, "新增条目", "Ctrl+N", self.add_entry)
        act(m_edit, "删除选中", None, self.delete_selected)
        act(m_edit, "去重", None, self.dedupe)
        self.act_undo = act(m_edit, "撤销", "Ctrl+Z", self._undo)
        self.act_redo = act(m_edit, "重做", "Ctrl+Shift+Z", self._redo)
        self.act_undo.setEnabled(False)
        self.act_redo.setEnabled(False)

        sort_menu = QMenu("排序", self)
        for mode, label in SORT_MODES:
            sort_menu.addAction(label, lambda _=False, m=mode: self.sort_library(m))
        m_edit.addMenu(sort_menu)
        self.btn_sort.setMenu(sort_menu)

        act(m_tool, "随机抽取 1 条", "Ctrl+R", self.random_pick)
        act(m_tool, "随机抽取多条…", None, self.random_pick_batch)
        act(m_help, "关于", "F1", self._about)

        # Ctrl+F 聚焦搜索框
        self.act_focus_search = QAction(self)
        self.act_focus_search.setShortcut(QKeySequence("Ctrl+F"))
        self.act_focus_search.triggered.connect(self._focus_search)
        self.addAction(self.act_focus_search)

    # ================= 库切换 =================

    def _bind_library(self, lib: Library) -> None:
        self._bound_lib = lib
        self.library = lib
        self.model = EntryListModel(lib, self)
        self.entry_view.setModel(self.model)
        self.entry_view.set_drag_enabled(not self.model.query)
        lib.undo_stack.canUndoChanged.connect(self.act_undo.setEnabled)
        lib.undo_stack.canRedoChanged.connect(self.act_redo.setEnabled)
        lib.dirty_changed.connect(self._on_dirty_changed)
        lib.meta_changed.connect(self._update_stats)
        self.act_undo.setEnabled(lib.undo_stack.canUndo())
        self.act_redo.setEnabled(lib.undo_stack.canRedo())
        self._update_title()
        self._update_stats()

    def _unbind_library(self) -> None:
        lib = self._bound_lib
        if lib is None:
            return
        for sig, slot in (
            (lib.undo_stack.canUndoChanged, self.act_undo.setEnabled),
            (lib.undo_stack.canRedoChanged, self.act_redo.setEnabled),
            (lib.dirty_changed, self._on_dirty_changed),
            (lib.meta_changed, self._update_stats),
        ):
            try:
                sig.disconnect(slot)
            except RuntimeError:
                pass
        if self.model is not None:
            self.model.deleteLater()
            self.model = None
        self._bound_lib = None

    def _set_library(self, lib: Library | None) -> None:
        self._unbind_library()
        if self.library is not None and self.library is not lib:
            self.library.deleteLater()
        self.library = lib
        if lib is None:
            self.entry_view.setModel(None)
            self._update_title()
            self._update_stats()
            return
        self._bind_library(lib)

    # ================= 打开 / 保存 =================

    def open_folder(self, folder: Path, autoload_first: bool = False) -> None:
        if not self._guard_unsaved():
            return
        folder = folder.resolve()
        self.current_folder = folder
        self.settings.setValue("last_folder", str(folder))
        self.sidebar.set_folder(folder)
        self._set_folder_watch()
        if autoload_first or (self.library is None and self.sidebar.first_path()):
            first = self.sidebar.first_path()
            if first:
                self.open_file(Path(first))
                return
        self._set_library(None)
        self.statusBar().showMessage(f"词库文件夹：{folder}", 3000)

    def open_file(self, path: Path) -> None:
        if not self._guard_unsaved():
            return
        path = path.resolve()
        folder = path.parent
        if self.current_folder != folder:
            self.current_folder = folder
            self.settings.setValue("last_folder", str(folder))
            self.sidebar.set_folder(folder)
            self._set_folder_watch()
        try:
            lib = Library.open(path, parent=self)
        except OSError as e:
            QMessageBox.critical(self, "打开失败", f"无法读取 {path.name}：\n{e}")
            return
        self._set_library(lib)
        self._watch_library_file()
        self.search_edit.clear()
        self.mode_combo.setCurrentIndex(0)
        self.sidebar.select_path(path)
        self.statusBar().showMessage(f"已打开 {path.name}（{lib.encoding}）", 3000)

    def open_file_dialog(self) -> None:
        start = str(self.current_folder) if self.current_folder else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self, "打开 TXT", start, "文本文件 (*.txt);;所有文件 (*)"
        )
        if path:
            self.open_file(Path(path))

    def save_library(self) -> None:
        if self.library is None or self.library.path is None:
            QMessageBox.information(self, "提示", "请先打开一个词库。")
            return
        self._saving = True
        try:
            ok = self.library.save()
        finally:
            self._saving = False
        self._watch_library_file()
        self._update_title()
        self._update_stats()
        if ok:
            self.statusBar().showMessage("已保存", 2000)

    # ================= 增删改 =================

    def add_entry(self) -> None:
        if self.library is None:
            QMessageBox.information(self, "提示", "请先打开一个词库。")
            return
        self.search_edit.clear()  # 清空筛选，保证新条目可见
        cmd = AddEntriesCommand(self.library, [""])
        self.library.undo_stack.push(cmd)
        entry = cmd.added[0] if cmd.added else None
        if entry is None:
            return
        row = self.model.index_of_entry(entry.id) if self.model else -1
        if row >= 0:
            idx = self.model.index(row, 0)
            self.entry_view.scrollTo(idx)
            self.entry_view.setCurrentIndex(idx)
            self.entry_view.edit(idx)
        self.statusBar().showMessage("已新增空条目，直接输入后按 Enter 保存（Esc 取消）", 3000)

    def delete_selected(self, confirm_needed: bool | None = None) -> None:
        if self.library is None or self.model is None:
            return
        rows = sorted({i.row() for i in self.entry_view.selectionModel().selectedIndexes()})
        if not rows:
            return
        entries = [self.model.entry_at(r) for r in rows]
        n = len(entries)
        if n >= 2 and confirm_needed is not False:
            if not confirm(self, "批量删除", f"确定删除选中的 {n} 条条目？\n删除后可用 Ctrl+Z 撤销。"):
                return
        self.library.undo_stack.push(RemoveEntriesCommand(self.library, entries))
        self.statusBar().showMessage(f"已删除 {n} 条（Ctrl+Z 可撤销）", 3000)

    def dedupe(self) -> None:
        if self.library is None:
            QMessageBox.information(self, "提示", "请先打开一个词库。")
            return
        dups = self.library.duplicate_ids()
        if not dups:
            QMessageBox.information(self, "去重", "没有重复项。")
            return
        id_set = set(dups)
        entries = [e for e in self.library.entries if e.id in id_set]
        if not confirm(
            self,
            "去重",
            f"发现 {len(dups)} 个重复项（按整行精确匹配，保留首次出现）。\n确定删除？",
        ):
            return
        self.library.undo_stack.push(RemoveEntriesCommand(self.library, entries, "去重"))
        self.statusBar().showMessage(f"已删除 {len(dups)} 个重复项（Ctrl+Z 可撤销）", 3000)

    def sort_library(self, mode: str) -> None:
        if self.library is None:
            return
        label = dict(SORT_MODES).get(mode, "排序")
        before = self.library.order_ids()
        after = self.library.sorted_ids(mode)
        if after == before:
            return
        self.library.undo_stack.push(ReorderCommand(self.library, before, after, f"排序：{label}"))

    # ================= 导入 / 导出 =================

    def import_txt(self) -> None:
        if self.library is None:
            QMessageBox.information(self, "提示", "请先打开一个词库。")
            return
        start = str(self.current_folder) if self.current_folder else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self, "导入 TXT", start, "文本文件 (*.txt);;CSV (*.csv);;所有文件 (*)"
        )
        if not path:
            return
        if path.lower().endswith(".csv"):
            QMessageBox.information(
                self, "提示", "CSV 导入将在后续阶段（Phase 4）提供，请先选择 TXT 文件。"
            )
            return
        try:
            lines, enc = io.read_lines(Path(path))
        except OSError as e:
            QMessageBox.critical(self, "导入失败", str(e))
            return
        if not lines:
            QMessageBox.information(self, "导入", "该文件没有可导入的内容（空行会被忽略）。")
            return
        if not confirm(
            self,
            "导入 TXT",
            f"将向当前词库「{self.library.name()}」追加 {len(lines)} 条。\n"
            f"（编码：{enc}；已自动清理首尾空格与空行）",
        ):
            return
        self.library.undo_stack.push(AddEntriesCommand(self.library, lines, None, "导入 TXT"))
        self.statusBar().showMessage(f"已导入 {len(lines)} 条（Ctrl+Z 可撤销）", 3000)

    def export_txt(self) -> None:
        if self.library is None:
            QMessageBox.information(self, "提示", "请先打开一个词库。")
            return
        default = self.library.path.name if self.library.path else "export.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 TXT", str(Path(default)), "文本文件 (*.txt)"
        )
        if not path:
            return
        try:
            io.write_text_atomic(Path(path), [e.text for e in self.library.entries], encoding="utf-8")
        except OSError as e:
            QMessageBox.critical(self, "导出失败", str(e))
            return
        n = len(self.library.entries)
        self.statusBar().showMessage(f"已导出 {n} 条 → {path}", 4000)

    # ================= 词库文件管理 =================

    def _choose_folder(self) -> None:
        start = str(self.current_folder) if self.current_folder else str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "打开词库文件夹", start)
        if folder:
            self.open_folder(Path(folder), autoload_first=True)

    def new_library(self) -> None:
        if self.current_folder is None:
            folder = QFileDialog.getExistingDirectory(self, "选择词库文件夹", str(Path.home()))
            if not folder:
                return
            self.open_folder(Path(folder))
        name, ok = QInputDialog.getText(self, "新建词库", "词库名称（无需扩展名，例如 lighting）：")
        name = (name or "").strip() if ok else ""
        if not name:
            return
        if not name.lower().endswith(".txt"):
            name += ".txt"
        if any(ch in name for ch in '<>:"/\\|?*'):
            QMessageBox.warning(self, "错误", "文件名包含非法字符。")
            return
        target = self.current_folder / name
        if target.exists():
            QMessageBox.warning(self, "错误", "同名词库已存在。")
            return
        try:
            io.write_text_atomic(target, [], encoding="utf-8")
        except OSError as e:
            QMessageBox.critical(self, "创建失败", str(e))
            return
        self.sidebar.refresh()
        self.open_file(target)

    def rename_library(self, path_str: str) -> None:
        path = Path(path_str)
        name, ok = QInputDialog.getText(self, "重命名词库", "新名称：", text=path.stem)
        name = (name or "").strip() if ok else ""
        if not name:
            return
        if not name.lower().endswith(".txt"):
            name += ".txt"
        if any(ch in name for ch in '<>:"/\\|?*'):
            QMessageBox.warning(self, "错误", "文件名包含非法字符。")
            return
        target = path.with_name(name)
        if target.exists() and target != path:
            QMessageBox.warning(self, "错误", "同名词库已存在。")
            return
        try:
            path.rename(target)
        except OSError as e:
            QMessageBox.critical(self, "重命名失败", str(e))
            return
        if self.library is not None and self.library.path == path:
            self.library.path = target
            self._watch_library_file()
            self._update_title()
        self.sidebar.refresh()
        self.sidebar.select_path(target)

    def delete_library(self, path_str: str) -> None:
        path = Path(path_str)
        if not confirm(
            self,
            "删除词库",
            f"确定删除词库文件？\n{path.name}\n\n文件将被永久删除，此操作不可撤销。",
            ok_text="删除",
        ):
            return
        try:
            path.unlink()
        except OSError as e:
            QMessageBox.critical(self, "删除失败", str(e))
            return
        if self.library is not None and self.library.path == path:
            self._set_library(None)
        self.sidebar.refresh()
        self.statusBar().showMessage(f"已删除 {path.name}", 3000)

    # ================= 随机抽取 =================

    def random_pick(self) -> None:
        if self.model is None or self.model.rowCount() == 0:
            QMessageBox.information(self, "随机抽取", "当前列表为空，无法抽取。")
            return
        RandomPickDialog(self.model, self).exec()

    def random_pick_batch(self) -> None:
        if self.model is None or self.model.rowCount() == 0:
            QMessageBox.information(self, "随机抽取", "当前列表为空，无法抽取。")
            return
        RandomBatchDialog(self.model, self).exec()

    # ================= 搜索 =================

    def _on_search_debounce(self, _text: str) -> None:
        self._search_timer.start()

    def _apply_filter(self, *_args) -> None:
        if self.model is None:
            return
        q = self.search_edit.text()
        mode = MODES[self.mode_combo.currentIndex()][0]
        self.model.set_filter(q, mode)
        self.entry_view.set_drag_enabled(not q)
        self._update_stats()

    def _focus_search(self) -> None:
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    # ================= 撤销 / 重做 =================

    def _undo(self) -> None:
        if self.library is not None:
            self.library.undo_stack.undo()
            self.statusBar().showMessage("已撤销", 1500)

    def _redo(self) -> None:
        if self.library is not None:
            self.library.undo_stack.redo()
            self.statusBar().showMessage("已重做", 1500)

    # ================= 外部修改检测 =================

    def _set_folder_watch(self) -> None:
        if self._watcher.directories():
            self._watcher.removePaths(self._watcher.directories())
        if self.current_folder:
            self._watcher.addPath(str(self.current_folder))

    def _watch_library_file(self) -> None:
        if self._watcher.files():
            self._watcher.removePaths(self._watcher.files())
        lib = self.library
        if lib is not None and lib.path is not None and lib.path.exists():
            self._watcher.addPath(str(lib.path))

    def _on_watch_event(self, path: str) -> None:
        if self._saving:
            return
        p = Path(path)
        lib = self.library
        if lib is not None and lib.path is not None and (
            p == lib.path or (self.current_folder is not None and p == self.current_folder)
        ):
            self._change_timer.start()

    def _handle_external_change(self) -> None:
        lib = self.library
        if lib is None or lib.path is None:
            return
        if not lib.path.exists():
            if lib.dirty and confirm(
                self,
                "文件被删除",
                f"「{lib.name()}」已被外部程序删除。\n是否重新创建并保存当前内容？",
                ok_text="保存（重新创建）",
            ):
                self.save_library()
            else:
                self.statusBar().showMessage(f"「{lib.name()}」已被外部删除", 4000)
            return
        self._watch_library_file()
        try:
            disk_lines, _ = io.read_lines(lib.path)
        except OSError:
            return
        mem_lines = [e.text for e in lib.entries]
        if disk_lines == mem_lines:
            return
        if not lib.dirty:
            lib.reload()  # 无未保存修改 → 静默重载
            self._update_title()
            self._update_stats()
            self.statusBar().showMessage(f"检测到外部修改，已重新载入 {lib.name()}", 3000)
            return
        box = QMessageBox(self)
        box.setWindowTitle("外部修改检测")
        box.setText(f"「{lib.name()}」已被外部程序修改。")
        b_reload = box.addButton("重新载入", QMessageBox.AcceptRole)
        b_keep = box.addButton("保留当前修改", QMessageBox.ActionRole)
        b_diff = box.addButton("查看差异", QMessageBox.ActionRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is b_reload:
            lib.reload()
            self._update_title()
            self._update_stats()
        elif clicked is b_diff:
            DiffDialog(
                f"{lib.name()} — 外部修改差异",
                "\n".join(disk_lines),
                "\n".join(mem_lines),
                self,
            ).exec()

    # ================= 拖拽文件到窗口 =================

    def dragEnterEvent(self, event) -> None:
        for url in event.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.is_dir() or p.suffix.lower() == ".txt":
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event) -> None:
        urls = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.toLocalFile()]
        for p in urls:
            if p.is_dir():
                self.open_folder(p, autoload_first=True)
                return
        files = [p for p in urls if p.suffix.lower() == ".txt"]
        if files:
            self.open_file(files[0])
            if len(files) > 1:
                self.statusBar().showMessage(
                    f"已打开 {files[0].name}（共拖入 {len(files)} 个 TXT，仅打开第一个）", 5000
                )

    # ================= 状态 / 标题 / 提示 =================

    def _update_title(self) -> None:
        if self.library is None:
            self.setWindowTitle("Prompt Library Manager")
            return
        mark = "● " if self.library.dirty else ""
        self.setWindowTitle(f"{mark}{self.library.name()} — Prompt Library Manager")

    def _on_dirty_changed(self, dirty: bool) -> None:
        self._update_title()
        self.status_dirty.setText("● 未保存" if dirty else "已保存")

    def _update_stats(self) -> None:
        if self.library is None:
            self.stats_label.setText("未打开词库")
            self.status_encoding.setText("")
            self.status_dirty.setText("")
            return
        c = self.library.counts()
        parts = [f"共 {c['total']:,} 条"]
        if c["duplicates"]:
            parts.append(f"重复 {c['duplicates']}")
        if c["empty"]:
            parts.append(f"空行 {c['empty']}")
        if c["translated"]:
            parts.append(f"已翻译 {c['translated']}")
        parts.append(f"{c['chars']:,} 字符")
        if self.model is not None and self.model.query:
            parts.append(f"匹配 {len(self.model.visible):,}")
        self.stats_label.setText("  |  ".join(parts))
        self.status_encoding.setText(f"编码：{self.library.encoding}")

    def _guard_unsaved(self) -> bool:
        """有未保存修改时弹出 [保存并继续 / 放弃修改 / 取消]。"""
        if self.library is None or not self.library.dirty:
            return True
        box = QMessageBox(self)
        box.setWindowTitle("未保存的修改")
        box.setText(f"「{self.library.name()}」有未保存的修改。")
        b_save = box.addButton("保存并继续", QMessageBox.AcceptRole)
        b_discard = box.addButton("放弃修改", QMessageBox.DestructiveRole)
        b_cancel = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(b_save)
        box.exec()
        clicked = box.clickedButton()
        if clicked is b_save:
            self.save_library()
            return True
        if clicked is b_discard:
            return True
        return False

    def _entry_context_menu(self, pos) -> None:
        if self.model is None:
            return
        index = self.entry_view.indexAt(pos)
        rows = sorted({i.row() for i in self.entry_view.selectionModel().selectedIndexes()})
        menu = QMenu(self)
        if len(rows) == 1 and index.isValid():
            text = self.model.entry_at(rows[0]).text
            menu.addAction("编辑", lambda: self.entry_view.edit(index))
            menu.addAction("复制", lambda: QApplication.clipboard().setText(text))
            menu.addSeparator()
            menu.addAction("删除", self.delete_selected)
        elif len(rows) > 1:
            texts = "\n".join(self.model.entry_at(r).text for r in rows)
            menu.addAction(f"复制 {len(rows)} 条", lambda: QApplication.clipboard().setText(texts))
            menu.addSeparator()
            menu.addAction(f"删除 {len(rows)} 条", lambda: self.delete_selected(confirm_needed=True))
        else:
            menu.addAction("新增条目", self.add_entry)
        menu.exec(self.entry_view.viewport().mapToGlobal(pos))

    # ================= 其他 =================

    def _about(self) -> None:
        QMessageBox.about(
            self,
            "关于 Prompt Library Manager",
            "Prompt / Tag 文本词库管理器（Phase 1）\n\n"
            "用于管理 ComfyUI Wildcard / 文本列表词库的本地 TXT 工具。\n"
            "整行 = 一个随机候选项，导出 TXT 只输出原始文本。\n\n"
            "Phase 1 功能：打开/搜索/增删改/批量删除/去重/排序/拖拽排序/\n"
            "导入导出/随机抽取/Ctrl+S/Ctrl+Z/编码自动识别/外部修改检测。\n\n"
            "后续阶段：中文翻译、AI API、批量替换、CSV、词库合并与差异比较。",
        )

    def _restore_settings(self) -> None:
        geo = self.settings.value("geometry")
        if geo:
            self.restoreGeometry(geo)
        state = self.settings.value("splitter")
        if state:
            self.splitter.restoreState(state)

    def closeEvent(self, event) -> None:
        if not self._guard_unsaved():
            event.ignore()
            return
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("splitter", self.splitter.saveState())
        event.accept()
