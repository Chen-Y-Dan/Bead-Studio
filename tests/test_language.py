"""Language-switcher tests: manual en/zh switching + retranslate safety.

All Qt interaction runs on the offscreen platform (env var set before any
PySide6 import), matching tests/test_ui_i18n.py.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

from beadstudio.app import MainWindow  # noqa: E402
from beadstudio.ui.i18n import get_language, set_language, tr  # noqa: E402


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
# i18n keys for the switcher
# ---------------------------------------------------------------------------

def test_i18n_language_keys():
    assert tr("language", "zh") == "语言"
    assert tr("language", "en") == "Language"
    assert tr("lang_en", "en") == "English"
    assert tr("lang_zh", "zh") == "中文"


# ---------------------------------------------------------------------------
# Manual switch drives the whole interface
# ---------------------------------------------------------------------------

def test_manual_switch_changes_language(qapp):
    window = MainWindow()
    window.show()
    qapp.processEvents()

    combo = window.lang_combo
    assert combo.count() == 2
    assert combo.itemText(0) == "中文"
    assert combo.itemText(1) == "English"

    # Deterministic start: force Chinese regardless of the auto-detected locale.
    if window._lang != "zh":
        combo.setCurrentIndex(0)
        qapp.processEvents()
    assert window.windowTitle() == "BeadStudio 豆趣工坊"
    assert window.settings.generate_preview_button.text() == "生成预览"

    # → English
    combo.setCurrentIndex(1)
    qapp.processEvents()
    assert window.windowTitle() == "BeadStudio"
    assert window.settings.generate_preview_button.text() == "Generate Preview"
    assert window.settings.choose_button.text() == "Choose image…"

    # → back to Chinese
    combo.setCurrentIndex(0)
    qapp.processEvents()
    assert window.windowTitle() == "BeadStudio 豆趣工坊"
    assert window.settings.generate_preview_button.text() == "生成预览"
    window.close()


# ---------------------------------------------------------------------------
# Retranslate never touches user-entered values
# ---------------------------------------------------------------------------

def test_retranslate_preserves_values(qapp):
    window = MainWindow(lang="zh")
    window.show()
    qapp.processEvents()
    panel = window.settings

    panel.width_spin.setValue(77)
    panel.set_brand("perler")
    panel.export_pdf_check.setChecked(True)
    qapp.processEvents()

    panel.retranslate("en")
    assert panel.width_spin.value() == 77
    assert panel.brand_combo.currentText() == "perler"
    assert panel.export_pdf_check.isChecked() is True
    # text did switch to English while the values stayed put
    assert panel.generate_preview_button.text() == "Generate Preview"
    assert panel._width_label.text() == "Width (beads)"
    assert panel._brand_label.text() == "Brand"
    window.close()
