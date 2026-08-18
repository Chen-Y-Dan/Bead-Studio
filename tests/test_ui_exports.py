"""W3a UI tests: PDF/CSV exports + batch-folder mode (all offscreen).

Covers the export wiring in app.py: single-image export after convert, the
batch loop with per-stem subfolders, and batch resilience against corrupt
images. Qt runs on the offscreen platform (env var set before any PySide6
import), matching tests/test_smoke.py.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PIL import Image  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

from beadstudio.app import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_image(path, color=(220, 30, 30), size=(64, 64)) -> str:
    array = np.full((size[1], size[0], 3), color, dtype=np.uint8)
    Image.fromarray(array).save(path)
    return str(path)


# ---------------------------------------------------------------------------
# Single-image export flow (PDF + CSV after convert)
# ---------------------------------------------------------------------------

def test_export_flow_pdf_and_csv(tmp_path, qapp):
    """Convert a red PNG with mard/mean/width-16, then export PDF + CSV into
    the chosen output dir; assert CLI-style names, non-empty files, and the
    CSV header row."""
    png = tmp_path / "red.png"
    image_path = _make_image(png)
    out_dir = tmp_path / "out"

    window = MainWindow()
    window.show()
    qapp.processEvents()

    window.settings.set_image_path(image_path)
    window.settings.set_brand("mard")  # series combo defaults to 全部
    window.settings.mode_radios["mean"].setChecked(True)
    window.settings.width_spin.setValue(16)
    window.settings.set_output_dir(str(out_dir))
    window.settings.export_pdf_check.setChecked(True)
    window.settings.export_csv_check.setChecked(True)

    window._convert()

    assert window._last_result is not None
    assert window._last_result.width == 16

    pdf = out_dir / "red_pattern.pdf"
    csv = out_dir / "red_shopping.csv"
    assert pdf.exists(), "PDF export missing (CLI name: <stem>_pattern.pdf)"
    assert csv.exists(), "CSV export missing (CLI name: <stem>_shopping.csv)"
    assert pdf.stat().st_size > 0
    assert csv.stat().st_size > 0

    text = csv.read_text(encoding="utf-8")
    assert text.splitlines()[0] == "brand,code,name,RGB,count"

    # status bar reports the saved paths
    status = window.status_label.text()
    assert "转换完成" in status
    assert "red_pattern.pdf" in status
    assert "red_shopping.csv" in status
    window.close()


def test_export_flow_respects_checkboxes(tmp_path, qapp):
    """No checkboxes → no export files are written (preview only)."""
    png = tmp_path / "plain.png"
    image_path = _make_image(png)
    out_dir = tmp_path / "out"

    window = MainWindow()
    window.settings.set_image_path(image_path)
    window.settings.width_spin.setValue(16)
    window.settings.set_output_dir(str(out_dir))

    window._convert()

    assert not (out_dir / "plain_pattern.pdf").exists()
    assert not (out_dir / "plain_shopping.csv").exists()
    assert window._last_result is not None
    window.close()


def test_export_flow_png_single(tmp_path, qapp):
    """Single-image PNG export: export_png checked → <stem>_pattern.png."""
    png = tmp_path / "blue.png"
    image_path = _make_image(png, color=(20, 60, 220))
    out_dir = tmp_path / "out"

    window = MainWindow()
    window.settings.set_image_path(image_path)
    window.settings.width_spin.setValue(16)
    window.settings.set_output_dir(str(out_dir))
    window.settings.export_png_check.setChecked(True)

    window._convert()

    assert window._last_result is not None
    pattern = out_dir / "blue_pattern.png"
    assert pattern.exists(), "PNG export missing (CLI name: <stem>_pattern.png)"
    assert pattern.stat().st_size > 0
    # PDF/CSV unchecked → only the PNG is written
    assert not (out_dir / "blue_pattern.pdf").exists()
    assert not (out_dir / "blue_shopping.csv").exists()
    # status bar reports the saved path
    assert "blue_pattern.png" in window.status_label.text()
    window.close()


def test_export_failure_does_not_crash(tmp_path, qapp):
    """An uncreatable output dir surfaces a status-bar error, no exception."""
    png = tmp_path / "img.png"
    image_path = _make_image(png)
    # A regular file blocks any directory creation beneath it.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")

    window = MainWindow()
    window.settings.set_image_path(image_path)
    window.settings.width_spin.setValue(16)
    window.settings.set_output_dir(str(blocker / "sub"))
    window.settings.export_pdf_check.setChecked(True)

    # Must not raise even though the output dir cannot be created.
    window._convert()

    assert window._last_result is not None
    assert "导出失败" in window.status_label.text()
    window.close()


# ---------------------------------------------------------------------------
# Batch mode
# ---------------------------------------------------------------------------

def test_batch_flow_three_images(tmp_path, qapp):
    """3 tiny images → 3 per-stem subfolders with pattern PNGs; progress hits
    100%; summary status reports 批量完成."""
    src = tmp_path / "src"
    src.mkdir()
    for name, color in (
        ("a.png", (255, 0, 0)),
        ("b.png", (0, 255, 0)),
        ("c.png", (0, 0, 255)),
    ):
        _make_image(src / name, color=color, size=(32, 32))
    out = tmp_path / "out"

    window = MainWindow()
    window.settings.width_spin.setValue(16)

    summary = window.run_batch(str(src), output_dir=str(out))

    assert summary == {"ok": 3, "failed": 0, "total": 3, "cancelled": False}
    for stem in ("a", "b", "c"):
        pattern = out / stem / f"{stem}_pattern.png"
        assert pattern.exists(), f"missing per-stem output: {pattern}"
        assert pattern.stat().st_size > 0

    # progress dialog reached 100% (value == maximum)
    dialog = window._batch_dialog
    assert dialog.maximum() == 3
    assert dialog.value() == dialog.maximum()

    assert "批量完成：3 张，0 张失败" in window.status_label.text()
    window.close()


def test_batch_flow_with_exports(tmp_path, qapp):
    """Batch with PDF/CSV checked: each stem folder also gets the exports."""
    src = tmp_path / "src"
    src.mkdir()
    _make_image(src / "one.png", color=(10, 200, 40), size=(32, 32))
    _make_image(src / "two.png", color=(200, 10, 200), size=(32, 32))
    out = tmp_path / "out"

    window = MainWindow()
    window.settings.width_spin.setValue(16)
    window.settings.export_pdf_check.setChecked(True)
    window.settings.export_csv_check.setChecked(True)

    summary = window.run_batch(str(src), output_dir=str(out))

    assert summary["ok"] == 2 and summary["failed"] == 0
    for stem in ("one", "two"):
        assert (out / stem / f"{stem}_pattern.png").exists()
        assert (out / stem / f"{stem}_pattern.pdf").exists()
        assert (out / stem / f"{stem}_shopping.csv").exists()
        csv_text = (out / stem / f"{stem}_shopping.csv").read_text(encoding="utf-8")
        assert csv_text.splitlines()[0] == "brand,code,name,RGB,count"
    window.close()


def test_batch_partial_failure(tmp_path, qapp):
    """2 good + 1 corrupt (PNG that is really text): batch completes, reports
    1 failure, and the 2 good outputs exist."""
    src = tmp_path / "src"
    src.mkdir()
    _make_image(src / "good1.png", color=(255, 0, 0), size=(32, 32))
    _make_image(src / "good2.png", color=(0, 255, 0), size=(32, 32))
    (src / "corrupt.png").write_text("this is not an image", encoding="utf-8")
    out = tmp_path / "out"

    window = MainWindow()
    window.settings.width_spin.setValue(16)

    summary = window.run_batch(str(src), output_dir=str(out))

    assert summary["ok"] == 2
    assert summary["failed"] == 1
    assert summary["total"] == 3
    assert (out / "good1" / "good1_pattern.png").exists()
    assert (out / "good2" / "good2_pattern.png").exists()
    assert not (out / "corrupt").exists()

    # summary status mentions the failure count
    assert "批量完成：2 张，1 张失败" in window.status_label.text()
    window.close()


def test_batch_empty_folder(tmp_path, qapp):
    """No supported images → status message, no crash."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "readme.txt").write_text("hi", encoding="utf-8")

    window = MainWindow()
    summary = window.run_batch(str(src), output_dir=str(tmp_path / "out"))

    assert summary == {"ok": 0, "failed": 0, "total": 0, "cancelled": False}
    assert "文件夹中没有支持的图片" in window.status_label.text()
    window.close()
