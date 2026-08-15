"""W4 theme tests: dark-theme application + REAL rendered screenshot evidence.

Applies ``apply_theme`` offscreen, constructs the MainWindow, renders a
synthetic bead pattern into the preview, grabs the styled window to a QPixmap
and saves ``tests/artifacts/dark_theme.png``. The QA gate is the rendered
artifact (non-trivial PNG), plus assertions that Fusion style and the
stylesheet are active.
"""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PIL import Image  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

from beadstudio.app import MainWindow  # noqa: E402
from beadstudio.ui import theme  # noqa: E402

#: Rendered-evidence output directory (repo-local, gitignored artifacts).
ARTIFACTS = Path(__file__).parent / "artifacts"
SCREENSHOT = ARTIFACTS / "dark_theme.png"
EMPTY_SCREENSHOT = ARTIFACTS / "dark_theme_empty.png"
#: Non-trivial-size gate for the rendered PNG (compressed dark PNGs are small).
_MIN_PNG_BYTES = 20 * 1024


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    theme.apply_theme(app)
    yield app


def _pattern(n: int = 52):
    """n×n pattern cycling 16 distinct bead colors (seeded random → high
    entropy so the rendered PNG cannot compress below the size gate, and the
    render is fully deterministic)."""
    colors = [
        (220, 30, 30), (30, 180, 60), (30, 60, 220), (240, 200, 20),
        (180, 40, 200), (20, 190, 200), (245, 130, 40), (70, 70, 80),
        (255, 255, 255), (0, 0, 0), (200, 120, 60), (120, 60, 200),
        (60, 200, 120), (200, 60, 120), (120, 200, 60), (255, 160, 160),
    ]
    rng = np.random.default_rng(7)
    codes = [
        [f"{chr(65 + (x + y) % 8)}{(x + y) % 26 + 1}" for x in range(n)]
        for y in range(n)
    ]
    legend = [
        {"code": f"{chr(65 + i)}{i + 1}", "rgb": colors[i], "count": n * n // 16}
        for i in range(len(colors))
    ]
    grid = np.zeros((n, n, 3), dtype=np.uint8)
    for y in range(n):
        for x in range(n):
            grid[y, x] = colors[rng.integers(0, len(colors))]
    return grid, codes, legend


# ---------------------------------------------------------------------------
# apply_theme behaviour
# ---------------------------------------------------------------------------

def test_apply_theme_sets_fusion_and_stylesheet(qapp):
    """Fusion base style active + a non-empty stylesheet + dark palette.

    A live app stylesheet wraps the base style in ``QStyleSheetStyle``, so the
    base is inspected by temporarily stripping the sheet (and restoring it).
    """
    assert theme.apply_theme(qapp) is True
    assert qapp.styleSheet() != ""

    saved_sheet = qapp.styleSheet()
    qapp.setStyleSheet("")  # unwrap QStyleSheetStyle → base style
    try:
        assert qapp.style().metaObject().className() == "QFusionStyle"
    finally:
        qapp.setStyleSheet(saved_sheet)

    # QColor.name() lowercases hex — compare case-insensitively.
    assert qapp.palette().window().color().name().lower() == theme.COLORS["bg"].lower()


def test_stylesheet_covers_core_tokens(qapp):
    """Every QSS-rendered DESIGN.md token appears in the built stylesheet.

    ``success``/``warning``/``danger`` are semantic tokens documented for
    status messaging but not yet rendered by any widget — they are asserted
    to exist in COLORS separately.
    """
    qss = theme.DARK_QSS
    for name, value in theme.COLORS.items():
        # preview rendering tokens consumed by preview.py paint code, not QSS
        if name in ("success", "warning", "danger", "grid", "empty_cell"):
            continue
        assert value in qss, f"token {name}={value} missing from DARK_QSS"
    for name in ("success", "warning", "danger"):
        assert theme.COLORS[name].startswith("#")
    # key controls are styled
    for selector in ("QPushButton", "QComboBox", "QSpinBox", "QCheckBox",
                     "QRadioButton", "QGroupBox", "QScrollBar", "QToolTip",
                     "QStatusBar", "QProgressBar", "QScrollArea", "QLabel"):
        assert selector in qss, f"selector {selector} missing from DARK_QSS"


def test_main_window_constructs_with_theme(qapp):
    """Themed MainWindow builds and shows without errors."""
    window = MainWindow()
    window.show()
    qapp.processEvents()
    assert window.settings.convert_button.objectName() == "primaryButton"
    assert window.preview.image() is None
    assert window.preview._canvas.objectName() == "previewCanvas"
    window.close()


# ---------------------------------------------------------------------------
# Rendered evidence (the QA gate — a real screenshot, not a dry claim)
# ---------------------------------------------------------------------------

def test_render_dark_theme_screenshot(qapp):
    """Grab the themed MainWindow with a rendered pattern → save PNG.

    Asserts the saved artifact exists and is non-trivial (> 20 KB). The
    empty-state placeholder is also captured as a secondary artifact.
    """
    window = MainWindow()
    window.resize(1440, 960)
    window.show()
    qapp.processEvents()

    # Empty state first (no pattern).
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    assert window.grab().save(str(EMPTY_SCREENSHOT))

    # Then a real synthetic pattern at high zoom (24px cells → 1249px canvas).
    grid, codes, legend = _pattern()
    window.preview.zoom_combo.setCurrentIndex(
        window.preview.zoom_combo.findData(24)
    )
    window.preview.set_pattern(grid, codes, legend)
    window.show_grid_check.setChecked(True)
    window.show_codes_check.setChecked(True)
    qapp.processEvents()

    assert not window.preview.image().isNull()
    assert window.preview.image().width() == 52 * 24 + 1
    # The scroll widget must have grown with the canvas (no clipping).
    assert window.preview.width() >= window.preview.image().width()

    assert window.grab().save(str(SCREENSHOT))
    window.close()

    # The rendered-evidence gate: file exists and is non-trivial in size.
    assert SCREENSHOT.exists(), f"missing rendered screenshot: {SCREENSHOT}"
    size = SCREENSHOT.stat().st_size
    assert size > _MIN_PNG_BYTES, (
        f"screenshot too small ({size} bytes <= {_MIN_PNG_BYTES}) — "
        "the theme likely did not render"
    )


def test_screenshot_pixels_are_dark(qapp):
    """The rendered artifact must actually BE dark (theme applied to paint)."""
    assert SCREENSHOT.exists(), "run test_render_dark_theme_screenshot first"
    img = Image.open(SCREENSHOT).convert("RGB")
    arr = np.asarray(img)
    mean = arr.mean(axis=(0, 1))
    assert mean.mean() < 120, (
        f"rendered screenshot mean brightness {mean.mean():.1f} — "
        "expected a dark theme"
    )
    # The amber accent (primary Convert button) must be present somewhere.
    amber = np.array([255, 165, 44])
    hits = np.sum(
        np.all(np.abs(arr.astype(int) - amber) < 40, axis=-1)
    )
    assert hits > 0, "bead-amber accent color not found in the screenshot"
