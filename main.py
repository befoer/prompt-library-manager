"""Prompt Library Manager — 入口。

本地桌面应用（PySide6/Qt），无需云服务器，所有数据保存在本地 TXT。
"""
import sys


def main() -> int:
    try:
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

    # 启动屏：直接加载与解压阶段同一张 splash.png，避免大小/外观跳变
    from app import resources
    splash = QSplashScreen()
    splash_path = resources.resource_path("splash.png")
    if splash_path is not None:
        splash.setPixmap(QPixmap(str(splash_path)))
    else:
        fallback = QPixmap(460, 240)
        fallback.fill(QColor("#1e1e1e"))
        splash.setPixmap(fallback)
    splash.show()
    app.processEvents()

    # 关闭 PyInstaller 解压启动图（Qt 启动屏已显示，避免中间消失）
    try:
        import pyi_splash  # type: ignore
        pyi_splash.close()
    except ImportError:
        pass

    # 再导入重型模块（启动屏覆盖这段加载时间）
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
