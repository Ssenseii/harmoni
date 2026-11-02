"""QSS Stylesheets for HARMONI GUI dark theme."""

# Color palette
COLORS = {
    "background": "#2e2e45",
    "background_light": "#383852",
    "background_dark": "#252538",
    "background_card": "#343449",
    "sidebar": "#282840",
    "text": "#e3e4e0",
    "text_secondary": "#9a9ab0",
    "text_muted": "#6a6a80",
    "accent": "#3c92de",
    "accent_hover": "#4da3ef",
    "accent_pressed": "#2b81cd",
    "accent_muted": "rgba(60, 146, 222, 0.15)",
    "success": "#4caf50",
    "success_muted": "rgba(76, 175, 80, 0.15)",
    "error": "#ef5350",
    "error_muted": "rgba(239, 83, 80, 0.15)",
    "warning": "#ff9800",
    "warning_muted": "rgba(255, 152, 0, 0.15)",
    "border": "#454560",
    "border_light": "#505070",
    "input_bg": "#323248",
}

DARK_THEME = f"""
/* ===================== GLOBAL ===================== */
QMainWindow {{
    background-color: {COLORS["background"]};
}}

QWidget {{
    background-color: {COLORS["background"]};
    color: {COLORS["text"]};
    font-family: 'Helvetica Neue', 'Segoe UI', Arial;
    font-size: 14px;
}}

/* ===================== CUSTOM TITLE BAR ===================== */
QWidget#titleBar {{
    background-color: {COLORS["background_dark"]};
    border-bottom: 1px solid {COLORS["border"]};
}}

QLabel#titleLabel {{
    font-size: 13px;
    font-weight: 600;
    color: {COLORS["text"]};
    padding-left: 8px;
}}

QPushButton#titleBarBtn {{
    background-color: transparent;
    border: none;
    border-radius: 0px;
    padding: 10px 16px;
    min-width: 46px;
    color: {COLORS["text_secondary"]};
    font-size: 12px;
}}

QPushButton#titleBarBtn:hover {{
    background-color: {COLORS["background_light"]};
    color: {COLORS["text"]};
}}

QPushButton#closeBtn {{
    background-color: transparent;
    border: none;
    border-radius: 0px;
    padding: 10px 16px;
    min-width: 46px;
    color: {COLORS["text_secondary"]};
    font-size: 12px;
}}

QPushButton#closeBtn:hover {{
    background-color: {COLORS["error"]};
    color: white;
}}

/* ===================== SIDEBAR ===================== */
QWidget#sidebarPanel {{
    background-color: {COLORS["sidebar"]};
    border-right: 1px solid {COLORS["border"]};
}}

QListWidget::item:selected {{
    background-color: {COLORS["accent_muted"]};
    color: {COLORS["text"]};
}}

QListWidget#sidebar {{
    background-color: {COLORS["sidebar"]};
    border: none;
    padding: 8px 0;
    outline: none;
}}

QListWidget#sidebar::item {{
    padding: 16px 24px;
    margin: 4px 10px;
    border-radius: 8px;
    color: {COLORS["text_secondary"]};
    font-weight: 500;
    font-size: 14px;
}}

QListWidget#sidebar::item:hover {{
    background-color: {COLORS["background_light"]};
    color: {COLORS["text"]};
}}

QListWidget#sidebar::item:selected {{
    background-color: {COLORS["accent"]};
    color: white;
}}

/* ===================== BUTTONS ===================== */
QPushButton {{
    background-color: {COLORS["accent"]};
    color: white;
    border: none;
    padding: 8px 16px;
    border-radius: 6px;
    font-weight: 600;
    font-size: 13px;
    min-width: 70px;
}}

QPushButton:hover {{
    background-color: {COLORS["accent_hover"]};
}}

QPushButton:pressed {{
    background-color: {COLORS["accent_pressed"]};
}}

QPushButton:disabled {{
    background-color: {COLORS["background_light"]};
    color: {COLORS["text_muted"]};
}}

QPushButton#secondary {{
    background-color: transparent;
    border: 1px solid {COLORS["border"]};
    color: {COLORS["text"]};
}}

QPushButton#secondary:hover {{
    background-color: {COLORS["background_light"]};
    border-color: {COLORS["border_light"]};
}}

QPushButton#secondary:disabled {{
    border-color: {COLORS["background_light"]};
    color: {COLORS["text_muted"]};
}}

QPushButton#accent {{
    background-color: {COLORS["accent"]};
    color: white;
}}

QPushButton#danger {{
    background-color: {COLORS["error"]};
}}

QPushButton#danger:hover {{
    background-color: #ff6b6b;
}}

QPushButton#danger:disabled {{
    background-color: {COLORS["error_muted"]};
    color: {COLORS["text_muted"]};
}}

QPushButton#success {{
    background-color: {COLORS["success"]};
}}

QPushButton#success:hover {{
    background-color: #5cc05c;
}}

QPushButton#ghost {{
    background-color: transparent;
    border: none;
    color: {COLORS["text_secondary"]};
    padding: 8px 12px;
    min-width: 40px;
}}

QPushButton#ghost:hover {{
    background-color: {COLORS["background_light"]};
    color: {COLORS["text"]};
}}

QPushButton#iconBtn {{
    background-color: transparent;
    border: 1px solid {COLORS["border"]};
    border-radius: 8px;
    padding: 8px;
    min-width: 36px;
    max-width: 36px;
    min-height: 36px;
    max-height: 36px;
}}

QPushButton#iconBtn:hover {{
    background-color: {COLORS["background_light"]};
    border-color: {COLORS["border_light"]};
}}

/* ===================== INPUT FIELDS ===================== */
QLineEdit, QTextEdit {{
    background-color: {COLORS["input_bg"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 8px;
    padding: 12px 16px;
    color: {COLORS["text"]};
    selection-background-color: {COLORS["accent"]};
    font-size: 14px;
    min-height: 20px;
}}

QLineEdit:focus, QTextEdit:focus {{
    border-color: {COLORS["accent"]};
}}

QLineEdit:disabled {{
    background-color: {COLORS["background_dark"]};
    color: {COLORS["text_muted"]};
}}

QLineEdit::placeholder {{
    color: {COLORS["text_muted"]};
}}

/* ===================== COMBO BOX ===================== */
QComboBox {{
    background-color: {COLORS["input_bg"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 8px;
    padding: 12px 16px;
    color: {COLORS["text"]};
    min-width: 140px;
    min-height: 20px;
    font-size: 14px;
}}

QComboBox:hover {{
    border-color: {COLORS["border_light"]};
}}

QComboBox:focus {{
    border-color: {COLORS["accent"]};
}}

QComboBox::drop-down {{
    border: none;
    padding-right: 10px;
}}

QComboBox::down-arrow {{
    width: 12px;
    height: 12px;
}}

QComboBox QAbstractItemView {{
    background-color: {COLORS["background_card"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 8px;
    selection-background-color: {COLORS["accent"]};
    outline: none;
    padding: 4px;
}}

QComboBox QAbstractItemView::item {{
    padding: 8px 12px;
    border-radius: 4px;
}}

QComboBox QAbstractItemView::item:hover {{
    background-color: {COLORS["background_light"]};
}}

/* ===================== TABLES ===================== */
QTableWidget {{
    background-color: {COLORS["background_card"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 10px;
    gridline-color: {COLORS["border"]};
    outline: none;
    selection-background-color: {COLORS["accent_muted"]};
    selection-color: {COLORS["text"]};
}}

QTableWidget::item {{
    padding: 12px 8px;
    border: none;
}}

QTableWidget::item:hover:!selected {{
    background-color: {COLORS["background_light"]};
}}

QTableWidget::item:selected {{
    background-color: {COLORS["accent_muted"]};
    color: {COLORS["text"]};
}}

QHeaderView::section {{
    background-color: {COLORS["background_dark"]};
    color: {COLORS["text_secondary"]};
    padding: 12px 8px;
    border: none;
    border-bottom: 1px solid {COLORS["border"]};
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}

QHeaderView::section:first {{
    border-top-left-radius: 10px;
}}

QHeaderView::section:last {{
    border-top-right-radius: 10px;
}}

/* ===================== SCROLL BARS ===================== */
QScrollBar:vertical {{
    background-color: transparent;
    width: 8px;
    margin: 4px 2px;
}}

QScrollBar::handle:vertical {{
    background-color: {COLORS["border"]};
    border-radius: 4px;
    min-height: 40px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {COLORS["text_muted"]};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}

QScrollBar:horizontal {{
    background-color: transparent;
    height: 8px;
    margin: 2px 4px;
}}

QScrollBar::handle:horizontal {{
    background-color: {COLORS["border"]};
    border-radius: 4px;
    min-width: 40px;
}}

QScrollBar::handle:horizontal:hover {{
    background-color: {COLORS["text_muted"]};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
}}

/* ===================== PROGRESS BAR ===================== */
QProgressBar {{
    background-color: {COLORS["background_dark"]};
    border: none;
    border-radius: 4px;
    height: 6px;
    text-align: center;
}}

QProgressBar::chunk {{
    background-color: {COLORS["accent"]};
    border-radius: 4px;
}}

/* ===================== LABELS ===================== */
QLabel {{
    color: {COLORS["text"]};
    background-color: transparent;
    font-size: 14px;
}}

QLabel#title {{
    font-size: 32px;
    font-weight: 700;
    color: {COLORS["text"]};
    letter-spacing: -0.5px;
}}

QLabel#subtitle {{
    font-size: 15px;
    color: {COLORS["text_secondary"]};
    font-weight: 400;
    line-height: 1.5;
}}

QLabel#section {{
    font-size: 18px;
    font-weight: 600;
    color: {COLORS["text"]};
}}

QLabel#sectionSmall {{
    font-size: 12px;
    font-weight: 600;
    color: {COLORS["text_muted"]};
    text-transform: uppercase;
    letter-spacing: 0.8px;
}}

QLabel#accent {{
    color: {COLORS["accent"]};
}}

QLabel#muted {{
    color: {COLORS["text_muted"]};
    font-size: 13px;
}}

/* ===================== GROUP BOX ===================== */
QGroupBox {{
    background-color: {COLORS["background_card"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 12px;
    margin-top: 14px;
    padding: 20px;
    padding-top: 36px;
    font-weight: 600;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 20px;
    top: 10px;
    padding: 0 6px;
    color: {COLORS["text_secondary"]};
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}

/* ===================== CHECK BOX ===================== */
QCheckBox {{
    spacing: 10px;
    color: {COLORS["text"]};
}}

QCheckBox::indicator {{
    width: 20px;
    height: 20px;
    border-radius: 6px;
    border: 2px solid {COLORS["border"]};
    background-color: {COLORS["input_bg"]};
}}

QCheckBox::indicator:checked {{
    background-color: {COLORS["accent"]};
    border-color: {COLORS["accent"]};
}}

QCheckBox::indicator:hover {{
    border-color: {COLORS["accent"]};
}}

/* ===================== STATUS BAR ===================== */
QStatusBar {{
    background-color: {COLORS["background_dark"]};
    color: {COLORS["text_secondary"]};
    border-top: 1px solid {COLORS["border"]};
    font-size: 12px;
    padding: 4px 8px;
}}

QStatusBar::item {{
    border: none;
}}

/* ===================== TOOLTIPS ===================== */
QToolTip {{
    background-color: {COLORS["background_dark"]};
    color: {COLORS["text"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}}

/* ===================== MESSAGE BOX ===================== */
QMessageBox {{
    background-color: {COLORS["background"]};
}}

QMessageBox QLabel {{
    color: {COLORS["text"]};
}}

/* ===================== TAB WIDGET ===================== */
QTabWidget::pane {{
    border: 1px solid {COLORS["border"]};
    border-radius: 10px;
    background-color: {COLORS["background_card"]};
    margin-top: -1px;
}}

QTabBar::tab {{
    background-color: transparent;
    color: {COLORS["text_secondary"]};
    padding: 12px 20px;
    margin-right: 4px;
    border-bottom: 2px solid transparent;
    font-weight: 500;
}}

QTabBar::tab:selected {{
    color: {COLORS["accent"]};
    border-bottom: 2px solid {COLORS["accent"]};
}}

QTabBar::tab:hover:!selected {{
    color: {COLORS["text"]};
}}

/* ===================== CARDS ===================== */
QFrame#card {{
    background-color: {COLORS["background_card"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 12px;
}}

QFrame#card:hover {{
    border-color: {COLORS["border_light"]};
}}

QFrame#cardAccent {{
    background-color: {COLORS["accent_muted"]};
    border: 1px solid rgba(60, 146, 222, 0.3);
    border-radius: 12px;
}}

QFrame#cardSuccess {{
    background-color: {COLORS["success_muted"]};
    border: 1px solid rgba(76, 175, 80, 0.3);
    border-radius: 12px;
}}

QFrame#cardWarning {{
    background-color: {COLORS["warning_muted"]};
    border: 1px solid rgba(255, 152, 0, 0.3);
    border-radius: 12px;
}}

QFrame#cardError {{
    background-color: {COLORS["error_muted"]};
    border: 1px solid rgba(239, 83, 80, 0.3);
    border-radius: 12px;
}}

/* ===================== DROP ZONE ===================== */
QFrame#dropZone {{
    background-color: {COLORS["background_card"]};
    border: 2px dashed {COLORS["border"]};
    border-radius: 12px;
}}

QFrame#dropZone:hover {{
    border-color: {COLORS["accent"]};
    background-color: {COLORS["accent_muted"]};
}}

QFrame#dropZoneActive {{
    background-color: {COLORS["accent_muted"]};
    border: 2px dashed {COLORS["accent"]};
    border-radius: 12px;
}}

/* ===================== DIVIDER ===================== */
QFrame#divider {{
    background-color: {COLORS["border"]};
    max-height: 1px;
    min-height: 1px;
}}

/* ===================== STATS BADGE ===================== */
QLabel#statValue {{
    font-size: 24px;
    font-weight: 700;
    color: {COLORS["text"]};
}}

QLabel#statLabel {{
    font-size: 12px;
    color: {COLORS["text_muted"]};
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}

/* ===================== SCROLL AREA ===================== */
QScrollArea {{
    border: none;
    background-color: transparent;
}}

QScrollArea > QWidget > QWidget {{
    background-color: transparent;
}}

/* ===================== SPLITTER ===================== */
QSplitter::handle {{
    background-color: {COLORS["border"]};
}}

QSplitter::handle:horizontal {{
    width: 1px;
}}

QSplitter::handle:vertical {{
    height: 1px;
}}
"""

def get_stylesheet() -> str:
    """Get the application stylesheet."""
    return DARK_THEME


def get_colors() -> dict:
    """Get the color palette dictionary."""
    return COLORS.copy()
