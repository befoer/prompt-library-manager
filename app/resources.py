"""资源文件定位（图标 / 图片等）。

打包后资源从 _internal/assets 或 _MEIPASS 读取；开发模式从项目根 / assets 读取。
"""
from __future__ import annotations

import sys
from pathlib import Path


def resource_path(name: str) -> Path | None:
    """在 assets/ 目录中查找资源文件，返回路径；找不到返回 None。"""
    cands: list[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        cands += [exe_dir / "assets" / name, exe_dir / "_internal" / "assets" / name]
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            cands.append(Path(meipass) / "assets" / name)
    # 开发模式：项目根 / assets
    cands.append(Path(__file__).resolve().parent.parent / "assets" / name)
    for c in cands:
        if c.exists():
            return c
    return None
