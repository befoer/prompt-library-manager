"""离线英中词典。

数据来源（Tags 目录）：
- zh-CN.txt      ：`english=中文` 每行一条（UTF-8），约 2.5 万条，是主词典。
- danbooru.csv   ：`规范tag,?,次数,"别名1,别名2,..."`，用于把别名归一化到规范 tag。
- e621.csv       ：同上，e621 风格。

查询策略（按条 Entry，整行为单位）：
1. 整行查词典（下划线→空格、忽略大小写）。
2. 未命中则查别名表，归一化后再查。
3. 仍不命中且行内含逗号 → 按 tag 拆开逐项翻译后拼接（缺词保留英文）。
4. 都不是 → 返回 None（交给 AI 翻译）。
"""
from __future__ import annotations

import csv
import sys
import threading
from pathlib import Path


def default_tags_dirs() -> list[Path]:
    """候选词典目录：打包后的 exe 目录 / _internal / 开发目录。"""
    cands: list[Path] = []
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
        cands.extend([base / "Tags", base / "_internal" / "Tags"])
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            cands.append(Path(meipass) / "Tags")
    cands.append(Path(__file__).resolve().parent.parent.parent / "Tags")
    return cands


class OfflineDictionary:
    """离线词典（线程安全，惰性加载）。"""

    def __init__(self, dirs: list[Path] | None = None):
        self.dirs: list[Path] = [d for d in (dirs or []) if d]
        self._zh: dict[str, str] = {}
        self._alias: dict[str, str] = {}
        self._loaded = False
        self._load_error: str | None = None
        self._lock = threading.Lock()

    # ---------- 加载 ----------

    def load(self) -> tuple[int, int]:
        """加载词典，返回 (中文词条数, 别名数)。可重复调用（重载）。"""
        with self._lock:
            self._zh.clear()
            self._alias.clear()
            self._load_error = None
            # 取第一个含 zh-CN.txt 的目录（打包后优先 exe 旁目录）
            source: Path | None = None
            for d in self.dirs:
                if d.is_dir() and (d / "zh-CN.txt").exists():
                    source = d
                    break
            if source is None:
                self._load_error = "未找到 zh-CN.txt（需要 Tags 目录或翻译设置中指定）"
                self._loaded = True
                return 0, 0
            zh_file = source / "zh-CN.txt"
            alias_files = [
                f for f in (source / "danbooru.csv", source / "e621.csv") if f.exists()
            ]
            try:
                text = zh_file.read_text(encoding="utf-8")
                for line in text.splitlines():
                    line = line.strip()
                    if not line or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = _norm(k)
                    v = v.strip()
                    if k and v:
                        self._zh[k] = v
            except Exception as exc:  # noqa: BLE001
                self._load_error = f"zh-CN.txt 读取失败: {exc}"
            for f in alias_files:
                try:
                    with open(f, encoding="utf-8", newline="") as fh:
                        for row in csv.reader(fh):
                            if len(row) < 4:
                                continue
                            canon = _norm(row[0])
                            if not canon:
                                continue
                            for a in row[3].split(","):
                                a = _norm(a)
                                if a:
                                    self._alias.setdefault(a, canon)
                except Exception as exc:  # noqa: BLE001
                    self._load_error = self._load_error or f"{f.name} 读取失败: {exc}"
            self._loaded = True
            return len(self._zh), len(self._alias)

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def error(self) -> str | None:
        return self._load_error

    @property
    def zh_count(self) -> int:
        return len(self._zh)

    @property
    def alias_count(self) -> int:
        return len(self._alias)

    # ---------- 查询 ----------

    def lookup(self, text: str) -> str | None:
        """单个 tag / 整行：词典 → 别名归一化 → 词典。"""
        if not self._loaded:
            return None
        key = _norm(text)
        if not key:
            return None
        v = self._zh.get(key)
        if v is not None:
            return v
        canon = self._alias.get(key)
        if canon:
            v = self._zh.get(canon)
            if v is not None:
                return v
        return None

    def translate_entry(self, text: str) -> str | None:
        """整条 Entry 的离线翻译（按整行语义，不拆散逗号除非确实需要）。"""
        whole = self.lookup(text)
        if whole is not None:
            return whole
        if "," not in text:
            return None
        parts = [p.strip() for p in text.split(",")]
        if len(parts) < 2 or not all(parts):
            return None
        out: list[str] = []
        hit = 0
        for p in parts:
            t = self.lookup(p)
            if t is None:
                out.append(p)  # 缺词保留英文
            else:
                out.append(t)
                hit += 1
        if hit == 0:
            return None
        return ", ".join(out)


def _norm(s: str) -> str:
    """查询键规范化：去首尾空白、下划线转空格、忽略大小写。"""
    return s.strip().replace("_", " ").casefold()
