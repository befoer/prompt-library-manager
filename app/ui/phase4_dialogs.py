"""Phase 4 对话框：Tag 统计、词库合并、词库差异比较。"""
from __future__ import annotations

import difflib
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QApplication,
)

DIFF_CAP = 20000
SET_DIFF_LIMIT = 50000


def compute_tag_stats(library) -> list[tuple[str, int]]:
    """统计词库内 tag 频率（按逗号拆分，不区分大小写计数，保留首次出现的写法）。"""
    counter: dict[str, int] = {}
    display: dict[str, str] = {}
    for e in library.entries:
        for tag in e.text.split(","):
            t = tag.strip()
            if not t:
                continue
            key = t.casefold()
            counter[key] = counter.get(key, 0) + 1
            display.setdefault(key, t)
    return [(display[k], c) for k, c in counter.items()]


def compute_diff(old_lines: list[str], new_lines: list[str]) -> tuple[int, int, list[str]]:
    """返回 (新增条数, 删除条数, diff 行)。超大词库退回顺序无关的集合统计。"""
    if len(old_lines) > SET_DIFF_LIMIT or len(new_lines) > SET_DIFF_LIMIT:
        sa, sb = set(old_lines), set(new_lines)
        return len(sb - sa), len(sa - sb), []
    sm = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    added = removed = 0
    out: list[str] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if tag in ("insert", "replace"):
            added += j2 - j1
            for j in range(j1, j2):
                out.append(f"+ {new_lines[j]}")
        if tag in ("delete", "replace"):
            removed += i2 - i1
            for i in range(i1, i2):
                out.append(f"- {old_lines[i]}")
        if len(out) >= DIFF_CAP:
            out.append(f"…（差异过大，仅显示前 {DIFF_CAP} 行）")
            break
    return added, removed, out


class TagStatsDialog(QDialog):
    """Tag 频率统计（只读分析，不会拆分条目）。"""

    def __init__(self, library, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tag 统计（当前词库）")
        self.resize(560, 520)
        self.library = library
        self.stats = compute_tag_stats(library)

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("显示前："))
        self.spin = QSpinBox()
        self.spin.setRange(1, 5000)
        self.spin.setValue(200)
        top.addWidget(self.spin)
        top.addWidget(QLabel("个 tag（共 %d 个不同 tag）" % len(self.stats)))
        top.addStretch(1)
        lay.addLayout(top)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.text_edit.setStyleSheet("font-family: Consolas; font-size: 12px;")
        lay.addWidget(self.text_edit, 1)

        row = QHBoxLayout()
        btn_copy = QPushButton("复制")
        btn_close = QPushButton("关闭")
        btn_close.setDefault(True)
        row.addWidget(btn_copy)
        row.addStretch(1)
        row.addWidget(btn_close)
        lay.addLayout(row)

        self.spin.valueChanged.connect(self._refresh)
        btn_copy.clicked.connect(self._copy)
        btn_close.clicked.connect(self.accept)
        self._refresh()

    def _refresh(self) -> None:
        n = self.spin.value()
        rows = sorted(self.stats, key=lambda x: (-x[1], x[0].casefold()))[:n]
        self.text_edit.setPlainText(
            "\n".join(f"{t}\t{c}" for t, c in rows) + f"\n\n共 {len(self.stats):,} 个不同 tag"
        )

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.text_edit.toPlainText())


class MergeDialog(QDialog):
    """词库合并：勾选多个词库，合并到当前词库（可撤销）或另存为新文件。"""

    def __init__(self, files: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("词库合并")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("选择要合并的词库（可多选）："))
        self.checks: list[QCheckBox] = []
        for name, path in files:
            cb = QCheckBox(name)
            cb.setToolTip(path)
            self.checks.append(cb)
            lay.addWidget(cb)

        self.chk_dedupe = QCheckBox("合并时去重（保留首次出现的条目）")
        self.chk_dedupe.setChecked(True)
        lay.addWidget(self.chk_dedupe)

        self.radio_current = QRadioButton("合并到当前词库（可撤销）")
        self.radio_current.setChecked(True)
        self.radio_new = QRadioButton("另存为新文件")
        lay.addWidget(self.radio_current)
        lay.addWidget(self.radio_new)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def selected_paths(self) -> list[str]:
        return [cb.toolTip() for cb in self.checks if cb.isChecked()]

    def to_new_file(self) -> bool:
        return self.radio_new.isChecked()

    def dedupe(self) -> bool:
        return self.chk_dedupe.isChecked()


class CompareDialog(QDialog):
    """词库差异比较：两个 TXT 的增删行统计 + 统一 diff 预览。"""

    def __init__(self, files: list[tuple[str, str]], current_path: str | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("词库差异比较")
        self.resize(820, 600)
        self.files = files

        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.combo_a = QComboBox()
        self.combo_b = QComboBox()
        for name, path in files:
            self.combo_a.addItem(name, path)
            self.combo_b.addItem(name, path)
        if current_path:
            for i, (_n, p) in enumerate(files):
                if p == current_path:
                    self.combo_a.setCurrentIndex(i)
                    break
            if len(files) > 1:
                self.combo_b.setCurrentIndex(1 if self.combo_a.currentIndex() != 1 else 0)
        form.addRow("文件 A", self.combo_a)
        form.addRow("文件 B", self.combo_b)
        lay.addLayout(form)

        self.lbl_summary = QLabel("")
        lay.addWidget(self.lbl_summary)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.text_edit.setStyleSheet("font-family: Consolas; font-size: 12px;")
        lay.addWidget(self.text_edit, 1)

        row = QHBoxLayout()
        btn_copy = QPushButton("复制 diff")
        btn_close = QPushButton("关闭")
        btn_close.setDefault(True)
        row.addWidget(btn_copy)
        row.addStretch(1)
        row.addWidget(btn_close)
        lay.addLayout(row)

        self.combo_a.currentIndexChanged.connect(self._compare)
        self.combo_b.currentIndexChanged.connect(self._compare)
        btn_copy.clicked.connect(self._copy)
        btn_close.clicked.connect(self.accept)
        self._compare()

    def _compare(self) -> None:
        pa = Path(self.combo_a.currentData())
        pb = Path(self.combo_b.currentData())
        from app.core import io

        try:
            la, _ = io.read_lines(pa)
            lb, _ = io.read_lines(pb)
        except OSError as e:
            self.lbl_summary.setText(f"读取失败：{e}")
            return

        added, removed, diff_lines = compute_diff(la, lb)
        if not diff_lines and (len(la) > SET_DIFF_LIMIT or len(lb) > SET_DIFF_LIMIT):
            self.lbl_summary.setText(
                f"A={len(la):,} 行，B={len(lb):,} 行　＋新增 {added:,}　－删除 {removed:,}\n"
                "（词库过大，按行集合统计，未显示逐行 diff）"
            )
            self.text_edit.setPlainText("")
            return
        self.lbl_summary.setText(
            f"A={len(la):,} 行（{pa.name}）　B={len(lb):,} 行（{pb.name}）\n"
            f"＋新增 {added:,} 条　－删除 {removed:,} 条"
        )
        self.text_edit.setPlainText("\n".join(diff_lines) if diff_lines else "（两个词库内容一致）")

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.text_edit.toPlainText())
