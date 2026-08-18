"""UI tests: i18n, settings panel, preview rendering and the full convert flow.

All Qt interaction runs on the offscreen platform (env var set before any
PySide6 import), matching tests/test_smoke.py.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PIL import Image  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

from beadstudio.app import MainWindow  # noqa: E402
from beadstudio.core.palette import get_series, list_brands  # noqa: E402
from beadstudio.ui.i18n import get_language, set_language, tr  # noqa: E402
from beadstudio.ui.preview import PreviewWidget, build_grid_rgb  # noqa: E402
from beadstudio.ui.settings_panel import SettingsPanel  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _restore_language():
    """Restore the module-level i18n language after each test."""
    original = get_language()
    yield
    set_language(original)


# ---------------------------------------------------------------------------
# i18n
# ---------------------------------------------------------------------------

def test_tr_zh_locale():
    assert tr("brand", "zh") == "品牌"
    assert tr("width", "zh") == "宽度（珠数）"
    assert tr("window_title", "zh") == "BeadStudio 豆趣工坊"


def test_tr_en_locale():
    assert tr("brand", "en") == "Brand"
    assert tr("width", "en") == "Width (beads)"
    assert tr("window_title", "en") == "BeadStudio"


def test_tr_default_follows_set_language():
    set_language("zh")
    assert tr("brand") == "品牌"
    set_language("en")
    assert tr("brand") == "Brand"


def test_tr_unknown_key_falls_back_to_key():
    assert tr("no_such_key", "zh") == "no_such_key"
    assert tr("no_such_key", "en") == "no_such_key"


# ---------------------------------------------------------------------------
# Settings panel
# ---------------------------------------------------------------------------

def test_settings_brand_combo_has_21_brands(qapp):
    panel = SettingsPanel()
    assert panel.brand_combo.count() == 21
    for brand in list_brands():
        assert panel.brand_combo.findText(brand) >= 0


def test_settings_default_params(qapp):
    panel = SettingsPanel()
    params = panel.params()
    assert params["brand"] == panel.brand_combo.currentText()
    assert params["width"] == 100
    assert params["height"] is None  # 0 = auto-aspect
    assert params["cell_mode"] == "mean"  # bot's fixed default
    assert params["dither"] is False
    assert params["image_path"] is None


def test_settings_series_shown_for_mard(qapp):
    panel = SettingsPanel()
    panel.show()
    qapp.processEvents()
    panel.set_brand("mard")
    qapp.processEvents()
    assert panel.series_active is True
    assert panel.colors_active is False
    assert panel.series_box.isVisible()
    assert not panel.max_colors_box.isVisible()
    # options = "全部" + get_series("mard")
    expected = ["全部"] + get_series("mard")
    assert panel.series_combo.count() == len(expected)
    for item in expected:
        assert panel.series_combo.findText(item) >= 0
    panel.close()


def test_settings_colors_shown_for_perler(qapp):
    panel = SettingsPanel()
    panel.show()
    qapp.processEvents()
    panel.set_brand("perler")
    qapp.processEvents()
    assert panel.series_active is False
    assert panel.colors_active is True
    assert not panel.series_box.isVisible()
    assert panel.max_colors_box.isVisible()
    assert get_series("perler") == []  # flat brand sanity
    # flat brand: max_colors captured, series_range always None
    params = panel.params()
    assert params["series_range"] is None
    assert params["max_colors"] == 30
    panel.max_colors_spin.setValue(0)
    assert panel.params()["max_colors"] is None  # 0 = unlimited
    panel.close()


def test_settings_dither_disabled_in_mean_mode(qapp):
    panel = SettingsPanel()
    panel.show()
    qapp.processEvents()
    panel.mode_radios["dominant"].setChecked(True)
    qapp.processEvents()
    assert panel.dither_check.isEnabled()
    assert panel.dither_hint.isHidden()
    panel.mode_radios["mean"].setChecked(True)
    qapp.processEvents()
    assert not panel.dither_check.isEnabled()  # mean auto-disables dither
    assert panel.dither_check.isChecked() is False
    assert panel.dither_hint.isVisible()
    panel.close()


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------

def test_preview_render_dimensions(qapp):
    grid = np.zeros((3, 4, 3), dtype=np.uint8)
    grid[:, :] = (255, 0, 0)  # solid red 3x4 pattern
    codes = [["R1"] * 4 for _ in range(3)]
    legend = [{"code": "R1", "rgb": (255, 0, 0), "count": 12}]

    preview = PreviewWidget()
    preview.zoom_combo.setCurrentIndex(preview.zoom_combo.findData(8))
    image = preview.render(grid, codes, legend)
    assert image is not None
    assert not image.isNull()
    assert image.width() == 4 * 8 + 1  # W*c + border pixel
    assert image.height() == 3 * 8 + 1


def test_preview_render_null_without_pattern(qapp):
    preview = PreviewWidget()
    assert preview.render().isNull()


def test_preview_zoom_changes_image_size(qapp):
    grid = np.full((2, 2, 3), (0, 0, 255), dtype=np.uint8)
    codes = [["B1", "B1"], ["B1", "B1"]]
    legend = [{"code": "B1", "rgb": (0, 0, 255), "count": 4}]
    preview = PreviewWidget()
    preview.set_pattern(grid, codes, legend)
    assert preview.image().width() == 2 * 16 + 1  # default cell = 16
    preview.zoom_combo.setCurrentIndex(preview.zoom_combo.findData(4))
    assert preview.image().width() == 2 * 4 + 1


def test_build_grid_rgb_from_codes_legend():
    codes = [["A", "B"], [None, "A"]]
    legend = [{"code": "A", "rgb": (10, 20, 30)}, {"code": "B", "rgb": (40, 50, 60)}]
    grid = build_grid_rgb(codes, legend)
    assert grid.shape == (2, 2, 3)
    assert grid.dtype == np.uint8
    assert tuple(grid[0, 0]) == (10, 20, 30)
    assert tuple(grid[0, 1]) == (40, 50, 60)
    assert tuple(grid[1, 0]) == (255, 255, 255)  # empty cell → white
    assert tuple(grid[1, 1]) == (10, 20, 30)


# ---------------------------------------------------------------------------
# Full convert flow (offscreen, direct method call)
# ---------------------------------------------------------------------------

def _make_red_image(path) -> str:
    array = np.full((64, 64, 3), (220, 30, 30), dtype=np.uint8)
    Image.fromarray(array).save(path)
    return str(path)


def test_convert_flow_mard_mean(qapp, tmp_path):
    png = tmp_path / "red.png"
    image_path = _make_red_image(png)

    window = MainWindow()
    window.show()
    qapp.processEvents()

    window.settings.set_image_path(image_path)
    window.settings.width_spin.setValue(16)
    window.settings.set_brand("mard")  # series combo defaults to 全部

    # direct method call instead of real mouse clicks
    window._convert()

    result = window._last_result
    assert result is not None
    assert result.width == 16
    assert result.height == 16  # square source → auto height
    assert result.colors_used >= 1

    # preview got a non-empty pattern
    assert window.preview.grid_rgb is not None
    assert window.preview.grid_rgb.size > 0
    assert window.preview.image() is not None
    assert not window.preview.image().isNull()
    # status bar reports the conversion
    assert "转换完成" in window.status_label.text()
    window.close()


def test_param_change_does_not_auto_convert(qapp, tmp_path):
    """Param changes must NOT auto-convert (no live preview / debounce) —
    only an explicit Generate Preview click runs the conversion."""
    png = tmp_path / "red.png"
    image_path = _make_red_image(png)

    window = MainWindow()
    window.show()
    qapp.processEvents()

    window.settings.set_image_path(image_path)
    window.settings.width_spin.setValue(16)
    window.settings.set_brand("mard")
    qapp.processEvents()

    # Implicit conversion must NOT have happened while setting params.
    assert window._last_result is None
    assert window.preview.image() is None
    assert "转换完成" not in window.status_label.text()

    # Explicit Generate Preview click DOES convert (full signal path).
    window.settings.generate_preview_button.click()
    qapp.processEvents()
    assert window._last_result is not None
    assert window._last_result.width == 16
    assert window.preview.grid_rgb is not None
    assert not window.preview.image().isNull()
    assert "转换完成" in window.status_label.text()

    # A later param change still must not re-convert on its own.
    window.settings.width_spin.setValue(24)
    qapp.processEvents()
    assert window._last_result.width == 16  # unchanged: still the click result
    window.close()
