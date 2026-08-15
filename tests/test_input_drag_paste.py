"""Tests for the quick image-input paths: drag & drop and Ctrl+V paste.

Qt drag/drop cannot be synthesized reliably through a real event loop
offscreen, so the handlers are invoked directly with constructed
QDragEnterEvent / QDropEvent objects (which Qt allows) — deterministic and
matching the design note. IMPORTANT shiboken quirk: the QMimeData must keep a
named Python reference in scope while the handler runs, otherwise
``event.mimeData()`` re-wraps it as a bare ``QObject``.

The clipboard (QImage / file-URL mime) works on the offscreen platform, so
``_on_paste`` is exercised through the real ``QApplication.clipboard()``.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PIL import Image  # noqa: E402

from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
    QImage,
)
from PySide6.QtWidgets import QApplication  # noqa: E402

from beadstudio.app import MainWindow  # noqa: E402
from beadstudio.ui.i18n import tr  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_red_png(path) -> str:
    array = np.full((48, 48, 3), (200, 40, 40), dtype=np.uint8)
    Image.fromarray(array).save(path)
    return str(path)


def _mime_with_url(path: str) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(path)])
    return mime


def _drag_event(mime: QMimeData) -> QDragEnterEvent:
    # ``mime`` must stay referenced by the caller while the handler runs.
    return QDragEnterEvent(
        QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier
    )


def _drop_event(mime: QMimeData) -> QDropEvent:
    return QDropEvent(
        QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier
    )


# ---------------------------------------------------------------------------
# Drag & drop
# ---------------------------------------------------------------------------

def test_drag_enter_accepts_image(qapp, tmp_path):
    png = tmp_path / "drag.png"
    image_path = _make_red_png(png)

    window = MainWindow()
    window.show()
    qapp.processEvents()

    mime = _mime_with_url(image_path)  # keep alive: shiboken type quirk
    event = _drag_event(mime)
    window.dragEnterEvent(event)

    assert event.isAccepted()
    # visual affordance is on while the drag hovers the window
    assert window.settings.image_label.text() == tr("drop_accept", window._lang)
    assert window.settings.image_path() is None  # drag-enter never sets the path
    window.close()


def test_drag_hint_restored_on_leave(qapp):
    window = MainWindow()
    window.show()
    qapp.processEvents()

    window.dragLeaveEvent(QDragLeaveEvent())
    # label is back to the default no-image text
    assert window.settings.image_label.text() == tr("image_path_default", window._lang)
    window.close()


def test_drop_loads_image_without_converting(qapp, tmp_path):
    png = tmp_path / "drop.png"
    image_path = _make_red_png(png)

    window = MainWindow()
    window.show()
    qapp.processEvents()

    mime = _mime_with_url(image_path)
    event = _drop_event(mime)
    window.dropEvent(event)

    assert event.isAccepted()
    assert Path(window.settings.image_path()) == Path(image_path)
    # Dropping only LOADS the image — no auto-convert; the pattern appears
    # only after the user presses Generate Preview.
    assert window._last_result is None
    assert "转换完成" not in window.status_label.text()
    assert window.settings.image_label.text() == Path(image_path).name

    # Generate Preview then converts the dropped image.
    window._on_generate_preview_clicked()
    assert window._last_result is not None
    assert "转换完成" in window.status_label.text()
    window.close()


def test_drag_enter_rejects_non_image(qapp, tmp_path):
    txt = tmp_path / "notes.txt"
    txt.write_text("not an image", encoding="utf-8")

    window = MainWindow()
    window.show()
    qapp.processEvents()

    mime = _mime_with_url(str(txt))
    event = _drag_event(mime)
    window.dragEnterEvent(event)

    assert not event.isAccepted()
    assert window.settings.image_path() is None
    window.close()


def test_drop_rejects_non_image_path_unchanged(qapp, tmp_path):
    png = tmp_path / "kept.png"
    first_path = _make_red_png(png)
    txt = tmp_path / "notes.txt"
    txt.write_text("not an image", encoding="utf-8")

    window = MainWindow()
    window.show()
    qapp.processEvents()
    window.settings.set_image_path(first_path)

    mime = _mime_with_url(str(txt))
    event = _drop_event(mime)
    window.dropEvent(event)

    assert not event.isAccepted()
    assert window.settings.image_path() == first_path  # unchanged
    assert window._last_result is None  # no conversion attempted
    window.close()


# ---------------------------------------------------------------------------
# Paste (Ctrl+V)
# ---------------------------------------------------------------------------

def test_paste_image_sets_path(qapp):
    window = MainWindow()
    window.show()
    qapp.processEvents()

    image = QImage(8, 8, QImage.Format.Format_RGB32)
    image.fill(QColor(200, 40, 40))
    QApplication.clipboard().setImage(image)
    qapp.processEvents()

    window._on_paste()

    path = window.settings.image_path()
    assert path is not None
    assert Path(path).exists()
    assert Path(path).name == "beadstudio_paste.png"
    # clipboard QImage → temp PNG → loaded only, no auto-convert
    assert window._last_result is None
    assert "转换完成" not in window.status_label.text()
    window.close()


def test_paste_file_url_sets_path(qapp, tmp_path):
    png = tmp_path / "copied.png"
    image_path = _make_red_png(png)

    window = MainWindow()
    window.show()
    qapp.processEvents()

    QApplication.clipboard().setMimeData(_mime_with_url(image_path))
    qapp.processEvents()

    window._on_paste()

    # copied image FILE → used directly, no temp file involved
    assert Path(window.settings.image_path()) == Path(image_path)
    # pasting only loads — no auto-convert
    assert window._last_result is None
    window.close()


def test_paste_no_image_shows_message(qapp):
    window = MainWindow()
    window.show()
    qapp.processEvents()

    QApplication.clipboard().clear()
    qapp.processEvents()

    window._on_paste()

    assert window.settings.image_path() is None
    assert window.status_label.text() == tr("no_clipboard_image", window._lang)
    window.close()
