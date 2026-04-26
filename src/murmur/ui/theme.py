"""Murmur visual theme.

Single accent color (violet), explicit light/dark palettes that tune
readability under both system themes, and a small set of helper
factories so pages can produce styled chrome (cards, section labels,
primary buttons) without hand-rolling stylesheets.

The accent appears in:

* the left-rail's selected row,
* primary action buttons (Record, Restart Now, Use, Download),
* focus rings on text fields / dropdowns,
* the section-label underline accent.

Both palettes deliberately push surface and text further apart than
the Qt default — the original UI was ~unreadable in dark mode because
section labels and "mid"-toned subtitles ended up nearly indistinguishable
from the window background.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton, QWidget

# ---- Accent ---------------------------------------------------------------

ACCENT = "#7c5cff"        # violet, primary action / selection
ACCENT_HOVER = "#9079ff"
ACCENT_PRESSED = "#6447e6"
ACCENT_TEXT = "#ffffff"   # text on accent backgrounds

# State dot colors — punchier than Qt defaults, readable on either surface.
STATE_IDLE = "#94a3b8"      # slate-400
STATE_RECORDING = "#ef4444" # red-500
STATE_BUSY = "#f59e0b"      # amber-500
STATE_OK = "#10b981"        # emerald-500


@dataclass(frozen=True)
class Palette:
    name: str          # "light" or "dark"
    window: str        # main window background
    surface: str       # card background
    surface_alt: str   # alternating row / hover
    border: str        # card / divider line
    text: str          # primary text
    text_dim: str      # subtitles, hints
    text_muted: str    # very secondary
    rail_bg: str       # left nav background
    rail_text: str
    rail_selected_bg: str
    rail_selected_text: str


LIGHT = Palette(
    name="light",
    window="#f6f5fb",
    surface="#ffffff",
    surface_alt="#f1eef9",
    border="#e2dff0",
    text="#1b1530",
    text_dim="#5a5475",
    text_muted="#8a839f",
    rail_bg="#ece8f7",
    rail_text="#3a3458",
    rail_selected_bg=ACCENT,
    rail_selected_text=ACCENT_TEXT,
)

DARK = Palette(
    name="dark",
    window="#15131e",
    surface="#1f1c2c",
    surface_alt="#272338",
    border="#322d48",
    text="#ece9f7",
    text_dim="#b6b0d0",
    text_muted="#867fa3",
    rail_bg="#1a1726",
    rail_text="#cbc4e6",
    rail_selected_bg=ACCENT,
    rail_selected_text=ACCENT_TEXT,
)


# ---- Theme detection + application ----------------------------------------

def _detect_palette(app: QApplication) -> Palette:
    """Pick a palette to match the system theme.

    Qt 6.5 added ``styleHints().colorScheme()``. On older builds we fall
    back to inspecting the default palette's window lightness. Tests
    that set ``MURMUR_FORCE_THEME=light|dark`` skip detection entirely.
    """
    import os
    forced = os.environ.get("MURMUR_FORCE_THEME", "").lower()
    if forced == "light":
        return LIGHT
    if forced == "dark":
        return DARK

    hints = app.styleHints()
    scheme = getattr(hints, "colorScheme", None)
    if callable(scheme):
        try:
            value = scheme()
            if value == Qt.ColorScheme.Dark:
                return DARK
            if value == Qt.ColorScheme.Light:
                return LIGHT
        except Exception:  # noqa: BLE001
            pass

    # Heuristic: look at the existing window-color lightness.
    win = app.palette().color(QPalette.ColorRole.Window)
    return DARK if win.lightness() < 128 else LIGHT


def apply_theme(app: QApplication, palette: Palette | None = None) -> Palette:
    """Apply the Murmur theme to ``app`` and return the active palette.

    Idempotent — calling twice just reapplies. The function tweaks both
    the QPalette (so native widgets like QMessageBox pick up reasonable
    defaults) and a global stylesheet (for the bits that need finer
    control than the palette exposes).
    """
    p = palette or _detect_palette(app)

    qpal = app.palette()
    qpal.setColor(QPalette.ColorRole.Window, QColor(p.window))
    qpal.setColor(QPalette.ColorRole.Base, QColor(p.surface))
    qpal.setColor(QPalette.ColorRole.AlternateBase, QColor(p.surface_alt))
    qpal.setColor(QPalette.ColorRole.Text, QColor(p.text))
    qpal.setColor(QPalette.ColorRole.WindowText, QColor(p.text))
    qpal.setColor(QPalette.ColorRole.ButtonText, QColor(p.text))
    qpal.setColor(QPalette.ColorRole.PlaceholderText, QColor(p.text_muted))
    qpal.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    qpal.setColor(QPalette.ColorRole.HighlightedText, QColor(ACCENT_TEXT))
    app.setPalette(qpal)

    app.setStyleSheet(_stylesheet(p))
    return p


def _stylesheet(p: Palette) -> str:
    return f"""
    QWidget {{
        color: {p.text};
        font-size: 13px;
    }}
    QMainWindow, QDialog {{
        background: {p.window};
    }}

    /* Left-rail navigation */
    QListWidget#nav {{
        background: {p.rail_bg};
        color: {p.rail_text};
        border: none;
        border-right: 1px solid {p.border};
        padding: 16px 8px;
        outline: 0;
    }}
    QListWidget#nav::item {{
        padding: 10px 14px;
        margin: 2px 4px;
        border-radius: 6px;
        color: {p.rail_text};
    }}
    QListWidget#nav::item:hover {{
        background: {p.surface_alt};
    }}
    QListWidget#nav::item:selected {{
        background: {p.rail_selected_bg};
        color: {p.rail_selected_text};
    }}

    /* Cards */
    QFrame[card="true"] {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: 10px;
    }}

    /* Section + hint labels */
    QLabel[section="true"] {{
        color: {ACCENT};
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        padding-top: 4px;
    }}
    QLabel[hint="true"] {{
        color: {p.text_dim};
        font-size: 11px;
    }}
    QLabel[dim="true"] {{
        color: {p.text_dim};
    }}

    /* Buttons */
    QPushButton {{
        background: {p.surface};
        color: {p.text};
        border: 1px solid {p.border};
        border-radius: 6px;
        padding: 6px 14px;
    }}
    QPushButton:hover {{
        background: {p.surface_alt};
    }}
    QPushButton:disabled {{
        color: {p.text_muted};
        background: {p.surface};
    }}
    QPushButton[primary="true"] {{
        background: {ACCENT};
        color: {ACCENT_TEXT};
        border: 1px solid {ACCENT};
    }}
    QPushButton[primary="true"]:hover {{
        background: {ACCENT_HOVER};
        border-color: {ACCENT_HOVER};
    }}
    QPushButton[primary="true"]:pressed {{
        background: {ACCENT_PRESSED};
        border-color: {ACCENT_PRESSED};
    }}
    QPushButton[primary="true"]:disabled {{
        background: {p.surface_alt};
        color: {p.text_muted};
        border-color: {p.border};
    }}

    /* Inputs */
    QLineEdit, QComboBox, QAbstractSpinBox {{
        background: {p.surface};
        color: {p.text};
        border: 1px solid {p.border};
        border-radius: 6px;
        padding: 5px 8px;
        selection-background-color: {ACCENT};
        selection-color: {ACCENT_TEXT};
    }}
    QLineEdit:focus, QComboBox:focus, QAbstractSpinBox:focus {{
        border: 1px solid {ACCENT};
    }}
    QComboBox QAbstractItemView {{
        background: {p.surface};
        color: {p.text};
        selection-background-color: {ACCENT};
        selection-color: {ACCENT_TEXT};
        border: 1px solid {p.border};
    }}

    /* Lists / tables */
    QListWidget, QTableWidget, QTableView {{
        background: {p.surface};
        alternate-background-color: {p.surface_alt};
        border: 1px solid {p.border};
        border-radius: 8px;
        outline: 0;
    }}
    QListWidget::item:selected, QTableWidget::item:selected {{
        background: {ACCENT};
        color: {ACCENT_TEXT};
    }}
    QHeaderView::section {{
        background: {p.surface_alt};
        color: {p.text_dim};
        border: none;
        padding: 6px 10px;
        font-weight: 600;
    }}

    /* Checkboxes */
    QCheckBox {{
        spacing: 8px;
        color: {p.text};
    }}

    /* Scrollbars — keep them subtle */
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {p.border};
        border-radius: 4px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {p.text_muted};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    """


# ---- Helper factories used by pages ---------------------------------------

def card() -> QFrame:
    """A bordered, rounded surface for grouping related controls."""
    frame = QFrame()
    frame.setProperty("card", True)
    return frame


def section_label(text: str) -> QLabel:
    """A small caps accent label that introduces a card."""
    label = QLabel(text)
    label.setProperty("section", True)
    return label


def hint_label(text: str) -> QLabel:
    """Dim helper text shown below cards."""
    label = QLabel(text)
    label.setProperty("hint", True)
    label.setWordWrap(True)
    return label


def primary_button(text: str) -> QPushButton:
    """Accent-colored call-to-action button."""
    btn = QPushButton(text)
    btn.setProperty("primary", True)
    return btn


def mark_dim(widget: QWidget) -> QWidget:
    """Tag a widget so the global stylesheet renders it in the dim text color."""
    widget.setProperty("dim", True)
    return widget


def scroll_wrap(content: QWidget):
    """Wrap a page widget in a frameless vertical-only scroll area.

    Pages can grow taller than a small window; without this, content
    near the bottom (the model list, the language picker) gets clipped
    because the central widget has no scroll. The horizontal bar is
    suppressed so children sized via stretch fill the viewport instead
    of triggering a side-scroll.
    """
    from PySide6.QtWidgets import QScrollArea

    area = QScrollArea()
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setWidgetResizable(True)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    area.setWidget(content)
    return area
