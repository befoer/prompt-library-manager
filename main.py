"""Prompt Library Manager — 入口。

本地桌面应用（PySide6/Qt），无需云服务器，所有数据保存在本地 TXT。
"""
import sys


def main() -> int:
    try:
        from PySide6.QtGui import QFont, QIcon
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("缺少依赖 PySide6。请先运行：")
        print("    pip install -r requirements.txt")
        return 1

    from app import resources
    from app.ui import theme
    from app.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("词库管理器")
    app.setOrganizationName("PromptLib")
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 9))
    app.setStyleSheet(theme.QSS)

    icon_path = resources.resource_path("icon.png")
    if icon_path is not None:
        app.setWindowIcon(QIcon(str(icon_path)))

    win = MainWindow()
    if icon_path is not None:
        win.setWindowIcon(QIcon(str(icon_path)))
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
