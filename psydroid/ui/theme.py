from PySide6.QtGui import QFontDatabase

from .. import paths

# One neutral dark ground, a lighter step for panels, and a single blue reserved for focus, links,
# progress and switches. The main action is an inverted light button, not a coloured one.
COLORS = {
    "sidebar": "#161616",
    "main": "#161616",
    "surface": "#1d1d1d",
    "raised": "#262626",
    "hover": "#242424",
    "selected": "#2c2c2c",
    "input": "#121212",
    "line": "#2a2a2a",
    "control": "#3a3a3a",
    "text": "#e6e6e6",
    "bright": "#ffffff",
    "muted": "#b4b4b4",
    "faint": "#949494",
    "dim": "#6b6b6b",
    "accent": "#5b9cf0",
    "accent_hover": "#7ab0f5",
    "on_accent": "#0d1b2c",
    "primary": "#ececec",
    "primary_hover": "#ffffff",
    "on_primary": "#161616",
    "green": "#3fc07a",
    "red": "#e5566f",
    "danger": "#e5566f",
    "danger_hover": "#2c1a1e",
    "yellow": "#d9a441",
}

ICONS = {
    "back": "",
    "home": "",
    "recents": "",
    "volume_up": "",
    "volume_down": "",
    "rotate": "",
    "camera": "",
    "record": "",
    "stop": "",
    "fullscreen": "",
    "location": "",
    "install": "",
    "folder": "",
    "settings": "",
    "add": "",
    "shake": "",
    "apps": "",
    "screen": "",
    "more": "",
    "popout": "",
    "mute": "",
    "pin": "",
    "download": "",
    "library": "",
}


class Fonts:
    text = "Segoe UI"
    strong = "Segoe UI Semibold"
    icons = "Segoe MDL2 Assets"

    @classmethod
    def load(cls):
        available = set(QFontDatabase.families())

        def pick(*names):
            return next((name for name in names if name in available), names[-1])

        cls.text = pick("Segoe UI Variable Text", "Segoe UI")
        cls.strong = pick("Segoe UI Semibold", "Segoe UI")
        cls.icons = pick("Segoe Fluent Icons", "Segoe MDL2 Assets")


def stylesheet():
    c = COLORS
    arrow = (paths.BUNDLE / "assets" / "chevron-down.svg").as_posix()
    return f"""
    QWidget {{
        color: {c["text"]};
        font-family: "{Fonts.text}";
        font-size: 10pt;
    }}
    QMainWindow, #Main, #Page, QStackedWidget {{
        background: {c["main"]};
    }}
    #Sidebar, #Tools {{
        background: {c["sidebar"]};
    }}
    #Sidebar {{
        border-right: 1px solid {c["line"]};
    }}
    #Tools {{
        border-left: 1px solid {c["line"]};
    }}
    #Header {{
        border-bottom: 1px solid {c["line"]};
    }}
    #Brand {{
        color: {c["bright"]};
        font-family: "{Fonts.strong}";
        font-size: 11pt;
    }}
    #Title {{
        color: {c["bright"]};
        font-family: "{Fonts.strong}";
        font-size: 11pt;
    }}
    #Heading {{
        color: {c["bright"]};
        font-family: "{Fonts.strong}";
        font-size: 15pt;
    }}
    #Subheading {{
        color: {c["bright"]};
        font-family: "{Fonts.strong}";
        font-size: 10.5pt;
    }}
    #Section {{
        color: {c["faint"]};
        font-size: 9pt;
    }}
    #Muted {{
        color: {c["muted"]};
    }}
    #Small {{
        color: {c["faint"]};
        font-size: 9pt;
    }}
    #Card {{
        background: {c["surface"]};
        border-radius: 8px;
        border: 1px solid {c["line"]};
    }}
    #Divider {{
        background: {c["line"]};
        max-height: 1px;
        min-height: 1px;
    }}
    QPushButton {{
        border: 1px solid {c["primary"]};
        border-radius: 6px;
        padding: 0 14px;
        min-height: 30px;
        font-family: "{Fonts.strong}";
        font-size: 10pt;
        color: {c["on_primary"]};
        background: {c["primary"]};
    }}
    QPushButton:hover {{
        background: {c["primary_hover"]};
        border-color: {c["primary_hover"]};
    }}
    QPushButton:pressed {{
        background: #d4d4d4;
    }}
    QPushButton:focus {{
        border: 1px solid {c["accent"]};
    }}
    QPushButton:disabled {{
        background: {c["raised"]};
        border-color: {c["raised"]};
        color: {c["dim"]};
    }}
    QPushButton[kind="secondary"] {{
        background: {c["raised"]};
        border: 1px solid {c["control"]};
        color: {c["text"]};
        font-family: "{Fonts.text}";
    }}
    QPushButton[kind="secondary"]:hover {{
        background: #2e2e2e;
    }}
    QPushButton[kind="secondary"]:pressed {{
        background: {c["hover"]};
    }}
    QPushButton[kind="secondary"]:focus, QPushButton[kind="danger"]:focus {{
        border: 1px solid {c["accent"]};
    }}
    QPushButton[kind="secondary"]:disabled {{
        background: transparent;
        border-color: {c["line"]};
        color: {c["dim"]};
    }}
    QPushButton[kind="danger"] {{
        background: transparent;
        border: 1px solid {c["danger"]};
        color: {c["danger"]};
        font-family: "{Fonts.text}";
    }}
    QPushButton[kind="danger"]:hover {{
        background: {c["danger_hover"]};
    }}
    QPushButton[kind="link"] {{
        background: transparent;
        border: none;
        color: {c["accent"]};
        font-family: "{Fonts.text}";
        padding: 0 8px;
    }}
    QPushButton[kind="link"]:hover {{
        text-decoration: underline;
    }}
    QPushButton[size="large"] {{
        min-height: 36px;
        padding: 0 18px;
    }}
    QLineEdit, QComboBox, QAbstractSpinBox, QKeySequenceEdit QLineEdit {{
        background: {c["input"]};
        border: 1px solid {c["control"]};
        border-radius: 6px;
        padding: 0 10px;
        min-height: 30px;
        color: {c["text"]};
        selection-background-color: {c["accent"]};
        selection-color: {c["on_accent"]};
    }}
    QLineEdit:focus, QComboBox:focus, QAbstractSpinBox:focus {{
        border: 1px solid {c["accent"]};
    }}
    QListWidget {{
        background: {c["input"]};
        border: 1px solid {c["line"]};
        border-radius: 6px;
        padding: 4px;
        outline: none;
    }}
    QListWidget::item {{
        padding: 7px 10px;
        border-radius: 4px;
    }}
    QListWidget::item:hover {{
        background: {c["hover"]};
    }}
    QListWidget::item:selected {{
        background: {c["selected"]};
        color: {c["bright"]};
    }}
    QComboBox {{
        padding-right: 28px;
    }}
    QComboBox::drop-down {{
        border: none;
        width: 28px;
    }}
    QComboBox::down-arrow {{
        image: url("{arrow}");
        width: 12px;
        height: 12px;
    }}
    QComboBox QAbstractItemView {{
        background: {c["surface"]};
        border: 1px solid {c["control"]};
        padding: 4px;
        outline: none;
        selection-background-color: {c["selected"]};
    }}
    QScrollArea, QScrollArea > QWidget > QWidget {{
        background: transparent;
        border: none;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {c["control"]};
        border-radius: 3px;
        min-height: 32px;
    }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
        height: 0;
        background: transparent;
    }}
    QToolTip {{
        background: {c["surface"]};
        color: {c["bright"]};
        border: 1px solid {c["control"]};
        padding: 5px 8px;
        font-size: 9pt;
    }}
    QMenu {{
        background: {c["surface"]};
        border: 1px solid {c["control"]};
        border-radius: 6px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: 6px 14px;
        border-radius: 4px;
        color: {c["text"]};
    }}
    QMenu::item:selected {{
        background: {c["selected"]};
        color: {c["bright"]};
    }}
    QMenu::separator {{
        height: 1px;
        background: {c["line"]};
        margin: 4px 6px;
    }}
    #Toast {{
        background: {c["surface"]};
        color: {c["bright"]};
        border-radius: 6px;
        border: 1px solid {c["control"]};
        padding: 10px 16px;
    }}
    #Dialog {{
        background: {c["surface"]};
        border: 1px solid {c["control"]};
        border-radius: 8px;
    }}
    """
