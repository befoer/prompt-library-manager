"""TXT 读写与编码识别。

- 读取时自动识别 UTF-8 / UTF-8 BOM / UTF-16 / GBK(GB18030) / 其他(chardet 兜底)
- 按行拆分兼容 Windows CRLF / Unix LF / Mac CR
- 默认删除每行首尾空白、删除空行，保留行内空格与英文大小写
- 写入采用原子替换（先写临时文件再 rename），避免写一半损坏词库
"""
from __future__ import annotations

import codecs
import os
import time
from pathlib import Path

import chardet


def detect_encoding(raw: bytes) -> str:
    """自动识别文本编码。"""
    if raw.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if raw.startswith(codecs.BOM_UTF16_LE):
        return "utf-16-le"
    if raw.startswith(codecs.BOM_UTF16_BE):
        return "utf-16-be"
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        raw.decode("gb18030")  # GB18030 是 GBK 的超集
        return "gb18030"
    except UnicodeDecodeError:
        guess = chardet.detect(raw)
        enc = (guess.get("encoding") or "utf-8").lower()
        return enc if enc not in ("ascii", "iso-8859-1") else "utf-8"


def decode(raw: bytes, encoding: str) -> str:
    try:
        return raw.decode(encoding, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def normalize_lines(text: str) -> list[str]:
    """拆分行为词库条目：删首尾空白、删空行、保留行内空格与大小写。"""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if s:
            out.append(s)
    return out


def read_lines(path: Path) -> tuple[list[str], str]:
    """读取 TXT，返回 (条目列表, 识别到的编码)。"""
    raw = path.read_bytes()
    enc = detect_encoding(raw)
    return normalize_lines(decode(raw, enc)), enc


def write_text_atomic(path: Path, lines: list[str], encoding: str = "utf-8") -> None:
    """原子写入 TXT。导出/保存默认 UTF-8（无 BOM）。

    Windows 上目标文件可能被瞬时占用（杀软扫描 / 同步工具 / 句柄释放延迟），
    遇到 PermissionError 时自动重试几次，避免写入失败。
    """
    text = "\n".join(lines)
    if lines:
        text += "\n"
    data = text.encode(encoding)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_bytes(data)
        last_err: OSError | None = None
        for attempt in range(6):
            try:
                os.replace(tmp, path)
                return
            except PermissionError as e:
                last_err = e
                time.sleep(0.06 * (attempt + 1))
        raise last_err  # type: ignore[misc]
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
