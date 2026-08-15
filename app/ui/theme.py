"""深色主题（参考 VS Code / Obsidian / SQLite Browser 风格，紧凑高密度）。"""

QSS = """
* { outline: none; }
QWidget {
    background: #1e1e1e;
    color: #d4d4d4;
    font-size: 13px;
}
QMenuBar { background: #1e1e1e; border-bottom: 1px solid #2d2d2d; }
QMenuBar::item { padding: 4px 12px; background: transparent; }
QMenuBar::item:selected { background: #094771; }
QMenu { background: #252526; border: 1px solid #3c3c3c; padding: 4px; }
QMenu::item { padding: 5px 28px 5px 12px; border-radius: 3px; }
QMenu::item:selected { background: #094771; }
QMenu::item:disabled { color: #6e6e6e; }
QMenu::separator { height: 1px; background: #3c3c3c; margin: 4px 8px; }
QToolButton, QPushButton {
    background: #333333; border: 1px solid #3c3c3c; border-radius: 3px;
    padding: 4px 10px; color: #d4d4d4;
}
QToolButton:hover, QPushButton:hover { background: #3c3c3c; border-color: #4a4a4a; }
QToolButton:pressed, QPushButton:pressed { background: #2a2d2e; }
QToolButton:checked { background: #0e639c; border-color: #4fc3f7; color: #ffffff; }
QToolButton:disabled, QPushButton:disabled { color: #6e6e6e; background: #2d2d2d; }
QToolButton::menu-indicator { image: none; }
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {
    background: #252526; border: 1px solid #3c3c3c; border-radius: 3px;
    padding: 4px 6px; color: #d4d4d4; selection-background-color: #094771;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus { border-color: #0e639c; }
QComboBox QAbstractItemView {
    background: #252526; border: 1px solid #3c3c3c;
    selection-background-color: #094771;
}
QListWidget, QListView { background: #1e1e1e; border: none; }
QListWidget::item { padding: 4px 6px; }
QListWidget::item:selected { background: #094771; color: #ffffff; }
QListWidget::item:hover { background: #2a2d2e; }
QSplitter::handle { background: #2d2d2d; }
QSplitter::handle:horizontal { width: 2px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #424242; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #4e4e4e; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: transparent; height: 10px; }
QScrollBar::handle:horizontal { background: #424242; border-radius: 5px; min-width: 30px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
QStatusBar { background: #2d2d2d; border-top: 1px solid #3c3c3c; }
QStatusBar QLabel { color: #9d9d9d; }
QToolTip { background: #252526; color: #d4d4d4; border: 1px solid #3c3c3c; padding: 4px; }
QDialog, QMessageBox, QInputDialog { background: #1e1e1e; }
QLabel#statsLabel { color: #9d9d9d; padding: 2px 6px; }
QLabel#sideTitle { color: #9d9d9d; font-weight: bold; padding: 2px 2px; }
QLabel#bigText {
    background: #252526; border: 1px solid #3c3c3c; border-radius: 4px;
    padding: 12px; font-size: 15px; color: #ffffff;
}
"""
