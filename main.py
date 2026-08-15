"""Prompt Library Manager — 入口。

本地桌面应用（PySide6/Qt），无需云服务器，所有数据保存在本地 TXT。
"""
import sys
from pathlib import Path


def find_icon() -> Path | None:
    """定位 icon.png：优先打包环境（exe 目录 / _internal / _MEIPASS），退回开发根目录。"""
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
        candidates += [base / "icon.png", base / "_internal" / "icon.png"]
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "icon.png")
    candidates.append(Path(__file__).resolve().parent / "icon.png")
    for c in candidates:
        if c.exists():
            return c
    return None


def main() -> int:
    try:
        from PySide6.QtGui import QFont, QIcon
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("缺少依赖 PySide6。请先运行：")
        print("    pip install -r requirements.txt")
        return 1

    from app.ui import theme
    from app.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Prompt Library Manager")
    app.setOrganizationName("PromptLib")
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 9))
    app.setStyleSheet(theme.QSS)

    icon = find_icon()
    if icon is not None:
        app.setWindowIcon(QIcon(str(icon)))

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
