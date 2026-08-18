"""W6a UI tests: advanced (EdgeConfig) parameters.

Covers the collapsible advanced group, the six sliders' defaults, the
params()["edge_config"] contract (None at defaults, built when changed), the
LOW < HIGH linkage that keeps the GUI from ever constructing an invalid
EdgeConfig, the reset button, and the end-to-end convert() wiring (including
the preview using the Pattern's grid_rgb directly).

Qt runs on the offscreen platform (env var set before any PySide6 import),
matching tests/test_smoke.py.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PIL import Image  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

from beadstudio.app import MainWindow  # noqa: E402
from beadstudio.core.models import EdgeConfig  # noqa: E402
from beadstudio.ui.settings_panel import SettingsPanel  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_image(path, color=(220, 30, 30), size=(64, 64)) -> str:
    array = np.full((size[1], size[0], 3), color, dtype=np.uint8)
    Image.fromarray(array).save(path)
    return str(path)


# ---------------------------------------------------------------------------
# Collapsible group
# ---------------------------------------------------------------------------

def test_advanced_group_collapsible(qapp):
    """The advanced group exists, is collapsed by default (checked=False means
    collapsed), and expanding makes the sliders usable/visible."""
    panel = SettingsPanel()
    panel.show()
    qapp.processEvents()

    group = panel.advanced_group
    assert group.isCheckable(), "checkable title = the Qt collapse toggle"
    assert not group.isChecked(), "collapsed by default (unchecked = collapsed)"
    assert not panel.advanced_contents.isVisible()
    assert not panel.advanced_sliders["smoothness"].isEnabled()

    group.setChecked(True)  # expand
    qapp.processEvents()
    assert panel.advanced_contents.isVisible()
    assert panel.advanced_sliders["smoothness"].isEnabled()
    panel.close()


# ---------------------------------------------------------------------------
# Slider defaults + params() contract
# ---------------------------------------------------------------------------

def test_sliders_default_to_edgeconfig_defaults(qapp):
    """All six sliders start at the engine's EdgeConfig() defaults."""
    panel = SettingsPanel()
    ec = EdgeConfig()
    panel.show()
    qapp.processEvents()

    assert panel.advanced_sliders["smoothness"].value() == ec.mean_edge_range_low
    assert panel.advanced_sliders["edge_sensitivity"].value() == int(
        ec.mean_edge_deltae_threshold
    )
    assert panel.advanced_sliders["thin_line"].value() == int(
        round(ec.stroke_min_fraction * 100)
    )
    assert panel.advanced_sliders["min_line_len"].value() == ec.stroke_min_length
    assert panel.advanced_sliders["high_boundary"].value() == ec.mean_edge_range_high
    assert panel.advanced_sliders["line_color_diff"].value() == int(
        ec.stroke_min_deltae
    )
    panel.close()


def test_params_edge_config_none_when_defaults(qapp):
    """params()['edge_config'] is None while every slider is at its default —
    this preserves the pre-W6 behavior (engine uses EdgeConfig())."""
    panel = SettingsPanel()
    assert panel.params()["edge_config"] is None
    panel.close()


def test_params_edge_config_built_when_changed(qapp):
    """Moving a slider yields an EdgeConfig carrying that value."""
    panel = SettingsPanel()
    panel.advanced_sliders["smoothness"].setValue(160)

    config = panel.params()["edge_config"]
    assert isinstance(config, EdgeConfig)
    assert config.mean_edge_range_low == 160
    assert config.mean_edge_range_high == 180  # untouched slider stays default
    panel.close()


# ---------------------------------------------------------------------------
# LOW < HIGH linkage (the GUI must never build an invalid EdgeConfig)
# ---------------------------------------------------------------------------

def test_low_high_linkage(qapp):
    """Raising smoothness up to the high-boundary clamps the high slider to
    low + 1; dragging the high slider below low snaps it back. params()
    constructs a validating EdgeConfig in both cases."""
    panel = SettingsPanel()
    high_slider = panel.advanced_sliders["high_boundary"]

    panel.advanced_sliders["smoothness"].setValue(180)  # == default high
    assert high_slider.value() == 181  # clamped to low + 1

    config = panel.params()["edge_config"]
    assert isinstance(config, EdgeConfig)  # constructing it validates fine
    assert config.mean_edge_range_low < config.mean_edge_range_high

    # Reverse drag: lowering high below a raised low snaps it back above.
    panel.advanced_sliders["smoothness"].setValue(150)
    high_slider.setValue(100)  # Qt clamps to the slider minimum (120), then
    # the linkage clamps it again to low + 1
    assert high_slider.value() == 151

    config = panel.params()["edge_config"]
    assert isinstance(config, EdgeConfig)
    assert config.mean_edge_range_low < config.mean_edge_range_high
    panel.close()


# ---------------------------------------------------------------------------
# Reset button
# ---------------------------------------------------------------------------

def test_reset_defaults_button(qapp):
    """Changed sliders + reset → all back to defaults, edge_config back to None."""
    panel = SettingsPanel()
    panel.show()
    # The reset button lives inside the collapsible group, which is disabled
    # while collapsed — expand it first (as a user would).
    panel.advanced_group.setChecked(True)
    qapp.processEvents()

    panel.advanced_sliders["smoothness"].setValue(160)
    panel.advanced_sliders["edge_sensitivity"].setValue(20)
    panel.advanced_sliders["min_line_len"].setValue(8)
    assert panel.params()["edge_config"] is not None

    panel.reset_defaults_button.click()

    defaults = EdgeConfig()
    assert panel.advanced_sliders["smoothness"].value() == defaults.mean_edge_range_low
    assert panel.advanced_sliders["edge_sensitivity"].value() == int(
        defaults.mean_edge_deltae_threshold
    )
    assert panel.advanced_sliders["min_line_len"].value() == defaults.stroke_min_length
    assert panel.params()["edge_config"] is None
    panel.close()


# ---------------------------------------------------------------------------
# End-to-end: convert() accepts edge_config; preview uses result.grid_rgb
# ---------------------------------------------------------------------------

def test_convert_accepts_edge_config_end_to_end(tmp_path, qapp):
    """A modified slider flows an EdgeConfig into convert() without raising and
    the preview renders the Pattern's grid_rgb; the all-defaults path (None)
    also runs cleanly."""
    png = tmp_path / "red.png"
    image_path = _make_image(png)

    window = MainWindow()
    window.show()
    qapp.processEvents()
    window.settings.set_image_path(image_path)
    window.settings.width_spin.setValue(16)
    window.settings.set_brand("mard")
    window.settings.mode_radios["mean"].setChecked(True)

    # Modified advanced slider → a real EdgeConfig reaches convert().
    window.settings.advanced_sliders["smoothness"].setValue(140)
    window._convert()  # must not raise
    assert window._last_result is not None
    assert window._last_result.width == 16
    assert not window.preview.image().isNull()

    # All defaults → edge_config=None → engine default path, still fine.
    window.settings.advanced_sliders["smoothness"].setValue(115)
    window._convert()
    assert window._last_result is not None
    assert not window.preview.image().isNull()
    assert "转换完成" in window.status_label.text()
    window.close()
