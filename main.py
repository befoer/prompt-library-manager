"""Prompt Library Manager — 入口。

本地桌面应用（PySide6/Qt），无需云服务器，所有数据保存在本地 TXT。
"""
import sys


def _make_splash_pixmap():
    """生成圆角启动屏（文字直接烘焙进图，避免字号跳变）。"""
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QFont, QPainter, QPixmap

    w, h = 460, 240
    pm = QPixmap(w, h)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#1e1e1e"))
    p.drawRoundedRect(0, 0, w, h, 18, 18)

    title = QFont("Microsoft YaHei UI", 18)
    title.setBold(True)
    p.setPen(QColor("#4fc3f7"))
    p.setFont(title)
    p.drawText(QRect(0, 58, w, 48), Qt.AlignCenter, "词库管理器")

    sub = QFont("Microsoft YaHei UI", 11)
    p.setPen(QColor("#d4d4d4"))
    p.setFont(sub)
    p.drawText(QRect(0, 116, w, 36), Qt.AlignCenter, "正在启动…")
    p.end()
    return pm


def main() -> int:
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QFont, QIcon
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

    # 关闭 PyInstaller 解压启动图（若存在），换用下方圆角启动屏
    try:
        import pyi_splash  # type: ignore
        pyi_splash.close()
    except ImportError:
        pass

    splash = QSplashScreen()
    splash.setAttribute(Qt.WA_TranslucentBackground, True)
    splash.setPixmap(_make_splash_pixmap())
    splash.show()
    app.processEvents()

    # 再导入重型模块（启动屏覆盖这段加载时间）
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
