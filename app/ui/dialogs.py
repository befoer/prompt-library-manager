"""对话框：随机抽取（单条/多条）、差异查看、确认提示。"""
from __future__ import annotations

import difflib
import random

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from app.ui.entry_model import EntryListModel

DIFF_CAP = 20000


def confirm(parent, title: str, text: str, ok_text: str = "确定", cancel_text: str = "取消") -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    ok_btn = box.addButton(ok_text, QMessageBox.AcceptRole)
    box.addButton(cancel_text, QMessageBox.RejectRole)
    box.setDefaultButton(ok_btn)
    box.exec()
    return box.clickedButton() is ok_btn


class RandomPickDialog(QDialog):
    """🎲 随机抽取 1 条。"""

    def __init__(self, model: EntryListModel, parent=None):
        super().__init__(parent)
        self.model = model
        self.setWindowTitle("🎲 随机抽取")
        self.setMinimumWidth(560)

        lay = QVBoxLayout(self)
        self.text_label = QLabel()
        self.text_label.setObjectName("bigText")
        self.text_label.setWordWrap(False)
        self.text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.text_label)

        hint = QLabel("从当前列表（含筛选结果）中随机抽取一条，整行为一个候选项。")
        hint.setStyleSheet("color:#9d9d9d;")
        lay.addWidget(hint)

        row = QHBoxLayout()
        self.btn_again = QPushButton("再抽一次")
        self.btn_copy = QPushButton("复制")
        self.btn_close = QPushButton("关闭")
        self.btn_again.setDefault(True)
        row.addWidget(self.btn_again)
        row.addWidget(self.btn_copy)
        row.addStretch(1)
        row.addWidget(self.btn_close)
        lay.addLayout(row)

        self.btn_again.clicked.connect(self._pick)
        self.btn_copy.clicked.connect(self._copy)
        self.btn_close.clicked.connect(self.accept)
        self._pick()

    def _pick(self) -> None:
        texts = self.model.visible_texts()
        if not texts:
            self.text_label.setText("（当前列表为空，无法抽取）")
            self.btn_again.setEnabled(False)
            return
        self.btn_again.setEnabled(True)
        self.text_label.setText(random.choice(texts))

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.text_label.text())


class RandomBatchDialog(QDialog):
    """🎲 随机抽取 N 条。"""

    def __init__(self, model: EntryListModel, parent=None):
        super().__init__(parent)
        self.model = model
        self.setWindowTitle("🎲 随机抽取多条")
        self.resize(560, 420)

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("抽取条数："))
        self.spin = QSpinBox()
        self.spin.setRange(1, 100)
        self.spin.setValue(10)
        top.addWidget(self.spin)
        top.addStretch(1)
        lay.addLayout(top)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.text_edit.setStyleSheet("font-family: Consolas; font-size: 13px;")
        lay.addWidget(self.text_edit, 1)

        row = QHBoxLayout()
        self.btn_again = QPushButton("再抽一次")
        self.btn_copy = QPushButton("复制全部")
        self.btn_close = QPushButton("关闭")
        self.btn_again.setDefault(True)
        row.addWidget(self.btn_again)
        row.addWidget(self.btn_copy)
        row.addStretch(1)
        row.addWidget(self.btn_close)
        lay.addLayout(row)

        self.btn_again.clicked.connect(self._pick)
        self.btn_copy.clicked.connect(self._copy)
        self.btn_close.clicked.connect(self.accept)
        self._pick()

    def _pick(self) -> None:
        texts = self.model.visible_texts()
        if not texts:
            self.text_edit.setPlainText("（当前列表为空，无法抽取）")
            return
        n = min(self.spin.value(), len(texts))
        picked = random.sample(texts, n)
        self.text_edit.setPlainText("\n".join(f"{i + 1}. {t}" for i, t in enumerate(picked)))

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.text_edit.toPlainText())


class DiffDialog(QDialog):
    """外部修改差异查看（磁盘版本 vs 内存版本）。"""

    def __init__(self, title: str, old_text: str, new_text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(820, 600)

        lay = QVBoxLayout(self)
        hint = QLabel("「-」= 磁盘上的版本　「+」= 当前内存中的版本")
        hint.setStyleSheet("color:#9d9d9d;")
        lay.addWidget(hint)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.text_edit.setStyleSheet("font-family: Consolas; font-size: 12px;")
        diff = list(
            difflib.unified_diff(
                old_text.splitlines(),
                new_text.splitlines(),
                "磁盘版本",
                "内存版本",
                lineterm="",
            )
        )
        if len(diff) > DIFF_CAP:
            diff = diff[:DIFF_CAP] + [f"…（差异过大，仅显示前 {DIFF_CAP} 行）"]
        self.text_edit.setPlainText("\n".join(diff))
        lay.addWidget(self.text_edit, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        row.addWidget(btn_close)
        lay.addLayout(row)
