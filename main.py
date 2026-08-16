"""Prompt Library Manager — 入口。

本地桌面应用（PySide6/Qt），无需云服务器，所有数据保存在本地 TXT。
"""
import sys


def main() -> int:
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QFont, QIcon, QPixmap
        from PySide6.QtWidgets import QApplication, QSplashScreen
    except ImportError:
        print("缺少依赖 PySide6。请先运行：")
        print("    pip install -r requirements.txt")
        return 1

    app = QApplication(sys.argv)
    app.setApplicationName("词库管理器")
    app.setOrganizationName("PromptLib")
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 9))

    # 关闭 PyInstaller 的解压启动图（若存在），换用下方带文字的启动屏
    try:
        import pyi_splash  # type: ignore
        pyi_splash.close()
    except ImportError:
        pass

    # 启动屏：尽早显示，避免用户以为卡死/失败
    splash = QSplashScreen()
    pm = QPixmap(440, 220)
    pm.fill(QColor("#1e1e1e"))
    splash.setPixmap(pm)
    splash.setFont(QFont("Microsoft YaHei UI", 11))
    splash.showMessage("词库管理器正在启动…", Qt.AlignCenter, QColor("#4fc3f7"))
    splash.show()
    app.processEvents()

    # 再导入重型模块（启动屏会盖住这段加载时间）
    from app import resources
    from app.ui import theme
    from app.ui.main_window import MainWindow

    app.setStyleSheet(theme.QSS)

    icon_path = resources.resource_path("icon.png")
    if icon_path is not None:
        app.setWindowIcon(QIcon(str(icon_path)))

    win = MainWindow()
    if icon_path is not None:
        win.setWindowIcon(QIcon(str(icon_path)))
    splash.finish(win)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
