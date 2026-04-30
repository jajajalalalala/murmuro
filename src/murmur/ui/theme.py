"""Murmur visual theme.

Single accent color (warm terracotta orange), explicit light/dark
palettes, and a small set of helper factories so pages can produce
styled chrome (cards, titles, primary buttons) without hand-rolling
stylesheets.

The accent appears in:

* the left-rail's selected row,
* primary action buttons (Record, Restart Now, Use, Download),
* focus rings on text fields / dropdowns,
* the checkbox indicator fill.

Both palettes deliberately push surface and text further apart than
the Qt default — section labels and "mid"-toned subtitles otherwise
end up nearly indistinguishable from the window background in dark
mode.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton, QWidget

# Repo-rooted path to bundled icon assets. Qt stylesheets accept absolute
# file URLs in the form ``url(/abs/path/to.png)`` — we resolve the path
# at import time so any later substitution into the stylesheet has the
# right string. The same pattern works inside a PyInstaller bundle
# because ``assets/`` is copied alongside ``src/`` at build time.
_ASSETS_DIR = Path(__file__).resolve().parents[3] / "assets"
_CHECK_ICON_URL = (_ASSETS_DIR / "check.png").as_posix()

# ---- Accent ---------------------------------------------------------------

# Warm terracotta orange — picked to read as "premium" rather than
# "Tailwind orange-500 toy app." Saturated enough to anchor the UI on
# either light or dark surfaces, muted enough that it doesn't fight the
# eye next to neutral text.
ACCENT = "#dd6f3a"        # primary action / selection
ACCENT_HOVER = "#e8865a"
ACCENT_PRESSED = "#b85525"
ACCENT_TEXT = "#ffffff"   # text on accent backgrounds

# State dot colors — punchier than Qt defaults, readable on either surface.
# BUSY moved off amber so it doesn't fight the new orange accent.
STATE_IDLE = "#94a3b8"      # slate-400
STATE_RECORDING = "#ef4444" # red-500
STATE_BUSY = "#0ea5e9"      # sky-500
STATE_OK = "#10b981"        # emerald-500
STATE_DANGER = "#ef4444"    # destructive button text


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


# Light palette: warm-neutral creams (no purple tint) that complement
# the terracotta accent rather than fighting it.
LIGHT = Palette(
    name="light",
    window="#faf7f3",
    surface="#ffffff",
    surface_alt="#f3ede5",
    border="#e7dfd3",
    text="#1f1a14",
    text_dim="#5d564c",
    text_muted="#8b8478",
    rail_bg="#f1ebe2",
    rail_text="#3d3730",
    rail_selected_bg=ACCENT,
    rail_selected_text=ACCENT_TEXT,
)

# Dark palette: deep warm-neutral charcoals with a faint warm undertone.
# Pure-black or blue-tinted darks make the orange accent look gaudy;
# warm-neutral darks let it sit naturally.
DARK = Palette(
    name="dark",
    window="#171411",
    surface="#211d18",
    surface_alt="#2b2620",
    border="#37312a",
    text="#f1ece4",
    text_dim="#b8aea0",
    text_muted="#857d72",
    rail_bg="#1c1813",
    rail_text="#d4cbbe",
    rail_selected_bg=ACCENT,
    rail_selected_text=ACCENT_TEXT,
)


# ---- Theme detection + application ----------------------------------------

def _detect_palette(app: QApplication) -> Palette:
    """Pick a palette to match the system theme, defaulting to LIGHT.

    Qt 6.5 added ``styleHints().colorScheme()``. On older builds we fall
    back to inspecting the default palette's window lightness. When
    neither approach gives a confident answer we now default to LIGHT
    rather than DARK — the maintainer prefers the brighter look on
    first launch and can flip to dark via the rail toggle.

    Tests that set ``MURMUR_FORCE_THEME=light|dark`` skip detection
    entirely.
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

    # Heuristic fallback: sample the existing window-color lightness.
    # Bias toward LIGHT (only flip to DARK on a clearly-dark surface)
    # so an indeterminate Qt build still launches in the brighter mode.
    win = app.palette().color(QPalette.ColorRole.Window)
    return DARK if win.lightness() < 80 else LIGHT


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

    /* Brand header at the top of the left rail */
    QWidget#brandHeader {{
        background: {p.rail_bg};
        border-right: 1px solid {p.border};
        border-bottom: 1px solid {p.border};
    }}
    QLabel#brandText {{
        color: {p.text};
        font-size: 15px;
        font-weight: 700;
        letter-spacing: -0.01em;
    }}

    /* Theme toggle at the bottom of the left rail */
    QPushButton#themeToggle {{
        background: transparent;
        color: {p.text_dim};
        border: 1px solid {p.border};
        border-radius: 6px;
        padding: 6px 10px;
        font-size: 12px;
        text-align: center;
    }}
    QPushButton#themeToggle:hover {{
        background: {p.surface_alt};
        color: {p.text};
        border-color: {p.text_muted};
    }}

    /* Left-rail navigation */
    QListWidget#nav {{
        background: {p.rail_bg};
        color: {p.rail_text};
        border: none;
        border-right: 1px solid {p.border};
        padding: 12px 8px;
        outline: 0;
    }}
    QListWidget#nav::item {{
        padding: 10px 14px;
        margin: 2px 4px;
        border-radius: 8px;
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

    /* Card titles (sentence-case, replaces the small-caps section
       labels for primary card headings — those felt heavy/bureaucratic
       when stacked four to a page). */
    QLabel[cardTitle="true"] {{
        color: {p.text};
        font-size: 14px;
        font-weight: 600;
    }}
    /* Section labels stay for true page-level eyebrows; tone them down
       so they read as metadata, not chapter dividers. */
    QLabel[section="true"] {{
        color: {p.text_muted};
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.04em;
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
    QLabel[mono="true"] {{
        font-family: "SF Mono", "JetBrains Mono", "Menlo", monospace;
        font-size: 11px;
        color: {p.text_dim};
    }}

    /* Buttons — three tiers:
       - default: ghost (transparent border, surface background on hover)
       - primary: filled accent
       - destructive: ghost with red text on hover */
    QPushButton {{
        background: transparent;
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
        border-color: {p.border};
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
    QPushButton[destructive="true"] {{
        color: {p.text_dim};
        border: 1px solid {p.border};
        background: transparent;
    }}
    QPushButton[destructive="true"]:hover {{
        color: {STATE_DANGER};
        border-color: {STATE_DANGER};
        background: transparent;
    }}
    /* The small × clear button on the hotkey field — borderless, dim,
       hover red. setProperty("clear", True) marks it. */
    QPushButton[clear="true"] {{
        background: transparent;
        border: none;
        color: {p.text_muted};
        font-size: 16px;
        padding: 0 6px;
        min-width: 22px;
        min-height: 22px;
    }}
    QPushButton[clear="true"]:hover {{
        color: {STATE_DANGER};
    }}

    /* Inputs */
    QLineEdit, QAbstractSpinBox {{
        background: {p.surface};
        color: {p.text};
        border: 1px solid {p.border};
        border-radius: 6px;
        padding: 5px 8px;
        selection-background-color: {ACCENT};
        selection-color: {ACCENT_TEXT};
    }}
    QLineEdit:focus, QAbstractSpinBox:focus {{
        border: 1px solid {ACCENT};
    }}

    /* QComboBox: drop the visible inner divider between the field and
       the drop-down arrow (Qt's default leaves a vertical line on the
       right that didn't follow the rounded radius — the "cut by force"
       look). The combobox is now one continuous rounded surface. */
    QComboBox {{
        background: {p.surface};
        color: {p.text};
        border: 1px solid {p.border};
        border-radius: 6px;
        padding: 5px 8px;
        padding-right: 28px;  /* room for the chevron */
        selection-background-color: {ACCENT};
        selection-color: {ACCENT_TEXT};
    }}
    QComboBox:focus {{
        border: 1px solid {ACCENT};
    }}
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 24px;
        border: none;
        background: transparent;
        margin: 0 4px 0 0;
    }}
    QComboBox::down-arrow {{
        width: 10px;
        height: 10px;
    }}
    QComboBox QAbstractItemView {{
        background: {p.surface};
        color: {p.text};
        selection-background-color: {ACCENT};
        selection-color: {ACCENT_TEXT};
        border: 1px solid {p.border};
        border-radius: 6px;
        outline: 0;
        padding: 4px;
    }}

    /* Lists / tables */
    QListWidget, QTableWidget, QTableView {{
        background: {p.surface};
        alternate-background-color: {p.surface_alt};
        border: 1px solid {p.border};
        border-radius: 8px;
        outline: 0;
    }}
    QListWidget::item {{
        padding: 8px 12px;
        border-radius: 6px;
        margin: 2px 4px;
    }}
    QListWidget::item:hover {{
        background: {p.surface_alt};
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

    /* Transcripts list — drop the inherited item padding so the row
       widget's own internal layout fully controls its height. The
       padding/margin in the generic ::item rule above otherwise eats
       into the widget area and short transcripts render squished. */
    QListWidget#transcripts::item {{
        padding: 0;
        margin: 0;
        border-radius: 0;
    }}
    QListWidget#transcripts::item:hover {{
        background: {p.surface_alt};
    }}
    QListWidget#transcripts::item:selected {{
        background: {p.surface_alt};
        color: {p.text};
    }}

    /* Progress bars (model downloads) */
    QProgressBar {{
        background: {p.surface_alt};
        border: 1px solid {p.border};
        border-radius: 6px;
        text-align: center;
        color: {p.text};
        font-size: 11px;
        min-height: 18px;
    }}
    QProgressBar::chunk {{
        background-color: {ACCENT};
        border-radius: 5px;
    }}

    /* Checkboxes — custom indicator so they no longer look like the
       Office-software defaults. 16x16 rounded square; border-only when
       unchecked, accent-filled with a white tick when checked. */
    QCheckBox {{
        spacing: 10px;
        color: {p.text};
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 1.5px solid {p.text_muted};
        border-radius: 4px;
        background: {p.surface};
    }}
    QCheckBox::indicator:hover {{
        border-color: {ACCENT};
    }}
    QCheckBox::indicator:checked {{
        background: {ACCENT};
        border-color: {ACCENT};
        image: url({_CHECK_ICON_URL});
    }}
    QCheckBox::indicator:checked:hover {{
        background: {ACCENT_HOVER};
        border-color: {ACCENT_HOVER};
    }}
    QCheckBox::indicator:disabled {{
        border-color: {p.border};
        background: {p.surface_alt};
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
    """A small caps muted-text label for page-level eyebrows."""
    label = QLabel(text)
    label.setProperty("section", True)
    return label


def card_title(text: str) -> QLabel:
    """Sentence-case bold title for the top of a card.

    Replaces the previous small-caps accent treatment everywhere a
    card needs a heading — that style now stays only on true page
    eyebrows where the eye benefits from a quieter visual marker.
    """
    label = QLabel(text)
    label.setProperty("cardTitle", True)
    return label


def mono_label(text: str) -> QLabel:
    """A monospace label, used for paths and key specs in About."""
    label = QLabel(text)
    label.setProperty("mono", True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
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


def destructive_button(text: str) -> QPushButton:
    """Ghost button that hovers to red — for Delete-style actions.

    Visually quieter than the primary button so destructive actions
    don't compete with the safe ones (Use, Download).
    """
    btn = QPushButton(text)
    btn.setProperty("destructive", True)
    return btn


def clear_button(text: str = "×") -> QPushButton:
    """Borderless ×-style button with a dim/red hover. Used for the
    hotkey field's clear affordance and any similar inline cancels."""
    btn = QPushButton(text)
    btn.setProperty("clear", True)
    btn.setFlat(True)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
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
