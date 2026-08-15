"""左侧词库列表面板：打开文件夹 / 新建 / 重命名 / 删除 / 刷新 / 右键菜单。"""
from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class SidebarPanel(QWidget):
    open_folder_requested = Signal()
    new_library_requested = Signal()
    refresh_requested = Signal()
    open_requested = Signal(str)       # path
    rename_requested = Signal(str)     # path
    delete_requested = Signal(str)     # path

    def __init__(self, parent=None):
        super().__init__(parent)
        self.folder: Path | None = None
        self._current: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        title = QLabel("📁 Prompt Libraries")
        title.setObjectName("sideTitle")
        layout.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(4)
        self.btn_open_folder = QToolButton(self, text="打开文件夹")
        self.btn_new = QToolButton(self, text="＋新建")
        self.btn_rename = QToolButton(self, text="重命名")
        self.btn_delete = QToolButton(self, text="删除")
        self.btn_refresh = QToolButton(self, text="刷新")
        for b in (self.btn_open_folder, self.btn_new, self.btn_rename, self.btn_delete, self.btn_refresh):
            row.addWidget(b)
        layout.addLayout(row)

        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SingleSelection)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.setAcceptDrops(False)
        layout.addWidget(self.list, 1)

        self.btn_open_folder.clicked.connect(self.open_folder_requested)
        self.btn_new.clicked.connect(self.new_library_requested)
        self.btn_refresh.clicked.connect(self.refresh_requested)
        self.list.itemDoubleClicked.connect(lambda item: self.open_requested.emit(item.data(Qt.UserRole)))
        self.list.customContextMenuRequested.connect(self._context_menu)

    # ---------- 列表内容 ----------

    def set_folder(self, folder: Path) -> None:
        self.folder = folder
        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        if not self.folder:
            return
        try:
            files = sorted(
                (p for p in self.folder.iterdir() if p.is_file() and p.suffix.lower() == ".txt"),
                key=lambda p: p.name.casefold(),
            )
        except OSError:
            return
        for p in files:
            item = QListWidgetItem(p.name)
            item.setData(Qt.UserRole, str(p))
            item.setToolTip(str(p))
            self.list.addItem(item)
        self._apply_current_marker()

    def paths(self) -> list[str]:
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]

    def first_path(self) -> str | None:
        return self.paths()[0] if self.list.count() else None

    def selected_path(self) -> str | None:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def select_path(self, path: Path) -> None:
        target = str(path)
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) == target:
                self.list.setCurrentItem(self.list.item(i))
                break
        self.set_current(path)

    def set_current(self, path: Path | None) -> None:
        """标记当前正在编辑的词库（加粗 + 强调色 + ▸ 前缀）。"""
        self._current = str(path) if path is not None else None
        self._apply_current_marker()

    def _apply_current_marker(self) -> None:
        bold = QFont(self.list.font())
        bold.setBold(True)
        for i in range(self.list.count()):
            item = self.list.item(i)
            p = item.data(Qt.UserRole)
            name = Path(p).name
            if p == self._current:
                item.setText("▸ " + name)
                item.setFont(bold)
                item.setForeground(QColor("#4fc3f7"))
            else:
                item.setText(name)
                item.setFont(self.list.font())
                item.setForeground(QBrush())

    # ---------- 右键菜单 ----------

    def _context_menu(self, pos) -> None:
        item = self.list.itemAt(pos)
        menu = QMenu(self)
        if item is not None:
            path = item.data(Qt.UserRole)
            menu.addAction("打开", lambda: self.open_requested.emit(path))
            menu.addAction("重命名", lambda: self.rename_requested.emit(path))
            menu.addAction("删除", lambda: self.delete_requested.emit(path))
            menu.addSeparator()
            menu.addAction("在文件夹中显示", lambda: self._reveal(path))
        else:
            menu.addAction("打开词库文件夹", self.open_folder_requested)
            menu.addAction("新建词库", self.new_library_requested)
            menu.addAction("刷新", self.refresh_requested)
        menu.exec(self.list.viewport().mapToGlobal(pos))

    @staticmethod
    def _reveal(path: str) -> None:
        try:
            subprocess.Popen(["explorer", "/select,", path])
        except OSError:
            pass
