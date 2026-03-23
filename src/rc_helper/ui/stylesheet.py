"""
stylesheet.py
-------------
Application-wide QSS dark theme.

Palette is adapted from the file_renamer project (same repo family):
  background  #0f141a / #161d24
  text        #d7dee7 / #96a4b5
  accent      #2f81f7
  danger      #ffb4bf on #2b1f24
  warning     #cc8800
"""

APP_STYLESHEET = """
/* ── Base ─────────────────────────────────────────────────────────────── */
QMainWindow, QWidget {
    background: #0f141a;
    color: #d7dee7;
    font-family: "SF Pro Text", "Segoe UI", sans-serif;
    font-size: 12px;
}

/* ── Group boxes ──────────────────────────────────────────────────────── */
QGroupBox {
    background: #161d24;
    border: 1px solid #283341;
    border-radius: 10px;
    margin-top: 14px;
    padding: 12px;
    font-weight: 600;
}
QGroupBox:disabled {
    background: #11161c;
    border: 1px solid #1d2631;
    color: #5b6674;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: #aeb9c7;
}
QGroupBox::title:disabled {
    color: #5b6674;
}

/* ── Text inputs ──────────────────────────────────────────────────────── */
QLineEdit, QPlainTextEdit {
    background: #121920;
    border: 1px solid #2d3948;
    border-radius: 8px;
    padding: 6px 8px;
    selection-background-color: #2f81f7;
    selection-color: #f5f9ff;
}
QLineEdit:focus, QPlainTextEdit:focus {
    border: 1px solid #4c8dff;
}
QLineEdit:disabled, QPlainTextEdit:disabled {
    background: #0f141a;
    border: 1px solid #1d2631;
    color: #617080;
}
QLineEdit[readOnly="true"] {
    color: #96a4b5;
}

/* ── Combo box ────────────────────────────────────────────────────────── */
QComboBox {
    background: #121920;
    border: 1px solid #2d3948;
    border-radius: 8px;
    padding: 5px 8px;
    color: #d7dee7;
    min-height: 26px;
}
QComboBox:focus {
    border: 1px solid #4c8dff;
}
QComboBox:disabled {
    background: #0f141a;
    color: #617080;
    border: 1px solid #1d2631;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #96a4b5;
    width: 0;
    height: 0;
    margin-right: 6px;
}
QComboBox QAbstractItemView {
    background: #161d24;
    border: 1px solid #2d3948;
    border-radius: 6px;
    selection-background-color: #2f81f7;
    selection-color: #f5f9ff;
    padding: 2px;
    outline: none;
}

/* ── List / Tree widgets ──────────────────────────────────────────────── */
QListWidget, QTreeWidget {
    background: #121920;
    border: 1px solid #2d3948;
    border-radius: 8px;
    padding: 2px;
    selection-background-color: #1d2b3b;
    selection-color: #f5f9ff;
    outline: none;
}
QListWidget:focus, QTreeWidget:focus {
    border: 1px solid #4c8dff;
}
QListWidget::item, QTreeWidget::item {
    padding: 5px 8px;
    border-bottom: 1px solid #182029;
    color: #d7dee7;
}
QListWidget::item:alternate, QTreeWidget::item:alternate {
    background: #141b22;
}
QListWidget::item:selected, QTreeWidget::item:selected {
    background: #1d2b3b;
    color: #f5f9ff;
}
QListWidget::item:hover, QTreeWidget::item:hover {
    background: #182231;
}

/* ── Buttons ──────────────────────────────────────────────────────────── */
QPushButton {
    background: #202a35;
    color: #e8eef6;
    border: 1px solid #304055;
    border-radius: 8px;
    padding: 4px 10px;
    min-height: 26px;
    font-weight: 600;
}
QPushButton:hover {
    background: #273444;
    border: 1px solid #3a4d67;
}
QPushButton:pressed {
    background: #18222d;
}
QPushButton:disabled {
    background: #161d24;
    color: #738091;
    border: 1px solid #243140;
}

QPushButton[variant="primary"] {
    background: #2f81f7;
    color: #f5f9ff;
    border: 1px solid #4c8dff;
}
QPushButton[variant="primary"]:hover {
    background: #2674e8;
    border: 1px solid #4c8dff;
}
QPushButton[variant="primary"]:pressed {
    background: #1e65d0;
}
QPushButton[variant="primary"]:disabled {
    background: #1a3a6b;
    color: #5b7aaa;
    border: 1px solid #1f3f5f;
}

QPushButton[variant="danger"] {
    background: #2b1f24;
    color: #ffb4bf;
    border: 1px solid #5a303d;
}
QPushButton[variant="danger"]:hover {
    background: #38232b;
    border: 1px solid #6d3a4a;
}
QPushButton[variant="danger"]:disabled {
    background: #1c161a;
    color: #7a5060;
    border: 1px solid #3a2530;
}

/* ── Check boxes & radio buttons ─────────────────────────────────────── */
QCheckBox, QRadioButton, QLabel {
    color: #d7dee7;
}
QCheckBox:disabled, QRadioButton:disabled, QLabel:disabled {
    color: #5b6674;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #304055;
    border-radius: 3px;
    background: #121920;
}
QCheckBox::indicator:checked {
    background: #2f81f7;
    border: 1px solid #4c8dff;
}
QCheckBox::indicator:disabled {
    background: #161d24;
    border: 1px solid #243140;
}

/* ── Progress bar ─────────────────────────────────────────────────────── */
QProgressBar {
    background: #121920;
    border: 1px solid #2d3948;
    border-radius: 6px;
    text-align: center;
    color: #96a4b5;
    font-size: 11px;
    min-height: 18px;
}
QProgressBar::chunk {
    background: #2f81f7;
    border-radius: 5px;
}

/* ── Scroll bars ──────────────────────────────────────────────────────── */
QScrollBar:vertical {
    background: #111821;
    width: 10px;
    margin: 4px;
}
QScrollBar::handle:vertical {
    background: #334154;
    min-height: 28px;
    border-radius: 5px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar:horizontal {
    background: #111821;
    height: 10px;
    margin: 4px;
}
QScrollBar::handle:horizontal {
    background: #334154;
    min-width: 28px;
    border-radius: 5px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* ── Splitter handle ──────────────────────────────────────────────────── */
QSplitter::handle {
    background: #283341;
}

/* ── Header view ──────────────────────────────────────────────────────── */
QHeaderView::section {
    background: #182029;
    color: #96a4b5;
    border: none;
    border-bottom: 1px solid #2d3948;
    padding: 8px 10px;
    font-weight: 700;
}

/* ── Menu bar ─────────────────────────────────────────────────────────── */
QMenuBar {
    background: #0f141a;
    color: #d7dee7;
}
QMenuBar::item:selected {
    background: #182029;
    border-radius: 4px;
}

/* ── Tooltip ──────────────────────────────────────────────────────────── */
QToolTip {
    background: #1c2735;
    color: #d7dee7;
    border: 1px solid #2d3948;
    border-radius: 4px;
    padding: 4px 6px;
    font-size: 11px;
}
"""
