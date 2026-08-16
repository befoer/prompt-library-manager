"""翻译设置、批量替换、跨词库复制/移动、编辑翻译等对话框。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.core.ai_translate import AIConfig, translate_baidu_batch, translate_openai_batch
from app.core.dictionary import OfflineDictionary


class TranslationSettingsDialog(QDialog):
    """AI 翻译配置（OpenAI 兼容 / 百度翻译）+ 词典目录 + 缓存管理。"""

    def __init__(self, cfg: AIConfig, dictionary: OfflineDictionary, cache, parent=None):
        super().__init__(parent)
        self.setWindowTitle("翻译设置")
        self.setMinimumWidth(460)
        self.cfg = cfg
        self.dictionary = dictionary
        self.cache = cache

        lay = QVBoxLayout(self)
        self.chk_enable = QCheckBox("启用在线翻译")
        lay.addWidget(self.chk_enable)

        form = QFormLayout()
        self.combo_provider = QComboBox()
        self.combo_provider.addItem("OpenAI 兼容 API", "openai")
        self.combo_provider.addItem("百度翻译", "baidu")
        form.addRow("接口类型", self.combo_provider)

        self.edit_base = QLineEdit()
        self.edit_key = QLineEdit()
        self.edit_key.setEchoMode(QLineEdit.Password)
        self.edit_model = QLineEdit()
        self.spin_conc = QSpinBox()
        self.spin_conc.setRange(1, 16)
        self.spin_conc.setValue(cfg.concurrency)
        self.spin_batch = QSpinBox()
        self.spin_batch.setRange(1, 100)
        self.spin_batch.setValue(cfg.batch_size)
        form.addRow("Base URL", self.edit_base)
        form.addRow("API Key", self.edit_key)
        form.addRow("Model", self.edit_model)
        form.addRow("并发数", self.spin_conc)
        form.addRow("每批条数", self.spin_batch)

        self.edit_appid = QLineEdit()
        self.edit_secret = QLineEdit()
        self.edit_secret.setEchoMode(QLineEdit.Password)
        form.addRow("百度 AppID", self.edit_appid)
        form.addRow("百度密钥", self.edit_secret)
        lay.addLayout(form)

        # 词典目录
        dict_row = QHBoxLayout()
        self.edit_dict_dir = QLineEdit()
        self.edit_dict_dir.setReadOnly(True)
        btn_dict = QPushButton("选择目录…")
        btn_dict.clicked.connect(self._pick_dict_dir)
        self.btn_reload = QPushButton("重新加载")
        self.btn_reload.clicked.connect(self._reload_dict)
        dict_row.addWidget(QLabel("离线词典目录"))
        dict_row.addWidget(self.edit_dict_dir, 1)
        dict_row.addWidget(btn_dict)
        dict_row.addWidget(self.btn_reload)
        lay.addLayout(dict_row)
        self.lbl_dict = QLabel()
        self.lbl_dict.setWordWrap(True)
        lay.addWidget(self.lbl_dict)

        # 缓存
        cache_row = QHBoxLayout()
        self.lbl_cache = QLabel()
        btn_clear_cache = QPushButton("清空翻译缓存")
        btn_clear_cache.clicked.connect(self._clear_cache)
        cache_row.addWidget(self.lbl_cache, 1)
        cache_row.addWidget(btn_clear_cache)
        lay.addLayout(cache_row)

        # 测试
        test_row = QHBoxLayout()
        btn_test = QPushButton("测试连接")
        btn_test.clicked.connect(self._test_connection)
        test_row.addStretch(1)
        test_row.addWidget(btn_test)
        lay.addLayout(test_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self._load_from_cfg()
        self.edit_key.textChanged.connect(self._on_provider_fields_changed)
        self.edit_appid.textChanged.connect(self._on_provider_fields_changed)
        self.edit_secret.textChanged.connect(self._on_provider_fields_changed)

    def _on_provider_fields_changed(self, *_args) -> None:
        """填了百度 AppID/密钥却没填 API Key 时，自动把接口类型切到百度。"""
        if (not self.edit_key.text().strip()
                and self.edit_appid.text().strip()
                and self.edit_secret.text().strip()
                and self.combo_provider.currentData() != "baidu"):
            self.combo_provider.setCurrentIndex(self.combo_provider.findData("baidu"))

    # ---------- 加载 / 保存 ----------

    def _load_from_cfg(self) -> None:
        c = self.cfg
        self.chk_enable.setChecked(c.enabled)
        idx = self.combo_provider.findData(c.provider)
        self.combo_provider.setCurrentIndex(max(0, idx))
        self.edit_base.setText(c.base_url)
        self.edit_key.setText(c.api_key)
        self.edit_model.setText(c.model)
        self.spin_conc.setValue(c.concurrency)
        self.spin_batch.setValue(c.batch_size)
        self.edit_appid.setText(c.baidu_appid)
        self.edit_secret.setText(c.baidu_secret)
        dirs = self.dictionary.dirs
        self.edit_dict_dir.setText(str(dirs[0]) if dirs else "")
        self._refresh_dict_status()

    def _refresh_dict_status(self) -> None:
        if self.dictionary.loaded:
            self.lbl_dict.setText(
                f"已加载：中文词条 {self.dictionary.zh_count:,}，别名 {self.dictionary.alias_count:,}"
                + (f"\n⚠ {self.dictionary.error}" if self.dictionary.error else "")
            )
        else:
            self.lbl_dict.setText("词典未加载" + (f"（{self.dictionary.error}）" if self.dictionary.error else ""))
        self.lbl_cache.setText(f"翻译缓存：{len(self.cache.data):,} 条")

    def _pick_dict_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择词典目录（含 zh-CN.txt 等）",
                                             self.edit_dict_dir.text())
        if d:
            self.edit_dict_dir.setText(d)
            self.dictionary.dirs = [Path(d)]
            self._reload_dict()

    def _reload_dict(self) -> None:
        self.dictionary.load()
        self._refresh_dict_status()

    def _clear_cache(self) -> None:
        self.cache.clear()
        self._refresh_dict_status()

    def _test_connection(self) -> None:
        cfg = self._collect_cfg()
        err = cfg.validate()
        if err:
            QMessageBox.warning(self, "测试连接", err)
            return
        try:
            if cfg.provider == "baidu":
                out = translate_baidu_batch(["hello world"], cfg)
            else:
                out = translate_openai_batch(["hello world"], cfg)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "测试连接", f"请求失败：\n{exc}")
            return
        QMessageBox.information(self, "测试连接", f"成功！\nhello world → {out[0] if out else ''}")

    def _collect_cfg(self) -> AIConfig:
        c = AIConfig(
            enabled=self.chk_enable.isChecked(),
            provider=str(self.combo_provider.currentData()),
            base_url=self.edit_base.text().strip(),
            api_key=self.edit_key.text().strip(),
            model=self.edit_model.text().strip(),
            concurrency=self.spin_conc.value(),
            batch_size=self.spin_batch.value(),
            baidu_appid=self.edit_appid.text().strip(),
            baidu_secret=self.edit_secret.text().strip(),
        )
        c.normalize()
        return c

    def result_cfg(self) -> AIConfig:
        return self._collect_cfg()


class BatchReplaceDialog(QDialog):
    """批量替换：查找/替换 + 作用范围（当前词库 / 所有词库）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批量替换")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.edit_find = QLineEdit()
        self.edit_repl = QLineEdit()
        form.addRow("查找", self.edit_find)
        form.addRow("替换为", self.edit_repl)
        lay.addLayout(form)

        self.radio_current = QRadioButton("当前词库（可撤销）")
        self.radio_current.setChecked(True)
        self.radio_all = QRadioButton("所有词库（直接写入文件，不可撤销）")
        lay.addWidget(self.radio_current)
        lay.addWidget(self.radio_all)
        note = QLabel("不区分大小写；执行前会先显示匹配数量并确认。")
        note.setStyleSheet("color:#8a8a8a;")
        lay.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("下一步")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def values(self) -> tuple[str, str, str]:
        return self.edit_find.text(), self.edit_repl.text(), \
            ("all" if self.radio_all.isChecked() else "current")


class MoveCopyDialog(QDialog):
    """跨词库批量复制 / 移动。"""

    def __init__(self, targets: list[tuple[str, str]], count: int, default_move: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("复制 / 移动到其他词库")
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        self.radio_copy = QRadioButton(f"复制 {count} 条")
        self.radio_move = QRadioButton(f"移动 {count} 条（源词库可用 Ctrl+Z 撤销）")
        if default_move:
            self.radio_move.setChecked(True)
        else:
            self.radio_copy.setChecked(True)
        lay.addWidget(self.radio_copy)
        lay.addWidget(self.radio_move)
        form = QFormLayout()
        self.combo_target = QComboBox()
        for name, path in targets:
            self.combo_target.addItem(name, path)
        form.addRow("目标词库", self.combo_target)
        lay.addLayout(form)
        note = QLabel("目标词库直接写入文件（跨词库操作，目标侧不提供撤销）。")
        note.setStyleSheet("color:#8a8a8a;")
        lay.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def result(self) -> tuple[str, str]:
        """返回 (mode, target_path)。mode: copy | move"""
        mode = "move" if self.radio_move.isChecked() else "copy"
        return mode, str(self.combo_target.currentData())


class EditTranslationDialog(QDialog):
    """手动编辑单条翻译。"""

    def __init__(self, english: str, chinese: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑翻译")
        self.setMinimumSize(460, 220)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"英文：{english}"))
        self.edit = QPlainTextEdit()
        self.edit.setPlainText(chinese)
        lay.addWidget(self.edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def text(self) -> str:
        return self.edit.toPlainText().strip()
