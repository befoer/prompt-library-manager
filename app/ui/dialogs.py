"""对话框：随机抽取（单条/多条）、差异查看、确认提示。"""
from __future__ import annotations

import difflib
import random

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
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


class ExportDialog(QDialog):
    """导出 TXT：选择格式（直接导出 / 附带中文翻译）与分隔符。"""

    def __init__(self, entries, default_sep: str = ", ", parent=None):
        super().__init__(parent)
        self._preview = list(entries[:2])
        self.setWindowTitle("导出 TXT")
        self.setMinimumWidth(460)

        lay = QVBoxLayout(self)

        # 格式选择：两个可点击的切换按钮（更直观）
        self.btn_direct = QPushButton("直接导出（仅原文）")
        self.btn_with_zh = QPushButton("原文 + 中文翻译")
        for b in (self.btn_direct, self.btn_with_zh):
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                "QPushButton { padding:7px 14px; border:1px solid #3c3c3c; "
                "border-radius:4px; background:#2d2d2d; color:#d4d4d4; }"
                "QPushButton:checked { background:#094771; color:#ffffff; "
                "border:1px solid #4fc3f7; font-weight:600; }"
            )
        self.btn_direct.setChecked(True)
        self.fmt_group = QButtonGroup(self)
        self.fmt_group.setExclusive(True)
        self.fmt_group.addButton(self.btn_direct)
        self.fmt_group.addButton(self.btn_with_zh)

        fmt_row = QHBoxLayout()
        fmt_row.addWidget(self.btn_direct)
        fmt_row.addWidget(self.btn_with_zh)
        fmt_row.addStretch(1)
        lay.addLayout(fmt_row)

        # 分隔符（仅"原文 + 中文翻译"时显示）
        self.sep_widget = QWidget()
        sep_row = QHBoxLayout(self.sep_widget)
        sep_row.setContentsMargins(0, 6, 0, 0)
        sep_row.addWidget(QLabel("分隔符："))
        self.edit_sep = QLineEdit(default_sep)
        self.edit_sep.setToolTip("原文与中文翻译之间的分隔符")
        sep_row.addWidget(self.edit_sep)
        lay.addWidget(self.sep_widget)

        # 预览
        self.lbl_preview = QLabel()
        self.lbl_preview.setStyleSheet("color:#93a7b3;")
        lay.addWidget(self.lbl_preview)

        # 按钮
        row = QHBoxLayout()
        btn_ok = QPushButton("导出")
        btn_cancel = QPushButton("取消")
        btn_ok.setDefault(True)
        row.addStretch(1)
        row.addWidget(btn_ok)
        row.addWidget(btn_cancel)
        lay.addLayout(row)

        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)

        self.btn_direct.toggled.connect(self._update)
        self.edit_sep.textChanged.connect(self._update)
        self._update()

    def _update(self) -> None:
        with_zh = self.btn_with_zh.isChecked()
        self.sep_widget.setVisible(with_zh)
        sep = self.edit_sep.text()
        lines = []
        for e in self._preview:
            if with_zh and e.translation:
                lines.append(f"{e.text}{sep}{e.translation}")
            else:
                lines.append(e.text)
        lines.append("...")
        self.lbl_preview.setText("预览：\n" + "\n".join(lines))

    def result(self) -> tuple[str, str]:
        """返回 (format, separator)。format 为 'direct' 或 'with_zh'。"""
        fmt = "with_zh" if self.btn_with_zh.isChecked() else "direct"
        return fmt, self.edit_sep.text()


class RandomPickDialog(QDialog):
    """🎲 随机抽取 1 条（含翻译结果 / 翻译按钮）。"""

    def __init__(self, model: EntryListModel, translate_fn, parent=None):
        super().__init__(parent)
        self.model = model
        self.translate_fn = translate_fn  # 回调：translate_fn(entry_id)
        self._current_id: str | None = None
        self.setWindowTitle("🎲 随机抽取")
        self.setMinimumWidth(560)

        lay = QVBoxLayout(self)
        self.text_label = QLabel()
        self.text_label.setObjectName("bigText")
        self.text_label.setWordWrap(False)
        self.text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.text_label)

        # 翻译结果
        self.trans_label = QLabel()
        self.trans_label.setWordWrap(True)
        self.trans_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.trans_label.setStyleSheet(
            "color:#93a7b3; font-family:'Microsoft YaHei UI'; font-size:13px;"
        )
        lay.addWidget(self.trans_label)

        self.btn_translate = QPushButton("翻译")
        self.btn_translate.clicked.connect(self._translate)
        lay.addWidget(self.btn_translate, 0, Qt.AlignLeft)

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

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(400)
        self._poll_timer.timeout.connect(self._poll_translation)
        self._pick()

    def _pick(self) -> None:
        self._poll_timer.stop()
        visible = self.model.visible
        if not visible:
            self.text_label.setText("（当前列表为空，无法抽取）")
            self.trans_label.clear()
            self.trans_label.setVisible(False)
            self.btn_translate.setVisible(False)
            self.btn_again.setEnabled(False)
            return
        self.btn_again.setEnabled(True)
        idx = random.choice(visible)
        entry = self.model.library.entries[idx]
        self._current_id = entry.id
        self.text_label.setText(entry.text)
        self._show_translation(entry.translation)

    def _show_translation(self, translation: str) -> None:
        if translation:
            self.trans_label.setText(translation)
            self.trans_label.setVisible(True)
            self.btn_translate.setVisible(False)
        else:
            self.trans_label.setVisible(False)
            self.btn_translate.setVisible(True)
            self.btn_translate.setEnabled(True)
            self.btn_translate.setText("翻译")

    def _translate(self) -> None:
        if self._current_id is None:
            return
        self.btn_translate.setEnabled(False)
        self.btn_translate.setText("翻译中…")
        self.translate_fn(self._current_id)
        self._poll_timer.start()

    def _poll_translation(self) -> None:
        entry = self.model.library.get(self._current_id) if self._current_id else None
        if entry is not None and entry.translation:
            self._poll_timer.stop()
            self._show_translation(entry.translation)

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
