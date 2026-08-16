"""主窗口：布局、菜单、快捷键、文件夹模式、外部修改检测、拖拽打开。"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QPoint, QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.core import csv_ops, io, library_ops
from app.core.ai_translate import AIConfig, TranslateWorker, TranslationCache
from app.core.commands import (
    AddEntriesCommand,
    BatchReplaceCommand,
    RemoveEntriesCommand,
    ReorderCommand,
    SetTranslationsCommand,
)
from app.core.dictionary import OfflineDictionary, default_tags_dirs
from app.core.model import Library
from app import resources
from app.ui import icons
from app.ui.dialogs import DiffDialog, ExportDialog, RandomBatchDialog, RandomPickDialog, confirm
from app.ui.entry_model import EntryListModel, MODES, SCOPES
from app.ui.entry_view import EntryListView, is_partial_translation
from app.ui.phase4_dialogs import CompareDialog, MergeDialog, TagStatsDialog
from app.ui.sidebar import SidebarPanel
from app.ui.translate_dialogs import (
    BatchReplaceDialog,
    EditTranslationDialog,
    MoveCopyDialog,
    TranslationSettingsDialog,
)

SORT_MODES = [
    ("original", "原始顺序"),
    ("alpha_asc", "A → Z"),
    ("alpha_desc", "Z → A"),
    ("pinyin", "中文拼音"),
    ("length", "长度（短 → 长）"),
    ("random", "随机排序"),
]


def default_txt_dir() -> Path | None:
    """项目默认词库目录：打包后依次尝试 exe 旁、exe 父级、项目根目录的 txt。"""
    cands: list[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        # 单目录打包：exe 在 dist\PromptLibraryManager\，项目根目录是其上两级
        cands += [
            exe_dir / "txt",
            exe_dir / "_internal" / "txt",
            exe_dir.parent / "txt",
            exe_dir.parent.parent / "txt",
        ]
    cands.append(Path(__file__).resolve().parent.parent.parent / "txt")
    for c in cands:
        if c.is_dir():
            return c
    return None


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("词库管理器")
        self.setMinimumSize(960, 600)
        self.resize(1280, 800)
        self.setAcceptDrops(True)

        self.library: Library | None = None
        self._bound_lib: Library | None = None
        self.model: EntryListModel | None = None
        self.current_folder: Path | None = None
        self._saving = False

        self.settings = QSettings("PromptLib", "PromptLibraryManager")

        self._load_ai_config()
        dict_override = str(self.settings.value("translate/dict_dir", ""))
        self.dictionary = OfflineDictionary(
            [Path(dict_override)] if dict_override else default_tags_dirs()
        )
        self.cache = TranslationCache()
        self._translate_worker = None
        self._translate_progress = None
        self._translate_ids: dict[str, list[str]] = {}

        self._sidecar_timer = QTimer(self)
        self._sidecar_timer.setSingleShot(True)
        self._sidecar_timer.setInterval(1200)
        self._sidecar_timer.timeout.connect(self._flush_sidecar)

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(600)
        self._autosave_timer.timeout.connect(self._autosave)

        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(400)
        self._scroll_timer.timeout.connect(self._translate_visible)
        self._lazy_translate_active = False

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

        # 词典后台加载，不阻塞界面显示
        self.status_dict.setText("词典 加载中…")
        self.status_dict.setToolTip("正在加载离线词典（zh-CN.txt + danbooru/e621 别名表）")
        self._dict_timer = QTimer(self)
        self._dict_timer.setInterval(120)
        self._dict_timer.timeout.connect(self._check_dict_loaded)
        threading.Thread(target=self._load_dictionary, daemon=True).start()
        self._dict_timer.start()

        last = self.settings.value("last_folder", "")
        if last and Path(last).is_dir():
            self.open_folder(Path(last), autoload_first=True)
        else:
            d = default_txt_dir()
            if d is not None:
                self.open_folder(d, autoload_first=True)

    # ================= UI =================

    def _build_ui(self) -> None:
        self.sidebar = SidebarPanel(self)

        # ---- 右侧：搜索/工具栏 + 列表 + 统计 ----
        right = QWidget(self)
        rlay = QVBoxLayout(right)
        rlay.setContentsMargins(8, 8, 8, 8)
        rlay.setSpacing(6)

        # 当前词库名（重点显示）
        self.current_file_label = QLabel("未打开词库")
        self.current_file_label.setStyleSheet(
            "QLabel { color:#4fc3f7; font-size:17px; font-weight:600; "
            "padding:2px 4px; border-left:3px solid #4fc3f7; }"
        )
        rlay.addWidget(self.current_file_label)

        row1 = QHBoxLayout()
        row1.setSpacing(6)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索（不区分大小写，Ctrl+F 聚焦）…")
        self.search_edit.setClearButtonEnabled(True)
        self.btn_filter = QToolButton()
        self.btn_filter.setIcon(icons.make_static_icon("funnel"))
        self.btn_filter.setIconSize(icons.QSIZE)
        self.btn_filter.setPopupMode(QToolButton.InstantPopup)
        self.btn_filter.setToolTip("筛选方式（包含 / 前缀 / 精确 / 正则）")
        self.btn_filter.setProperty("bare", True)
        self.btn_random = QToolButton(text="🎲 随机")
        self.btn_random.setToolTip("随机抽取一条（Ctrl+R）")
        row1.addWidget(self.search_edit, 1)
        row1.addWidget(self.btn_filter)
        row1.addWidget(self.btn_random)
        rlay.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(6)
        self.btn_new_entry = QToolButton(text="新增")
        self.btn_new_entry.setToolTip("在列表底部新增条目（Ctrl+N）")
        self.btn_import = QToolButton(text="导入")
        self.btn_export = QToolButton(text="导出")
        self.btn_batch = QToolButton(text="批量 ▾")
        self.btn_batch.setPopupMode(QToolButton.InstantPopup)
        self.btn_translate = QToolButton()
        _svg = resources.resource_path("翻译.svg")
        if _svg is not None:
            self.btn_translate.setIcon(QIcon(str(_svg)))
        self.btn_translate.setIconSize(icons.QSIZE)
        self.btn_translate.setToolTip("翻译当前文件（仅翻译可见部分，滚动时继续）")
        self.btn_translate.setProperty("bare", True)
        # 紧凑布局开关（图标，紧挨翻译）
        self.btn_compact = QToolButton()
        self.btn_compact.setIcon(icons.make_static_icon("compact"))
        self.btn_compact.setIconSize(icons.QSIZE)
        self.btn_compact.setCheckable(True)
        self.btn_compact.setToolTip("紧凑布局：英文紧邻中文（如 1girl | 1女孩）")
        self.btn_compact.setProperty("bare", True)
        # 排序图标（无容器）
        self.btn_sort = QToolButton()
        self.btn_sort.setIcon(icons.make_static_icon("sort"))
        self.btn_sort.setIconSize(icons.QSIZE)
        self.btn_sort.setPopupMode(QToolButton.InstantPopup)
        self.btn_sort.setToolTip("排序（A→Z / 中文拼音 / 随机…）")
        self.btn_sort.setProperty("bare", True)
        row2.addWidget(self.btn_new_entry)
        row2.addWidget(self.btn_import)
        row2.addWidget(self.btn_export)
        row2.addWidget(self.btn_batch)
        row2.addWidget(self.btn_compact)
        row2.addWidget(self.btn_translate)
        row2.addWidget(self.btn_sort)
        row2.addStretch(1)
        self.btn_clear_sel = QToolButton(text="取消选中")
        self.btn_clear_sel.setToolTip("清除所有选中状态")
        self.btn_copy_sel = QToolButton(text="复制选中")
        self.btn_copy_sel.setToolTip("复制选中的条目到剪贴板（每行一个）")
        self.btn_delete = QToolButton(text="删除选中")
        for _b in (self.btn_clear_sel, self.btn_copy_sel, self.btn_delete):
            _b.setEnabled(False)
        row2.addWidget(self.btn_clear_sel)
        row2.addWidget(self.btn_copy_sel)
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
        self.splitter.setSizes([150, 1130])
        self.setCentralWidget(self.splitter)

        # 状态栏
        self.status_dirty = QLabel("")
        self.status_encoding = QLabel("")
        self.status_dict = QLabel("")
        self.statusBar().addPermanentWidget(self.status_encoding)
        self.statusBar().addPermanentWidget(self.status_dict)
        self.statusBar().addPermanentWidget(self.status_dirty)

        # 信号
        self._search_mode = "contains"
        self._search_scope = "both"
        self.search_edit.textChanged.connect(self._on_search_debounce)
        self.btn_random.clicked.connect(self.random_pick)
        self.btn_new_entry.clicked.connect(self.add_entry)
        self.btn_import.clicked.connect(self.import_txt)
        self.btn_export.clicked.connect(self.export_txt)
        self.btn_delete.clicked.connect(self.delete_selected)
        self.btn_copy_sel.clicked.connect(self.copy_selected)
        self.btn_translate.clicked.connect(self._translate_file_lazy)
        self.entry_view.delete_requested.connect(self.delete_selected)
        self.entry_view.clear_search_requested.connect(self._clear_search)
        self.entry_view.translate_requested.connect(self._translate_entry)
        self.entry_view.customContextMenuRequested.connect(self._entry_context_menu)
        self.entry_view.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self.entry_view.selection_changed.connect(self._update_selection_buttons)
        self.btn_compact.toggled.connect(self._on_compact_toggled)
        self.btn_clear_sel.clicked.connect(self._clear_selection)
        # 筛选方式菜单（漏斗）
        self._filter_menu = QMenu(self)
        self._filter_group = QActionGroup(self)
        self._filter_group.setExclusive(True)
        for _key, label in MODES:
            a = QAction(label, self)
            a.setCheckable(True)
            if _key == "contains":
                a.setChecked(True)
            a.triggered.connect(lambda _=False, m=_key: self._set_search_mode(m))
            self._filter_group.addAction(a)
            self._filter_menu.addAction(a)
        # 搜索范围：原文 / 翻译 / 两者
        self._filter_menu.addSeparator()
        self._scope_group = QActionGroup(self)
        self._scope_group.setExclusive(True)
        for _key, label in SCOPES:
            a = QAction(label, self)
            a.setCheckable(True)
            if _key == "both":
                a.setChecked(True)
            a.triggered.connect(lambda _=False, s=_key: self._set_search_scope(s))
            self._scope_group.addAction(a)
            self._filter_menu.addAction(a)
        self.btn_filter.setMenu(self._filter_menu)

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

        def act(parent, text, shortcut, handler):
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            a.triggered.connect(handler)
            parent.addAction(a)
            return a

        act(m_file, "打开词库文件夹…", "Ctrl+Shift+O", self._choose_folder)
        act(m_file, "打开 TXT…", "Ctrl+O", self.open_file_dialog)
        m_recent = m_file.addMenu("最近打开")
        m_recent.aboutToShow.connect(self._build_recent_menu)
        act(m_file, "导入 TXT / CSV…", "Ctrl+I", self.import_txt)
        act(m_file, "导出 TXT…", "Ctrl+E", self.export_txt)
        act(m_file, "导出 CSV（英中对照）…", None, self.export_csv)
        m_file.addSeparator()
        act(m_file, "保存", "Ctrl+S", self.save_library)
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

        batch_menu = QMenu("批量操作", self)
        batch_menu.addAction("批量替换…", self.batch_replace)
        batch_menu.addAction("复制到其他词库…", lambda: self.move_copy_entries())
        batch_menu.addAction("移动到其他词库…", lambda: self.move_copy_entries(move=True))
        batch_menu.addAction("词库合并…", self.merge_libraries)
        batch_menu.addAction("词库差异比较…", self.compare_libraries)
        self.btn_batch.setMenu(batch_menu)
        m_tool.addMenu(batch_menu)

        act(m_tool, "Tag 统计…", None, self.tag_stats)
        act(m_tool, "词库合并…", None, self.merge_libraries)
        act(m_tool, "词库差异比较…", None, self.compare_libraries)

        # 翻译菜单（工具栏按钮 + 菜单栏共用同一组 action）
        a_offline = QAction("离线词典翻译选中", self)
        a_offline.triggered.connect(lambda: self.translate_selected(ai=False))
        a_ai_sel = QAction("在线翻译选中", self)
        a_ai_sel.triggered.connect(lambda: self.translate_selected(ai=True))
        a_ai_all = QAction("在线翻译全部未翻译…", self)
        a_ai_all.triggered.connect(self.translate_all_untranslated)
        a_edit_tr = QAction("编辑翻译…", self)
        a_edit_tr.triggered.connect(self.edit_translation)
        a_clear_tr = QAction("清除选中翻译", self)
        a_clear_tr.triggered.connect(self.clear_selected_translations)
        a_tr_cfg = QAction("翻译设置…", self)
        a_tr_cfg.triggered.connect(self.open_translate_settings)

        m_translate = mb.addMenu("翻译(&L)")
        for a in (a_offline, a_ai_sel, a_ai_all):
            m_translate.addAction(a)
        m_translate.addSeparator()
        m_translate.addAction(a_edit_tr)
        m_translate.addAction(a_clear_tr)
        m_translate.addSeparator()
        m_translate.addAction(a_tr_cfg)

        act(mb, "帮助(&H)", "F1", self._help)

        # Ctrl+F 聚焦搜索框
        self.act_focus_search = QAction(self)
        self.act_focus_search.setShortcut(QKeySequence("Ctrl+F"))
        self.act_focus_search.triggered.connect(self._focus_search)
        self.addAction(self.act_focus_search)

    # ================= 库切换 =================

    def _bind_library(self, lib: Library) -> None:
        self._bound_lib = lib
        self.library = lib
        self._lazy_translate_active = False
        self.model = EntryListModel(lib, self)
        self.entry_view.setModel(self.model)
        self.entry_view.set_drag_enabled(not self.model.query)
        lib.undo_stack.canUndoChanged.connect(self.act_undo.setEnabled)
        lib.undo_stack.canRedoChanged.connect(self.act_redo.setEnabled)
        lib.dirty_changed.connect(self._on_dirty_changed)
        lib.meta_changed.connect(self._update_stats)
        lib.translations_changed.connect(self._sidecar_timer.start)
        lib.undo_stack.indexChanged.connect(self._autosave_timer.start)
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
            (lib.translations_changed, self._sidecar_timer.start),
            (lib.undo_stack.indexChanged, self._autosave_timer.start),
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
        self._flush_sidecar()
        self._unbind_library()
        if self.library is not None and self.library is not lib:
            self.library.deleteLater()
        self.library = lib
        if lib is None:
            self.entry_view.setModel(None)
            self.sidebar.set_current(None)
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
        self._add_recent_folder(folder)
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
        self._set_search_mode("contains")
        self.sidebar.select_path(path)
        self.statusBar().showMessage(f"已打开 {path.name}（{lib.encoding}）", 3000)
        self._auto_offline_translate()

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
            self.import_csv(Path(path))
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

    def import_csv(self, path: Path) -> None:
        """导入英中对照 CSV：已有条目更新翻译，没有的追加。"""
        if self.library is None:
            QMessageBox.information(self, "提示", "请先打开一个词库。")
            return
        try:
            pairs = csv_ops.read_translation_csv(path)
        except OSError as e:
            QMessageBox.critical(self, "导入失败", str(e))
            return
        if not pairs:
            QMessageBox.information(self, "导入 CSV", "该 CSV 没有可导入的内容。")
            return
        if not confirm(
            self,
            "导入 CSV（英中对照）",
            f"将导入 {len(pairs)} 对英中对照：\n"
            "- 已存在的条目：更新中文翻译\n"
            "- 不存在的条目：作为新条目追加（可 Ctrl+Z 撤销）",
        ):
            return
        from app.core.commands import ImportCsvCommand

        self.library.undo_stack.push(ImportCsvCommand(self.library, pairs))
        self._flush_sidecar()
        self.statusBar().showMessage(f"已导入 {len(pairs)} 对英中对照（Ctrl+Z 可撤销）", 3000)

    def export_csv(self) -> None:
        """导出英中对照 CSV（全条目，含未翻译）。"""
        if self.library is None:
            QMessageBox.information(self, "提示", "请先打开一个词库。")
            return
        default = (self.library.path.stem if self.library.path else "export") + ".csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 CSV（英中对照）", str(Path(default)), "CSV 文件 (*.csv)"
        )
        if not path:
            return
        try:
            csv_ops.write_translation_csv(
                Path(path), [(e.text, e.translation) for e in self.library.entries]
            )
        except OSError as e:
            QMessageBox.critical(self, "导出失败", str(e))
            return
        n = len(self.library.entries)
        self.statusBar().showMessage(f"已导出 {n} 条英中对照 → {path}", 4000)

    def export_txt(self) -> None:
        if self.library is None:
            QMessageBox.information(self, "提示", "请先打开一个词库。")
            return
        sep_default = str(self.settings.value("export/separator", ", "))
        dlg = ExportDialog(self.library.entries, sep_default, self)
        if dlg.exec() != QDialog.Accepted:
            return
        fmt, sep = dlg.result()
        self.settings.setValue("export/separator", sep)

        default = self.library.path.name if self.library.path else "export.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 TXT", str(Path(default)), "文本文件 (*.txt)"
        )
        if not path:
            return
        try:
            if fmt == "direct":
                lines = [e.text for e in self.library.entries]
            else:
                lines = [
                    f"{e.text}{sep}{e.translation}" if e.translation else e.text
                    for e in self.library.entries
                ]
            io.write_text_atomic(Path(path), lines, encoding="utf-8")
        except OSError as e:
            QMessageBox.critical(self, "导出失败", str(e))
            return
        n = len(self.library.entries)
        self.statusBar().showMessage(f"已导出 {n} 条 → {path}", 4000)

    # ================= 翻译 =================

    def _load_ai_config(self) -> None:
        s = self.settings
        self.ai_cfg = AIConfig(
            enabled=bool(s.value("translate/enabled", False, type=bool)),
            provider=str(s.value("translate/provider", "openai")),
            base_url=str(s.value("translate/base_url", "https://api.openai.com/v1")),
            api_key=str(s.value("translate/api_key", "")),
            model=str(s.value("translate/model", "gpt-4o-mini")),
            concurrency=int(s.value("translate/concurrency", 4)),
            batch_size=int(s.value("translate/batch_size", 20)),
            baidu_appid=str(s.value("translate/baidu_appid", "")),
            baidu_secret=str(s.value("translate/baidu_secret", "")),
        )
        self.ai_cfg.normalize()

    def _save_ai_config(self) -> None:
        s = self.settings
        c = self.ai_cfg
        s.setValue("translate/enabled", c.enabled)
        s.setValue("translate/provider", c.provider)
        s.setValue("translate/base_url", c.base_url)
        s.setValue("translate/api_key", c.api_key)
        s.setValue("translate/model", c.model)
        s.setValue("translate/concurrency", c.concurrency)
        s.setValue("translate/batch_size", c.batch_size)
        s.setValue("translate/baidu_appid", c.baidu_appid)
        s.setValue("translate/baidu_secret", c.baidu_secret)

    def _load_dictionary(self) -> None:
        try:
            self.dictionary.load()
        except Exception:
            pass

    def _check_dict_loaded(self) -> None:
        if not self.dictionary.loaded:
            return
        self._dict_timer.stop()
        self._on_dict_loaded()
        # 词典加载完成后，对已打开的词库补一次自动离线翻译
        if self.library is not None:
            self._auto_offline_translate()

    def _on_dict_loaded(self) -> None:
        d = self.dictionary
        if d.loaded:
            self.status_dict.setText(f"词典 {d.zh_count:,}/{d.alias_count:,}")
            self.status_dict.setToolTip("离线词典：zh-CN.txt 英中对照 + danbooru/e621 别名表")
        else:
            self.status_dict.setText("词典 未加载")
            self.status_dict.setToolTip(d.error or "未找到词典文件（需要 Tags 目录或翻译设置指定）")

    def _flush_sidecar(self) -> None:
        if self.library is not None:
            self.library.save_sidecar()

    def _auto_offline_translate(self) -> None:
        """打开词库后自动用离线词典翻译未翻译的条目（不覆盖已有翻译）。"""
        lib = self.library
        if lib is None or not self.dictionary.loaded:
            return
        changes: list[tuple[str, str]] = []
        for e in lib.entries:
            if not e.translation:
                zh = self.dictionary.translate_entry(e.text)
                if zh:
                    changes.append((e.id, zh))
        if changes:
            lib.apply_translations(changes)
            lib.save_sidecar()
            self.statusBar().showMessage(f"已自动离线翻译 {len(changes)} 条", 3000)

    def selected_texts(self) -> list[str]:
        rows = sorted({i.row() for i in self.entry_view.selectionModel().selectedIndexes()})
        if not rows or self.model is None:
            return []
        return list(dict.fromkeys(self.model.entry_at(r).text for r in rows))

    def translate_selected(self, ai: bool = True) -> None:
        if self.library is None or self.model is None:
            QMessageBox.information(self, "翻译", "请先打开一个词库。")
            return
        texts = self.selected_texts()
        if not texts:
            QMessageBox.information(self, "翻译", "请先选中要翻译的条目（可 Ctrl+A 全选）。")
            return
        self._start_translate(texts, ai=ai)

    def translate_all_untranslated(self) -> None:
        if self.library is None:
            return
        if self.model is not None and self.model.query:
            cand = [self.model.entry_at(r) for r in range(self.model.rowCount())]
        else:
            cand = self.library.entries
        texts = list(dict.fromkeys(e.text for e in cand if not e.translation or e.translation_dirty))
        if not texts:
            QMessageBox.information(self, "批量翻译", "当前范围没有未翻译的条目。")
            return
        self._start_translate(texts, ai=True)

    def _start_translate(self, texts: list[str], ai: bool) -> None:
        if not texts:
            return
        if not ai:
            self._offline_translate(texts)
            return
        if self._translate_worker is not None:
            QMessageBox.information(self, "翻译", "已有翻译任务正在进行，请稍候。")
            return
        worker = TranslateWorker(texts, self.ai_cfg, self.cache, self.dictionary, skip_dict=True, parent=self)
        self._translate_worker = worker
        self._translate_ids = {}
        for e in self.library.entries:
            self._translate_ids.setdefault(e.text, []).append(e.id)
        dlg = QProgressDialog("准备翻译…", "取消", 0, len(texts), self)
        dlg.setWindowTitle("在线批量翻译")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.canceled.connect(worker.cancel.set)
        self._translate_progress = dlg
        worker.progress.connect(self._on_translate_progress)
        worker.finished.connect(self._on_translate_finished)
        threading.Thread(target=worker.run, daemon=True).start()

    def _on_translate_progress(self, done: int, total: int, current: str) -> None:
        dlg = self._translate_progress
        if dlg is None:
            return
        dlg.setMaximum(max(total, 1))
        dlg.setValue(done)
        if current:
            dlg.setLabelText(f"翻译中… {done}/{total}\n{current[:80]}")

    def _on_translate_finished(self, results: dict, errors: list) -> None:
        if self._translate_progress is not None:
            self._translate_progress.close()
            self._translate_progress.deleteLater()
            self._translate_progress = None
        self._translate_worker = None
        changes = []
        for text, zh in results.items():
            for eid in self._translate_ids.get(text, []):
                entry = self.library.get(eid) if self.library else None
                if entry is not None and entry.translation != zh:
                    changes.append((eid, entry.translation, zh))
        if changes and self.library is not None:
            self.library.undo_stack.push(
                SetTranslationsCommand(self.library, changes, f"在线翻译 {len(changes)} 条")
            )
        if self.library is not None:
            self._flush_sidecar()
            self._update_stats()
        if errors:
            QMessageBox.warning(
                self,
                "翻译完成",
                f"成功 {len(changes)} 条，失败 {len(errors)} 条。\n\n" + "\n".join(errors[:8]),
            )
        else:
            self.statusBar().showMessage(f"翻译完成：{len(changes)} 条", 4000)

    def _offline_translate(self, texts: list[str]) -> None:
        if not self.dictionary.loaded:
            QMessageBox.information(
                self,
                "离线翻译",
                "离线词典未加载。\n" + (self.dictionary.error or "请在 翻译设置 中指定词典目录。"),
            )
            return
        wanted = set(texts)
        changes = []
        for e in self.library.entries:
            if e.text not in wanted:
                continue
            zh = self.dictionary.translate_entry(e.text)
            if zh and zh != e.translation:
                changes.append((e.id, e.translation, zh))
        if changes:
            self.library.undo_stack.push(
                SetTranslationsCommand(self.library, changes, f"离线翻译 {len(changes)} 条")
            )
            self._flush_sidecar()
        self.statusBar().showMessage(f"离线翻译 {len(changes)} 条（词典命中）", 3000)

    def _translate_file_lazy(self) -> None:
        """点击工具栏翻译图标：翻译当前可见部分，滚动时继续。"""
        if self.library is None or self.model is None:
            QMessageBox.information(self, "翻译", "请先打开一个词库。")
            return
        self._lazy_translate_active = True
        self.statusBar().showMessage("懒加载翻译已启动：翻译可见部分，滚动时继续", 3000)
        self._translate_visible()

    def _on_scroll(self, _value: int) -> None:
        if self._lazy_translate_active:
            self._scroll_timer.start()

    def _visible_rows(self) -> tuple[int, int]:
        view = self.entry_view
        model = self.model
        if model is None or model.rowCount() == 0:
            return (0, 0)
        vp = view.viewport()
        top = view.indexAt(QPoint(10, 10))
        bottom = view.indexAt(QPoint(10, max(0, vp.height() - 10)))
        top_row = top.row() if top.isValid() else 0
        bottom_row = bottom.row() if bottom.isValid() else model.rowCount() - 1
        return (top_row, bottom_row)

    def _translate_visible(self) -> None:
        if self.model is None or self.library is None:
            return
        top, bottom = self._visible_rows()
        bottom = min(bottom + 50, self.model.rowCount() - 1)  # 下方多带一小部分
        texts = []
        for r in range(top, bottom + 1):
            e = self.model.entry_at(r)
            if e is None:
                continue
            # 未翻译，或离线词典只翻译了一部分（中英混杂）→ 需要翻译
            if not e.translation or is_partial_translation(e.translation):
                texts.append(e.text)
        self._translate_silent(list(dict.fromkeys(texts)), replace_translated=True)

    def _translate_entry(self, eid: str) -> None:
        """内联翻译按钮：未翻译走词典+AI；部分翻译走 AI 替换。"""
        if self.library is None:
            return
        e = self.library.get(eid)
        if e is None:
            return
        if e.translation:
            self._translate_silent([e.text], replace_translated=True)
        else:
            self._translate_silent([e.text])

    def _translate_silent(self, texts: list[str], replace_translated: bool = False) -> None:
        """静默翻译一批（不弹进度框）。

        - 未翻译：缓存 / 离线词典优先，词典只部分命中时交给 AI 全量翻译。
        - 已翻译（replace_translated=True）：用 AI 替换（跳过本地词典）。
        """
        if not texts or self.library is None:
            return
        wanted = set(texts)
        changes = []
        ai_todo = []
        for e in self.library.entries:
            if e.text not in wanted:
                continue
            if e.translation:
                if replace_translated:
                    ai_todo.append(e.text)  # 用 AI 替换已有翻译
                continue
            got = self.cache.get(e.text) if self.ai_cfg.use_cache else None
            if got is None and self.dictionary.loaded:
                got = self.dictionary.translate_entry(e.text)
                if got is not None and is_partial_translation(got):
                    got = None  # 词典部分命中 → 交给 AI
            if got:
                changes.append((e.id, e.translation, got))
            else:
                ai_todo.append(e.text)
        if changes:
            self.library.undo_stack.push(
                SetTranslationsCommand(self.library, changes, f"离线翻译 {len(changes)} 条")
            )
            self._flush_sidecar()
            self._update_stats()
        ai_todo = list(dict.fromkeys(ai_todo))
        if not ai_todo:
            if changes:
                self.statusBar().showMessage(f"已翻译 {len(changes)} 条", 3000)
            return
        if not self.ai_cfg.enabled:
            self.statusBar().showMessage(
                f"离线命中 {len(changes)} 条；{len(ai_todo)} 条需在线翻译（未启用）", 5000
            )
            return
        if self._translate_worker is not None:
            return
        worker = TranslateWorker(
            ai_todo, self.ai_cfg, self.cache, self.dictionary, skip_dict=True, parent=self
        )
        self._translate_worker = worker
        self._translate_ids = {}
        for e in self.library.entries:
            self._translate_ids.setdefault(e.text, []).append(e.id)
        worker.finished.connect(self._on_translate_finished)
        threading.Thread(target=worker.run, daemon=True).start()
        self.statusBar().showMessage(f"在线翻译中… {len(ai_todo)} 条", 3000)

    def edit_translation(self) -> None:
        if self.library is None or self.model is None:
            return
        rows = sorted({i.row() for i in self.entry_view.selectionModel().selectedIndexes()})
        if len(rows) != 1:
            QMessageBox.information(self, "编辑翻译", "请只选中一条条目。")
            return
        entry = self.model.entry_at(rows[0])
        dlg = EditTranslationDialog(entry.text, entry.translation, self)
        if dlg.exec() == QDialog.Accepted:
            new = dlg.text()
            if new != entry.translation:
                self.library.undo_stack.push(
                    SetTranslationsCommand(self.library, [(entry.id, entry.translation, new)], "编辑翻译")
                )
                self._flush_sidecar()

    def clear_selected_translations(self) -> None:
        if self.library is None or self.model is None:
            return
        rows = sorted({i.row() for i in self.entry_view.selectionModel().selectedIndexes()})
        changes = [
            (self.model.entry_at(r).id, self.model.entry_at(r).translation, "")
            for r in rows
            if self.model.entry_at(r).translation
        ]
        if not changes:
            QMessageBox.information(self, "清除翻译", "选中的条目都没有翻译。")
            return
        self.library.undo_stack.push(
            SetTranslationsCommand(self.library, changes, f"清除 {len(changes)} 条翻译")
        )
        self._flush_sidecar()
        self.statusBar().showMessage(f"已清除 {len(changes)} 条翻译（Ctrl+Z 可撤销）", 3000)

    def open_translate_settings(self) -> None:
        dlg = TranslationSettingsDialog(self.ai_cfg, self.dictionary, self.cache, self)
        if dlg.exec() == QDialog.Accepted:
            self.ai_cfg = dlg.result_cfg()
            self._save_ai_config()
            self._on_dict_loaded()
            self.statusBar().showMessage("翻译设置已保存", 3000)

    # ================= 批量替换 / 跨词库复制移动 =================

    def batch_replace(self) -> None:
        if self.library is None:
            QMessageBox.information(self, "提示", "请先打开一个词库。")
            return
        dlg = BatchReplaceDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        find, repl, scope = dlg.values()
        if not find.strip():
            QMessageBox.warning(self, "批量替换", "查找内容不能为空。")
            return
        if scope == "all":
            self._batch_replace_all(find, repl)
        else:
            self._batch_replace_current(find, repl)

    def _batch_replace_current(self, find: str, repl: str) -> None:
        changes = library_ops.library_replace_changes(self.library, find, repl)
        if not changes:
            QMessageBox.information(self, "批量替换", f"未找到包含「{find}」的条目。")
            return
        if not confirm(
            self,
            "批量替换",
            f"发现 {len(changes)} 个匹配条目。\n将把「{find}」替换为「{repl}」（不区分大小写）。\n替换可用 Ctrl+Z 撤销。",
            ok_text="全部替换",
        ):
            return
        self.library.undo_stack.push(BatchReplaceCommand(self.library, changes, find, repl))
        self.statusBar().showMessage(f"已替换 {len(changes)} 条（Ctrl+Z 可撤销）", 3000)

    def _batch_replace_all(self, find: str, repl: str) -> None:
        if self.current_folder is None:
            QMessageBox.information(self, "批量替换", "请先打开词库文件夹。")
            return
        files = sorted(self.current_folder.glob("*.txt"), key=lambda x: x.name.casefold())
        if not files:
            return
        _apply, count = library_ops.compile_replacer(find, repl)
        total = 0
        readable: list[Path] = []
        for f in files:
            try:
                lines, _ = io.read_lines(f)
                readable.append(f)
                total += sum(count(ln) for ln in lines)
            except OSError:
                continue
        if not total:
            QMessageBox.information(self, "批量替换", f"所有词库中未找到包含「{find}」的条目。")
            return
        if not confirm(
            self,
            "批量替换",
            f"所有词库共发现 {total} 个匹配项（{len(readable)} 个文件）。\n"
            "将直接写入文件，此操作不可撤销。",
            ok_text="全部替换",
        ):
            return
        progress = QProgressDialog("正在替换…", None, 0, len(readable), self)
        progress.setWindowTitle("批量替换（所有词库）")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        for i, f in enumerate(readable):
            if (
                self.library is not None
                and self.library.path is not None
                and f.resolve() == self.library.path.resolve()
            ):
                changes = library_ops.library_replace_changes(self.library, find, repl)
                if changes:
                    self.library.undo_stack.push(
                        BatchReplaceCommand(self.library, changes, find, repl)
                    )
                    self.save_library()
            else:
                try:
                    library_ops.replace_in_file(f, find, repl)
                except OSError:
                    pass
            progress.setValue(i + 1)
        progress.close()
        self.statusBar().showMessage(f"所有词库替换完成：共 {total} 处", 4000)

    def move_copy_entries(self, move: bool = False) -> None:
        if self.library is None or self.model is None or self.current_folder is None:
            return
        rows = sorted({i.row() for i in self.entry_view.selectionModel().selectedIndexes()})
        if not rows:
            QMessageBox.information(self, "复制/移动", "请先选中条目（可 Ctrl+A 全选）。")
            return
        texts = [self.model.entry_at(r).text for r in rows]
        cur = self.library.path.resolve() if self.library.path else None
        targets = [
            (p.name, str(p))
            for p in sorted(self.current_folder.glob("*.txt"), key=lambda x: x.name.casefold())
            if cur is None or p.resolve() != cur
        ]
        if not targets:
            QMessageBox.information(self, "复制/移动", "当前文件夹没有其他词库。")
            return
        dlg = MoveCopyDialog(targets, len(texts), default_move=move, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        mode, target_path = dlg.result()
        try:
            added = library_ops.append_lines_to_file(Path(target_path), texts)
        except OSError as e:
            QMessageBox.critical(self, "失败", f"写入目标词库失败：\n{e}")
            return
        if mode == "move":
            entries = [self.model.entry_at(r) for r in rows]
            self.library.undo_stack.push(
                RemoveEntriesCommand(self.library, entries, "移动到其他词库")
            )
            self.statusBar().showMessage(
                f"已移动 {len(entries)} 条 → {Path(target_path).name}（源库 Ctrl+Z 可撤销）", 4000
            )
        else:
            self.statusBar().showMessage(f"已复制 {added} 条 → {Path(target_path).name}", 4000)

    # ================= Phase 4：统计 / 合并 / 差异比较 =================

    def folder_txt_files(self) -> list[tuple[str, str]]:
        if self.current_folder is None:
            return []
        return [
            (p.name, str(p))
            for p in sorted(self.current_folder.glob("*.txt"), key=lambda x: x.name.casefold())
        ]

    def tag_stats(self) -> None:
        if self.library is None:
            QMessageBox.information(self, "提示", "请先打开一个词库。")
            return
        TagStatsDialog(self.library, self).exec()

    def merge_libraries(self) -> None:
        if self.current_folder is None:
            QMessageBox.information(self, "词库合并", "请先打开词库文件夹。")
            return
        cur = self.library.path.resolve() if self.library and self.library.path else None
        others = [
            (n, p) for n, p in self.folder_txt_files() if cur is None or Path(p).resolve() != cur
        ]
        if not others:
            QMessageBox.information(self, "词库合并", "当前文件夹没有其他词库可合并。")
            return
        dlg = MergeDialog(others, self)
        if dlg.exec() != QDialog.Accepted:
            return
        paths = dlg.selected_paths()
        if not paths:
            QMessageBox.information(self, "词库合并", "请至少选择一个词库。")
            return
        lists: list[list[str]] = []
        for p in paths:
            try:
                lists.append(io.read_lines(Path(p))[0])
            except OSError as e:
                QMessageBox.critical(self, "读取失败", f"{Path(p).name}：\n{e}")
                return
        target_current = not dlg.to_new_file()
        if dlg.dedupe() and target_current:
            lists.insert(0, [e.text for e in self.library.entries])
        merged = library_ops.merge_lines(lists, dlg.dedupe())
        if target_current:
            existing = {e.text for e in self.library.entries}
            merged = [ln for ln in merged if ln not in existing]
        if not merged:
            QMessageBox.information(self, "词库合并", "没有可合并的新条目。")
            return
        if target_current:
            if not confirm(
                self,
                "词库合并",
                f"将向当前词库追加 {len(merged)} 条（来自 {len(paths)} 个词库）。\n可 Ctrl+Z 撤销。",
            ):
                return
            self.library.undo_stack.push(
                AddEntriesCommand(self.library, merged, None, "词库合并")
            )
            self.statusBar().showMessage(f"已合并 {len(merged)} 条（Ctrl+Z 可撤销）", 3000)
        else:
            path, _ = QFileDialog.getSaveFileName(
                self, "合并另存为", "merged.txt", "文本文件 (*.txt)"
            )
            if not path:
                return
            try:
                io.write_text_atomic(Path(path), merged, encoding="utf-8")
            except OSError as e:
                QMessageBox.critical(self, "保存失败", str(e))
                return
            self.statusBar().showMessage(f"已合并 {len(merged)} 条 → {path}", 4000)

    def compare_libraries(self) -> None:
        if self.current_folder is None:
            QMessageBox.information(self, "词库差异比较", "请先打开词库文件夹。")
            return
        files = self.folder_txt_files()
        if len(files) < 2:
            QMessageBox.information(self, "词库差异比较", "文件夹中至少需要两个词库。")
            return
        cur = str(self.library.path) if self.library and self.library.path else None
        CompareDialog(files, cur, self).exec()

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
        RandomPickDialog(self.model, self._translate_entry, self).exec()

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
        self.model.set_filter(q, self._search_mode, self._search_scope)
        self.entry_view.set_drag_enabled(not q)
        self._update_stats()

    def _focus_search(self) -> None:
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def _clear_search(self) -> None:
        """Esc：清空搜索框并聚焦到条目列表。"""
        self.search_edit.clear()
        self.entry_view.setFocus()

    def _set_search_mode(self, mode: str) -> None:
        self._search_mode = mode
        self._apply_filter()

    def _set_search_scope(self, scope: str) -> None:
        self._search_scope = scope
        self._apply_filter()

    def copy_selected(self) -> None:
        """复制选中的条目文本到剪贴板（每行一个）。"""
        if self.model is None:
            return
        rows = sorted({i.row() for i in self.entry_view.selectionModel().selectedIndexes()})
        if not rows:
            QMessageBox.information(self, "复制选中", "请先选中要复制的条目。")
            return
        texts = [self.model.entry_at(r).text for r in rows]
        QApplication.clipboard().setText("\n".join(texts))
        self.statusBar().showMessage(f"已复制 {len(texts)} 条到剪贴板", 3000)

    def _autosave(self) -> None:
        """每步操作后自动保存（编辑中暂缓，避免打断输入）。"""
        if self.library is None or self.library.path is None:
            return
        if self.entry_view.state() == QAbstractItemView.EditingState:
            self._autosave_timer.start()  # 正在编辑，稍后再试
            return
        if self.library.dirty:
            self.save_library()

    def _on_compact_toggled(self, on: bool) -> None:
        self.entry_view.set_layout("compact" if on else "split")

    def _clear_selection(self) -> None:
        self.entry_view.clearSelection()
        self.entry_view.setFocus()

    def _update_selection_buttons(self, *_args) -> None:
        """无选中时禁用取消选中 / 复制选中 / 删除选中。"""
        has_sel = self.entry_view.selectionModel().hasSelection()
        self.btn_clear_sel.setEnabled(has_sel)
        self.btn_copy_sel.setEnabled(has_sel)
        self.btn_delete.setEnabled(has_sel)

    # ================= 最近打开 =================

    def _add_recent_folder(self, folder: Path) -> None:
        cur = self.settings.value("recent_folders", [])
        if isinstance(cur, str):
            cur = [cur]
        cur = [str(f) for f in cur if f]
        s = str(folder.resolve())
        cur = [s] + [f for f in cur if f != s]
        self.settings.setValue("recent_folders", cur[:8])

    def _build_recent_menu(self) -> None:
        menu = self.sender()
        menu.clear()
        folders = self.settings.value("recent_folders", [])
        if isinstance(folders, str):
            folders = [folders]
        folders = [f for f in folders if f and Path(f).is_dir()]
        if not folders:
            a = menu.addAction("（暂无记录）")
            a.setEnabled(False)
            return
        for f in folders:
            menu.addAction(f, lambda _=False, path=f: self.open_folder(Path(path), autoload_first=True))
        menu.addSeparator()
        menu.addAction("清空记录", self._clear_recent)

    def _clear_recent(self) -> None:
        self.settings.remove("recent_folders")

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
            self.setWindowTitle("词库管理器")
            self.current_file_label.setText("未打开词库")
            self.current_file_label.setToolTip("")
            return
        mark = "● " if self.library.dirty else ""
        self.setWindowTitle(f"{mark}{self.library.name()} — 词库管理器")
        self.current_file_label.setText(f"{mark}{self.library.name()}")
        self.current_file_label.setToolTip(str(self.library.path))

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
        parts.append(f"翻译 {c['translated']}/{c['total']}")
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
            menu.addAction("在线翻译", lambda: self.translate_selected(ai=True))
            menu.addAction("离线词典翻译", lambda: self.translate_selected(ai=False))
            menu.addAction("编辑翻译…", self.edit_translation)
            menu.addAction("复制到其他词库…", lambda: self.move_copy_entries())
            menu.addAction("移动到其他词库…", lambda: self.move_copy_entries(move=True))
            menu.addSeparator()
            menu.addAction("删除", self.delete_selected)
        elif len(rows) > 1:
            texts = "\n".join(self.model.entry_at(r).text for r in rows)
            menu.addAction(f"复制 {len(rows)} 条", lambda: QApplication.clipboard().setText(texts))
            menu.addAction(f"在线翻译 {len(rows)} 条", lambda: self.translate_selected(ai=True))
            menu.addAction("复制到其他词库…", lambda: self.move_copy_entries())
            menu.addAction("移动到其他词库…", lambda: self.move_copy_entries(move=True))
            menu.addSeparator()
            menu.addAction(f"删除 {len(rows)} 条", lambda: self.delete_selected(confirm_needed=True))
        else:
            menu.addAction("新增条目", self.add_entry)
        menu.exec(self.entry_view.viewport().mapToGlobal(pos))

    # ================= 其他 =================

    def _help(self) -> None:
        QMessageBox.about(
            self,
            "帮助",
            "<b>词库管理器（Prompt Library Manager）</b><br><br>"
            "用于管理 ComfyUI Wildcard / 文本列表词库的本地 TXT 工具。<br>"
            "整行 = 一个随机候选项，导出 TXT 只输出原始文本。<br><br>"
            "Phase 1：打开/搜索/增删改/批量删除/去重/排序/<br>"
            "　　　　导入导出/随机抽取/编码识别/外部修改检测<br>"
            "Phase 2：批量替换、跨词库复制/移动<br>"
            "Phase 3：双语显示、离线词典、在线翻译、翻译状态标记<br>"
            "Phase 4：CSV 英中导入导出、Tag 统计、词库合并、差异比较<br>"
            "Phase 5：虚拟列表性能优化、桌面打包<br><br>"
            'GitHub：<a href="https://github.com/befoer/prompt-library-manager">'
            "https://github.com/befoer/prompt-library-manager</a>",
        )

    def _restore_settings(self) -> None:
        geo = self.settings.value("geometry")
        if geo:
            self.restoreGeometry(geo)
        state = self.settings.value("splitter_v2")
        if state:
            self.splitter.restoreState(state)

    def closeEvent(self, event) -> None:
        if not self._guard_unsaved():
            event.ignore()
            return
        self._flush_sidecar()
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("splitter_v2", self.splitter.saveState())
        event.accept()
