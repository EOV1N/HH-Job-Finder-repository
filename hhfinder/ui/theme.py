"""Тёмная тема и палитра приложения."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

COLORS = {
    "bg": "#0b0f16",
    "surface": "#111826",
    "surface2": "#162033",
    "surface3": "#1c273a",
    "border": "#273449",
    "text": "#e8eef7",
    "muted": "#8b9bb1",
    "accent": "#63e6be",
    "accent2": "#8b8cf7",
    "blue": "#5aa9ff",
    "amber": "#f2b45c",
    "red": "#f47d7d",
    "green": "#5ed6a4",
}

QSS_TEMPLATE = """
* { font-family: "Inter", "Segoe UI", "Arial", sans-serif; color: @TEXT@; }
QMainWindow, QWidget#central { background: @BG@; }
QFrame#sidebar { background: @SURFACE@; border-right: 1px solid @BORDER@; }
QFrame#topbar, QFrame#filterbar, QFrame#statusbar { background: @SURFACE@; border-bottom: 1px solid @BORDER@; }
QFrame#statusbar { border-top: 1px solid @BORDER@; border-bottom: none; }
QFrame#card, QFrame#vacancyCard, QFrame#detailPanel, QGroupBox {
    background: @SURFACE2@; border: 1px solid @BORDER@; border-radius: 14px;
}
QFrame#vacancyCard:hover { background: @SURFACE3@; border: 1px solid #3b526c; }
QFrame#vacancyCard[selected="true"] { border: 1px solid @ACCENT@; }
QGroupBox { margin-top: 18px; padding-top: 14px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: @MUTED@; }
QLabel { background: transparent; }
QLabel#muted, QLabel#hint { color: @MUTED@; }
QLabel#logo { font-size: 18px; font-weight: 700; letter-spacing: 0.3px; }
QLabel#pageTitle { font-size: 22px; font-weight: 700; }
QLabel#sectionTitle { font-size: 14px; font-weight: 700; color: @TEXT@; }
QLabel#chip {
    background: @SURFACE3@; border: 1px solid @BORDER@; border-radius: 9px;
    padding: 3px 8px; color: @MUTED@; font-size: 11px;
}
QLabel#chipAccent { background: #173a35; border: 1px solid #2d6b5c; color: @ACCENT@; border-radius: 9px; padding: 3px 8px; font-size: 11px; }
QLabel#chipWarn { background: #3a2e1c; border: 1px solid #6a5230; color: @AMBER@; border-radius: 9px; padding: 3px 8px; font-size: 11px; }
QLabel#badgeNew { background: #163b32; color: @ACCENT@; border-radius: 10px; padding: 3px 9px; font-weight: 700; font-size: 11px; }
QPushButton {
    background: @SURFACE3@; border: 1px solid @BORDER@; border-radius: 10px;
    padding: 8px 14px; font-weight: 600;
}
QPushButton:hover { background: #24334a; border-color: #3c5170; }
QPushButton:pressed { background: #1b2739; }
QPushButton:disabled { color: #66748a; background: @SURFACE2@; }
QPushButton#primary { background: @ACCENT@; color: #06231c; border: none; }
QPushButton#primary:hover { background: #7cf0cd; }
QPushButton#nav {
    background: transparent; border: none; border-radius: 10px; text-align: left;
    padding: 10px 12px; color: @MUTED@; font-size: 13px; font-weight: 600;
}
QPushButton#nav:hover { background: @SURFACE3@; color: @TEXT@; }
QPushButton#nav:checked { background: @SURFACE3@; color: @ACCENT@; }
QPushButton#icon { padding: 5px 9px; border-radius: 8px; font-size: 13px; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {
    background: @SURFACE2@; border: 1px solid @BORDER@; border-radius: 10px;
    padding: 8px 10px; selection-background-color: #2b5d72;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: @ACCENT@; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: @SURFACE2@; border: 1px solid @BORDER@; selection-background-color: @SURFACE3@; }
QCheckBox, QRadioButton { spacing: 8px; }
QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px; border: 1px solid @BORDER@; border-radius: 4px; background: @SURFACE2@; }
QCheckBox::indicator:checked { background: @ACCENT@; border-color: @ACCENT@; }
QTableView, QListWidget, QTreeWidget {
    background: @SURFACE@; border: 1px solid @BORDER@; border-radius: 12px;
    gridline-color: @BORDER@; alternate-background-color: #101827;
}
QTableView::item { padding: 7px 8px; border-bottom: 1px solid #1b2637; }
QTableView::item:selected, QListWidget::item:selected { background: #243a50; color: @TEXT@; }
QHeaderView::section { background: @SURFACE2@; color: @MUTED@; padding: 9px 8px; border: none; border-bottom: 1px solid @BORDER@; font-weight: 700; }
QListWidget { padding: 6px; }
QListWidget::item { border-radius: 12px; margin: 4px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #34445c; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #455b78; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QProgressBar { background: @SURFACE2@; border: none; border-radius: 6px; height: 8px; text-align: center; }
QProgressBar::chunk { background: @ACCENT@; border-radius: 6px; }
QSplitter::handle { background: @BORDER@; width: 5px; }
QToolTip { background: @SURFACE3@; color: @TEXT@; border: 1px solid @BORDER@; padding: 5px; }
QTabWidget::pane { border: 1px solid @BORDER@; border-radius: 10px; }
QTabBar::tab { background: @SURFACE2@; padding: 8px 14px; border-top-left-radius: 8px; border-top-right-radius: 8px; }
QTabBar::tab:selected { background: @SURFACE3@; color: @ACCENT@; }
"""


def stylesheet() -> str:
    out = QSS_TEMPLATE
    for key, value in COLORS.items():
        out = out.replace(f"@{key.upper()}@", value)
    return out


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setFont(QFont("Inter", 10))
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(COLORS["bg"]))
    palette.setColor(QPalette.WindowText, QColor(COLORS["text"]))
    palette.setColor(QPalette.Base, QColor(COLORS["surface"]))
    palette.setColor(QPalette.AlternateBase, QColor(COLORS["surface2"]))
    palette.setColor(QPalette.Text, QColor(COLORS["text"]))
    palette.setColor(QPalette.Button, QColor(COLORS["surface2"]))
    palette.setColor(QPalette.ButtonText, QColor(COLORS["text"]))
    palette.setColor(QPalette.Highlight, QColor("#2d5b6b"))
    palette.setColor(QPalette.HighlightedText, QColor(COLORS["text"]))
    palette.setColor(QPalette.ToolTipBase, QColor(COLORS["surface3"]))
    palette.setColor(QPalette.ToolTipText, QColor(COLORS["text"]))
    app.setPalette(palette)
    app.setStyleSheet(stylesheet())
