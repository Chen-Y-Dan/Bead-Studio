"""Smoke tests: headless (offscreen Qt) launch check + engine data sanity.

Must be runnable in CI/headless environments — Qt is forced to the
offscreen platform before any PySide6 import.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

from beadstudio.app import MainWindow  # noqa: E402
from beadstudio.core.palette import list_brands  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_core_palettes_available():
    """The copied engine must resolve all 21 brand palettes."""
    brands = list_brands()
    assert len(brands) == 21


def test_window_constructs_and_shows(qapp):
    """Main window constructs, shows and closes without crashing."""
    window = MainWindow()
    window.show()
    assert window.windowTitle() == "BeadStudio 豆趣工坊"
    assert window.centralWidget() is not None
    assert not window.windowIcon().isNull()
    qapp.processEvents()
    window.close()
