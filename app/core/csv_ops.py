"""CSV 英中对照导入导出。

格式：
    English,Chinese
    windows,窗户
    Fantasy Room,幻想房间

导入：第一列 English，第二列 Chinese（跳过表头行）。
导出：UTF-8 BOM（Excel 友好），全条目输出。
"""
from __future__ import annotations

import csv
from pathlib import Path


def read_translation_csv(path: Path) -> list[tuple[str, str]]:
    """读取英中对照 CSV，返回 [(english, chinese), ...]。"""
    pairs: list[tuple[str, str]] = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            if len(row) < 2:
                continue
            en = row[0].strip()
            zh = row[1].strip()
            if not en:
                continue
            if en.casefold() == "english" and zh.casefold() == "chinese":
                continue  # 表头
            pairs.append((en, zh))
    return pairs


def write_translation_csv(path: Path, pairs: list[tuple[str, str]]) -> None:
    """写出英中对照 CSV（含表头）。pairs = [(english, chinese), ...]。"""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["English", "Chinese"])
        for en, zh in pairs:
            w.writerow([en, zh])
