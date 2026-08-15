"""Dark modern theme for BeadStudio — design tokens + QSS + apply_theme().

Single source of truth for the visual system (see ``DESIGN.md``). The
``COLORS`` dict mirrors DESIGN.md §2 verbatim; ``DARK_QSS`` is built from it
with f-strings so a token change re-skins every control. ``apply_theme``
switches the app to the **Fusion** style first (Qt's style whose drawing
primitives are QSS-friendly — without it many QSS rules are unreliable on
the native Windows style), then applies a matching dark QPalette (so any
un-styled widget still renders dark) and finally the stylesheet.

``apply_theme`` never raises: it is the app's theme entry point and the
tests call it directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

# --------------------------------------------------------------------------
# Design tokens (DESIGN.md §2) — semantic roles, hex values.
# --------------------------------------------------------------------------

COLORS: Dict[str, str] = {
    # -- surfaces (cool slate, layered) -----------------------------------
    "bg": "#1B1D21",  # window base / status bar / scrollbar track
    "panel": "#212328",  # group boxes (elevation +1)
    "surface": "#26292F",  # raised: inputs, buttons, combo popups
    "surface_hover": "#2E323A",  # hover for raised elements
    "surface_pressed": "#191B1F",  # pressed for raised elements
    # -- borders ------------------------------------------------------------
    "border": "#33373F",  # subtle dividers / default outlines
    "border_strong": "#424752",  # popups, tooltips, hover borders
    # -- text ---------------------------------------------------------------
    "text": "#E6E9EF",  # primary (13.4:1 on bg)
    "text_secondary": "#9AA3B2",  # hints, group titles, status (6.2:1)
    "text_disabled": "#5C6470",  # disabled controls
    "text_on_accent": "#1B1203",  # on amber (7.8:1)
    # -- accent: bead amber (DESIGN.md §2.4 — craft/warmth, not generic blue)
    "accent": "#FFA52C",
    "accent_hover": "#FFB85C",
    "accent_pressed": "#E08F1F",
    "accent_disabled": "#6B5A3F",
    "focus": "#FFA52C",  # keyboard focus ring (same hue as accent)
    # -- semantic status -----------------------------------------------------
    "success": "#3ECF8E",
    "warning": "#F2B84B",
    "danger": "#F0584A",
    # -- preview surface (DESIGN.md §8) --------------------------------------
    "preview_bg": "#16181C",  # recessed canvas card (darker than window)
    "empty_cell": "#26292F",  # None-cell fill — neutral dark
    "grid": "#3A3F48",  # grid lines — subtle on dark, legible over beads
    # -- scrollbar -------------------------------------------------------------
    "scrollbar_handle": "#4A505B",
    "scrollbar_handle_hover": "#5A6170",
}

#: Font stack (DESIGN.md §3): Segoe UI for en, Microsoft YaHei UI for zh.
FONT_FAMILIES = ["Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei"]
_BASE_FONT_SIZE = "9pt"

#: Combo-popup selection (DESIGN.md §6): accent-tinted bg + amber text.
_COMBO_SELECTED_BG = "#3A3322"

#: Repo asset folder (theme.py lives one level deeper than app.py, so it
#: needs an extra ``parent`` to reach the repo root).
_ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"


def _asset_uri(name: str) -> str:
    """Absolute QSS ``url()`` for an asset file (forward-slash path).

    Qt's QSS image loader cannot load ``data:image/...;base64`` URIs (they
    silently render nothing), so the arrow images ship as real PNG files and
    are referenced by absolute path, exactly like the window icon.
    """
    return f"url('{(_ASSETS_DIR / name).as_posix()}')"


#: Light chevron arrows (#9AA3B2 text_secondary) for the spinbox/combo
#: up/down subcontrols — visible on the dark surface. Real PNG assets, not
#: data-URIs (see ``_asset_uri``). Fusion's built-in arrows render dark on
#: the dark palette / stylesheet, so an explicit image is required.
_ARROW_UP = _asset_uri("arrow_up.png")
_ARROW_DOWN = _asset_uri("arrow_down.png")


def _qss() -> str:
    """Build the full dark stylesheet from ``COLORS`` (DESIGN.md §6-8)."""
    c = COLORS
    return f"""
* {{
    font-family: "{FONT_FAMILIES[0]}", "{FONT_FAMILIES[1]}", "{FONT_FAMILIES[2]}";
}}
QMainWindow, QDialog, QWidget {{
    background-color: {c["bg"]};
    color: {c["text"]};
    font-size: {_BASE_FONT_SIZE};
}}

/* ---------------- QLabel ---------------- */
QLabel {{
    color: {c["text"]};
    background-color: transparent;
}}
QLabel:disabled {{
    color: {c["text_disabled"]};
}}
QLabel#hintLabel {{
    color: {c["text_secondary"]};
    font-size: 8pt;
}}

/* ---------------- QGroupBox (DESIGN.md §6) ---------------- */
QGroupBox {{
    background-color: {c["panel"]};
    border: 1px solid {c["border"]};
    border-radius: 8px;
    margin-top: 12px;
    padding: 12px 12px 12px 12px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 4px;
    color: {c["text_secondary"]};
    font-weight: 600;
}}

/* ---------------- QPushButton (DESIGN.md §6) ---------------- */
QPushButton {{
    background-color: {c["surface"]};
    border: 1px solid {c["border"]};
    border-radius: 6px;
    padding: 5px 12px;
    color: {c["text"]};
    min-height: 18px;
}}
QPushButton:hover {{
    background-color: {c["surface_hover"]};
    border-color: {c["border_strong"]};
}}
QPushButton:pressed {{
    background-color: {c["surface_pressed"]};
}}
QPushButton:focus {{
    border: 1px solid {c["focus"]};
}}
QPushButton:disabled {{
    color: {c["text_disabled"]};
    background-color: {c["surface"]};
    border-color: {c["border"]};
}}
QPushButton:default {{
    border-color: {c["accent"]};
}}

/* Primary action (Generate Preview) — bead-amber call to action */
QPushButton#primaryButton {{
    background-color: {c["accent"]};
    border: 1px solid {c["accent"]};
    color: {c["text_on_accent"]};
    font-weight: 600;
}}
QPushButton#primaryButton:hover {{
    background-color: {c["accent_hover"]};
    border-color: {c["accent_hover"]};
}}
QPushButton#primaryButton:pressed {{
    background-color: {c["accent_pressed"]};
    border-color: {c["accent_pressed"]};
}}
QPushButton#primaryButton:focus {{
    border: 1px solid {c["focus"]};
}}
QPushButton#primaryButton:disabled {{
    background-color: {c["accent_disabled"]};
    border-color: {c["accent_disabled"]};
    color: {c["text_disabled"]};
}}

/* ---------------- QComboBox (DESIGN.md §6) ---------------- */
QComboBox {{
    background-color: {c["surface"]};
    border: 1px solid {c["border"]};
    border-radius: 6px;
    padding: 4px 8px;
    min-height: 18px;
    color: {c["text"]};
}}
QComboBox:hover {{
    border-color: {c["border_strong"]};
}}
QComboBox:pressed {{
    background-color: {c["surface_pressed"]};
}}
QComboBox:focus {{
    border: 1px solid {c["focus"]};
}}
QComboBox:disabled {{
    color: {c["text_disabled"]};
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
    border-left: 1px solid {c["border"]};
    border-top-right-radius: 5px;
    border-bottom-right-radius: 5px;
}}
QComboBox::drop-down:hover {{
    background-color: {c["surface_hover"]};
}}
QComboBox::down-arrow {{
    image: {_ARROW_DOWN};
    width: 10px;
    height: 6px;
}}
QComboBox QAbstractItemView {{
    background-color: {c["surface"]};
    border: 1px solid {c["border_strong"]};
    border-radius: 6px;
    padding: 2px;
    selection-background-color: {c["surface_hover"]};
    selection-color: {c["text"]};
    outline: 0;
}}
QComboBox QAbstractItemView::item {{
    padding: 4px 8px;
    border-radius: 4px;
    color: {c["text"]};
}}
QComboBox QAbstractItemView::item:selected {{
    background-color: {_COMBO_SELECTED_BG};
    color: {c["accent"]};
}}
QComboBox QAbstractItemView::item:hover {{
    background-color: {c["surface_hover"]};
}}

/* ---------------- QSpinBox (DESIGN.md §6) ---------------- */
QSpinBox {{
    background-color: {c["surface"]};
    border: 1px solid {c["border"]};
    border-radius: 6px;
    padding: 2px 6px;
    color: {c["text"]};
}}
QSpinBox:hover {{
    border-color: {c["border_strong"]};
}}
QSpinBox:focus {{
    border: 1px solid {c["focus"]};
}}
QSpinBox:disabled {{
    color: {c["text_disabled"]};
}}
QSpinBox::up-button, QSpinBox::down-button {{
    subcontrol-origin: border;
    width: 16px;
    border: 1px solid {c["border_strong"]};
    background-color: {c["surface_hover"]};
}}
QSpinBox::up-button {{
    subcontrol-position: top right;
    border-top-right-radius: 5px;
}}
QSpinBox::down-button {{
    subcontrol-position: bottom right;
    border-bottom-right-radius: 5px;
}}
/* The up/down buttons get a LIGHTER surface + visible border so the arrow
   hit-areas read clearly, and the arrows themselves are explicit light
   chevron images (real PNG assets — Qt's QSS loader silently drops
   ``data:image`` URIs, and Fusion's built-in arrows render dark on the
   dark palette/stylesheet). */
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
    background-color: {c["scrollbar_handle_hover"]};
    border-color: {c["text_secondary"]};
}}
QSpinBox::up-button:pressed, QSpinBox::down-button:pressed {{
    background-color: {c["surface_pressed"]};
}}
QSpinBox::up-arrow {{
    image: {_ARROW_UP};
    width: 10px;
    height: 6px;
}}
QSpinBox::down-arrow {{
    image: {_ARROW_DOWN};
    width: 10px;
    height: 6px;
}}

/* ---------------- QCheckBox / QRadioButton (DESIGN.md §6) ---------------- */
QCheckBox, QRadioButton {{
    color: {c["text"]};
    spacing: 6px;
}}
QCheckBox:disabled, QRadioButton:disabled {{
    color: {c["text_disabled"]};
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {c["border_strong"]};
    background-color: {c["surface"]};
}}
QCheckBox::indicator {{
    border-radius: 3px;
}}
QRadioButton::indicator {{
    border-radius: 7px;
}}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    background-color: {c["surface_hover"]};
    border-color: {c["border_strong"]};
}}
QCheckBox::indicator:pressed, QRadioButton::indicator:pressed {{
    background-color: {c["surface_pressed"]};
}}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background-color: {c["accent"]};
    border-color: {c["accent"]};
}}
QCheckBox::indicator:checked:hover, QRadioButton::indicator:checked:hover {{
    background-color: {c["accent_hover"]};
    border-color: {c["accent_hover"]};
}}
QCheckBox::indicator:checked:pressed, QRadioButton::indicator:checked:pressed {{
    background-color: {c["accent_pressed"]};
    border-color: {c["accent_pressed"]};
}}
QCheckBox::indicator:checked:disabled, QRadioButton::indicator:checked:disabled {{
    background-color: {c["accent_disabled"]};
    border-color: {c["accent_disabled"]};
}}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
    background-color: {c["surface"]};
    border-color: {c["border"]};
}}
QCheckBox::indicator:focus, QRadioButton::indicator:focus {{
    border: 1px solid {c["focus"]};
}}

/* ---------------- QLineEdit (future-proofing) ---------------- */
QLineEdit {{
    background-color: {c["surface"]};
    border: 1px solid {c["border"]};
    border-radius: 6px;
    padding: 4px 8px;
    color: {c["text"]};
    selection-background-color: {c["accent"]};
    selection-color: {c["text_on_accent"]};
}}
QLineEdit:focus {{
    border: 1px solid {c["focus"]};
}}
QLineEdit:disabled {{
    color: {c["text_disabled"]};
}}

/* ---------------- QScrollArea / preview canvas (DESIGN.md §8) ---------------- */
QScrollArea {{
    background-color: {c["preview_bg"]};
    border: 1px solid {c["border"]};
    border-radius: 8px;
}}
QScrollArea > QWidget > QWidget {{
    background-color: {c["preview_bg"]};
}}
QWidget#previewCanvas {{
    background-color: {c["preview_bg"]};
    border: 1px solid {c["border"]};
    border-radius: 8px;
}}

/* ---------------- QScrollBar (DESIGN.md §6, dark + slim) ---------------- */
QScrollBar:vertical {{
    background: {c["bg"]};
    width: 12px;
    margin: 0;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: {c["scrollbar_handle"]};
    border-radius: 6px;
    min-height: 24px;
    margin: 2px;
}}
QScrollBar::handle:vertical:hover {{
    background: {c["scrollbar_handle_hover"]};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
    background: none;
    border: none;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
QScrollBar:horizontal {{
    background: {c["bg"]};
    height: 12px;
    border: none;
}}
QScrollBar::handle:horizontal {{
    background: {c["scrollbar_handle"]};
    border-radius: 6px;
    min-width: 24px;
    margin: 2px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {c["scrollbar_handle_hover"]};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
    background: none;
    border: none;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
}}

/* ---------------- QToolTip (DESIGN.md §6) ---------------- */
QToolTip {{
    background-color: {c["surface_hover"]};
    color: {c["text"]};
    border: 1px solid {c["border_strong"]};
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 8pt;
}}

/* ---------------- QStatusBar (DESIGN.md §6) ---------------- */
QStatusBar {{
    background-color: {c["bg"]};
    border-top: 1px solid {c["border"]};
    color: {c["text_secondary"]};
}}
QStatusBar::item {{
    border: none;
}}

/* ---------------- QProgressBar (batch dialog) ---------------- */
QProgressBar {{
    background-color: {c["surface"]};
    border: 1px solid {c["border"]};
    border-radius: 5px;
    text-align: center;
    color: {c["text"]};
    height: 14px;
}}
QProgressBar::chunk {{
    background-color: {c["accent"]};
    border-radius: 4px;
}}

/* ---------------- QMenu (context menus / combo popups) ---------------- */
QMenu {{
    background-color: {c["surface"]};
    border: 1px solid {c["border_strong"]};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{
    padding: 5px 24px 5px 12px;
    border-radius: 4px;
    color: {c["text"]};
}}
QMenu::item:selected {{
    background-color: {c["surface_hover"]};
    color: {c["accent"]};
}}
QMenu::item:disabled {{
    color: {c["text_disabled"]};
}}
QMenu::separator {{
    height: 1px;
    background: {c["border"]};
    margin: 4px 8px;
}}

/* ---------------- QSplitter ---------------- */
QSplitter::handle {{
    background-color: {c["border"]};
}}
QSplitter::handle:horizontal {{
    width: 2px;
}}
QSplitter::handle:vertical {{
    height: 2px;
}}
"""

#: The full dark stylesheet (built once at import; tokens are immutable by
#: convention — call ``apply_theme`` again after changing ``COLORS``).
DARK_QSS: str = _qss()


def _build_palette() -> QPalette:
    """Dark QPalette from the tokens — covers anything QSS cannot reach."""
    c = COLORS
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(c["bg"]))
    pal.setColor(QPalette.WindowText, QColor(c["text"]))
    pal.setColor(QPalette.Base, QColor(c["surface"]))
    pal.setColor(QPalette.AlternateBase, QColor(c["surface_hover"]))
    pal.setColor(QPalette.ToolTipBase, QColor(c["surface_hover"]))
    pal.setColor(QPalette.ToolTipText, QColor(c["text"]))
    pal.setColor(QPalette.Text, QColor(c["text"]))
    pal.setColor(QPalette.PlaceholderText, QColor(c["text_disabled"]))
    pal.setColor(QPalette.Button, QColor(c["surface"]))
    pal.setColor(QPalette.ButtonText, QColor(c["text"]))
    pal.setColor(QPalette.BrightText, QColor("#FFFFFF"))
    pal.setColor(QPalette.Highlight, QColor(c["accent"]))
    pal.setColor(QPalette.HighlightedText, QColor(c["text_on_accent"]))
    pal.setColor(QPalette.Link, QColor(c["accent"]))
    pal.setColor(QPalette.LinkVisited, QColor(c["accent_hover"]))

    # Disabled roles — muted, non-interactive.
    disabled = {
        QPalette.WindowText: c["text_disabled"],
        QPalette.Text: c["text_disabled"],
        QPalette.ButtonText: c["text_disabled"],
        QPalette.Base: c["surface"],
        QPalette.Button: c["surface"],
        QPalette.Highlight: c["accent_disabled"],
        QPalette.HighlightedText: c["text_disabled"],
    }
    for role, color in disabled.items():
        pal.setColor(QPalette.Disabled, role, QColor(color))
    return pal


def apply_theme(app: QApplication) -> bool:
    """Apply the bead-dark theme to a QApplication (Fusion + palette + QSS).

    * Switches to the **Fusion** style first — its drawing primitives honour
      QSS reliably (the native Windows style ignores many rules).
    * Sets a dark QPalette so any widget QSS does not reach stays dark.
    * Applies :data:`DARK_QSS` as the app-wide stylesheet.

    Idempotent and side-effect-free beyond the app state. Returns True on
    success; never raises.
    """
    app.setStyle("Fusion")
    app.setPalette(_build_palette())
    app.setStyleSheet(DARK_QSS)

    # Font fallback for CJK (§3): enforce the en+zh stack at QFont level too,
    # so non-QSS text (dialogs, popups) also picks Segoe UI / YaHei UI.
    font = app.font()
    font.setFamilies(FONT_FAMILIES)
    app.setFont(font)
    return True
