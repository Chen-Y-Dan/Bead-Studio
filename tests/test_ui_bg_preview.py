"""W3b UI tests: bg-remove optional-dependency hint + preview view toggles.

Qt runs on the offscreen platform (env var set before any PySide6 import),
matching tests/test_smoke.py. rembg is NOT installed in the beadGUI env — the
negative-case tests rely on that real absence (no monkeypatching), while the
positive case stubs the module via monkeypatch.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import importlib.util  # noqa: E402
import sys  # noqa: E402
import types  # noqa: E402

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PIL import Image  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

from beadstudio.app import MainWindow  # noqa: E402
from beadstudio.ui.preview import PreviewWidget  # noqa: E402
from beadstudio.ui.settings_panel import SettingsPanel  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_image(path, color=(220, 30, 30), size=(64, 64)) -> str:
    array = np.full((size[1], size[0], 3), color, dtype=np.uint8)
    Image.fromarray(array).save(path)
    return str(path)


def _red_pattern():
    """3x4 red pattern with code "R1" (and its legend)."""
    codes = [["R1"] * 4 for _ in range(3)]
    legend = [{"code": "R1", "rgb": (255, 0, 0), "count": 12}]
    grid = np.full((3, 4, 3), (255, 0, 0), dtype=np.uint8)
    return grid, codes, legend


# ---------------------------------------------------------------------------
# bg-remove checkbox (rembg optional dependency)
# ---------------------------------------------------------------------------

def test_rembg_really_absent():
    """Guard: the negative-case tests depend on rembg genuinely missing."""
    assert importlib.util.find_spec("rembg") is None


def test_bg_remove_checkbox_disabled_without_rembg(qapp):
    """rembg absent (real env): checkbox is disabled with the hint up front,
    and any check attempt snaps back — unchecked, disabled, hint visible."""
    panel = SettingsPanel()
    panel.show()
    qapp.processEvents()

    assert panel.params()["bg_remove"] is False
    assert not panel.bg_remove_check.isEnabled()
    assert panel.bg_remove_check.toolTip() != ""  # 已禁用（需安装 rembg）
    assert panel.bg_remove_hint.isVisible()

    # Programmatic check (what a click would do) → snapped back.
    panel.bg_remove_check.setChecked(True)
    qapp.processEvents()
    assert not panel.bg_remove_check.isChecked()
    assert not panel.bg_remove_check.isEnabled()
    assert panel.bg_remove_hint.isVisible()
    assert panel.params()["bg_remove"] is False
    panel.close()


def test_bg_remove_checkbox_stays_checked_with_rembg(qapp, monkeypatch):
    """rembg importable (simulated): checking it keeps it checked + enabled."""
    stub = types.ModuleType("rembg")
    stub.remove = lambda img: img
    monkeypatch.setitem(sys.modules, "rembg", stub)

    panel = SettingsPanel()
    panel.show()
    qapp.processEvents()

    assert panel.bg_remove_check.isEnabled()
    panel.bg_remove_check.setChecked(True)
    qapp.processEvents()
    assert panel.bg_remove_check.isChecked()
    assert panel.params()["bg_remove"] is True
    assert not panel.bg_remove_hint.isVisible()
    panel.close()


# ---------------------------------------------------------------------------
# _convert guard: bg_remove flag while rembg is absent
# ---------------------------------------------------------------------------

def test_convert_with_bg_remove_flag_without_rembg(tmp_path, qapp):
    """A stale/forced bg_remove flag with rembg absent must not crash —
    the conversion runs on the original image and the status notes the skip."""
    png = tmp_path / "red.png"
    image_path = _make_image(png)

    window = MainWindow()
    window.show()
    qapp.processEvents()
    window.settings.set_image_path(image_path)
    window.settings.width_spin.setValue(16)
    window.settings.set_brand("mard")

    # The checkbox itself refuses to stay checked without rembg, so force the
    # flag past the handler to exercise the _convert guard directly.
    window.settings.bg_remove_check.blockSignals(True)
    window.settings.bg_remove_check.setChecked(True)
    window.settings.bg_remove_check.blockSignals(False)

    window._convert()  # must not raise

    assert window._last_result is not None
    assert window._last_result["width"] == 16
    assert not window.preview.image().isNull()
    assert "转换完成" in window.status_label.text()
    assert "背景移除已跳过" in window.status_label.text()
    assert not (tmp_path / "red_nobg.png").exists()
    window.close()


# ---------------------------------------------------------------------------
# Preview view toggles
# ---------------------------------------------------------------------------

def test_cell_size_exposed(qapp):
    preview = PreviewWidget()
    assert preview.cell_size == 16  # default zoom
    preview.zoom_combo.setCurrentIndex(preview.zoom_combo.findData(4))
    assert preview.cell_size == 4


def test_grid_toggle_changes_render(qapp):
    preview = PreviewWidget()
    preview.zoom_combo.setCurrentIndex(preview.zoom_combo.findData(16))
    preview.set_pattern(*_red_pattern())
    with_grid = bytes(preview.image().bits())

    preview.set_show_grid(False)
    without_grid = bytes(preview.image().bits())
    assert without_grid != with_grid

    # Grid color (190,190,190) is present when on, absent when off. RGB32
    # pixels are BGRX in memory, but gray is order-independent.
    def has_grid_color(data: bytes) -> bool:
        arr = np.frombuffer(data, dtype=np.uint8).reshape(-1, 4)
        return bool(np.any(np.all(arr[:, :3] == (190, 190, 190), axis=1)))

    assert has_grid_color(with_grid)
    assert not has_grid_color(without_grid)
    preview.close()


def test_codes_toggle_changes_render_at_high_zoom(qapp):
    """Cell size 32 (>= 14): codes drawn on, not drawn off."""
    preview = PreviewWidget()
    preview.zoom_combo.setCurrentIndex(preview.zoom_combo.findData(32))
    preview.set_pattern(*_red_pattern())
    with_codes = bytes(preview.image().bits())

    preview.set_show_codes(False)
    assert bytes(preview.image().bits()) != with_codes
    preview.close()


def test_codes_toggle_noop_below_threshold(qapp):
    """Cell size 8 (< 14): codes are never drawn, so toggling changes nothing."""
    preview = PreviewWidget()
    preview.zoom_combo.setCurrentIndex(preview.zoom_combo.findData(8))
    preview.set_pattern(*_red_pattern())
    low_zoom = bytes(preview.image().bits())

    preview.set_show_codes(False)
    assert bytes(preview.image().bits()) == low_zoom
    preview.set_show_codes(True)
    assert bytes(preview.image().bits()) == low_zoom
    preview.close()
