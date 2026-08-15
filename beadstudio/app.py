"""Application bootstrap: QApplication + main window.

W2: full settings/preview UI on top of the core engine — a left-hand
settings panel (bilingual) and a scrollable preview on the right.
Conversion runs only when the user presses Generate Preview (an explicit
action — parameter changes never trigger a conversion, so there is no
debounced auto-preview and no lag while dragging controls). Offscreen-
platform safe (no hardcoded platform calls).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Optional

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from beadstudio.core import palette as palette_mod
from beadstudio.core.convert import convert
from beadstudio.core.export import export_pdf, export_png, shopping_list_csv
from beadstudio.ui.i18n import get_language, set_language, tr
from beadstudio.ui.preview import PreviewWidget, build_grid_rgb
from beadstudio.ui.settings_panel import SettingsPanel

_log = logging.getLogger("beadstudio.app")

_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
_ICON_PATH = _ASSETS_DIR / "app_icon_512.png"

#: Image extensions accepted in batch-folder mode (engine's supported list).
_SUPPORTED_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"}


def _preprocess_bg_remove(image_path: str) -> Optional[str]:
    """Remove the background with rembg; return the processed image path.

    Mirrors ``beadstudio/core/cli.py:_preprocess_bg_remove`` — same rembg call
    on the RGBA-converted source and the same ``<stem>_nobg.png`` output name —
    but is GUI-safe: it never ``sys.exit``s. Returns ``None`` when rembg is not
    importable or the removal fails, so the caller can fall back to converting
    the original image.
    """
    try:
        from rembg import remove as _rembg_remove
    except ImportError:
        return None
    try:
        from PIL import Image

        src = Path(image_path)
        img = Image.open(src).convert("RGBA")
        img_data = _rembg_remove(img)
        out_path = src.with_name(f"{src.stem}_nobg.png")
        img_data.save(out_path)
        return str(out_path)
    except Exception as exc:  # noqa: BLE001 — optional feature, never fatal
        _log.warning("Background removal failed, converting original: %s", exc)
        return None


class MainWindow(QMainWindow):
    """Main application window: settings panel + live pattern preview."""

    def __init__(self, lang: Optional[str] = None) -> None:
        super().__init__()
        self._lang = lang or get_language()
        self._last_result: Optional[dict[str, Any]] = None

        self.setWindowTitle(tr("window_title", self._lang))
        if _ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(_ICON_PATH)))

        # -- left: settings panel (fixed width) ------------------------------
        self.settings = SettingsPanel(self, lang=self._lang)
        self.settings.setFixedWidth(320)

        # -- right: view options + scrollable preview ------------------------
        self.preview = PreviewWidget(self, lang=self._lang)
        self.scroll = QScrollArea(self)
        self.scroll.setWidget(self.preview)
        # widgetResizable(True): the widget grows with the canvas (large
        # patterns scroll) and fills the viewport when the canvas is small
        # (e.g. the empty-state placeholder). With False the scroll area
        # would keep the widget at its initial size and clip big patterns.
        self.scroll.setWidgetResizable(True)

        view_options = QHBoxLayout()
        view_options.addStretch(1)
        self.show_grid_check = QCheckBox(tr("show_grid", self._lang), self)
        self.show_codes_check = QCheckBox(tr("show_codes", self._lang), self)
        self.show_grid_check.setChecked(True)
        self.show_codes_check.setChecked(True)
        view_options.addWidget(self.show_grid_check)
        view_options.addWidget(self.show_codes_check)
        # Manual language switcher (top-right). Both option names are shown
        # in either language by design; the index mirrors get_language().
        self.lang_combo = QComboBox(self)
        self.lang_combo.setObjectName("langCombo")
        self.lang_combo.addItem(tr("lang_zh", self._lang))
        self.lang_combo.addItem(tr("lang_en", self._lang))
        self.lang_combo.setCurrentIndex(0 if self._lang == "zh" else 1)
        view_options.addWidget(self.lang_combo)

        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addLayout(view_options)
        right_layout.addWidget(self.scroll, 1)

        central = QWidget(self)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.settings)
        layout.addLayout(right_layout, 1)
        self.setCentralWidget(central)

        # -- status bar ---------------------------------------------------------
        self.status_label = QLabel(tr("status_ready", self._lang), self)
        self.statusBar().addWidget(self.status_label)

        # -- wiring --------------------------------------------------------------
        self.settings.generate_preview_clicked.connect(
            self._on_generate_preview_clicked
        )
        self.settings.batch_clicked.connect(self._on_batch_clicked)
        # View toggles only re-render the existing pattern — never reconvert.
        self.show_grid_check.toggled.connect(self.preview.set_show_grid)
        self.show_codes_check.toggled.connect(self.preview.set_show_codes)
        self.lang_combo.currentIndexChanged.connect(self._on_language_changed)

    # ------------------------------------------------------------------ API

    def _on_generate_preview_clicked(self) -> None:
        # Conversion is explicit: it runs only when the user presses the
        # Generate Preview button — never on parameter changes.
        self._convert()

    def _on_language_changed(self, index: int) -> None:
        """Switch every visible string to the selected language in place.

        Combo order is fixed (index 0 = 中文, 1 = English). Retranslation is
        pushed into the settings panel, preview, view toggles and window
        title; user-entered values are preserved by ``retranslate``.
        """
        if index < 0:
            return
        lang = "zh" if index == 0 else "en"
        old_ready = tr("status_ready", self._lang)
        set_language(lang)
        self._lang = lang
        self.settings.retranslate(lang)
        self.preview.retranslate(lang)
        self.show_grid_check.setText(tr("show_grid", lang))
        self.show_codes_check.setText(tr("show_codes", lang))
        # Only downgrade a still-fresh "Ready" status to the new language —
        # never clobber a conversion result / error message.
        if self.status_label.text() == old_ready:
            self.status_label.setText(tr("status_ready", lang))
        self.setWindowTitle(tr("window_title", lang))

    def _convert(self) -> None:
        """Run the conversion with the current settings and render the result.

        Public-ish (also called directly by tests): safe to invoke without a
        running event loop — only Qt widgets are touched.
        """
        params = self.settings.params()
        image_path = params.get("image_path")
        if not image_path:
            self._set_status(tr("err_no_image", self._lang))
            return
        if not Path(image_path).exists():
            self._set_status(tr("err_image_missing", self._lang))
            return

        # Optional bg-removal preprocessing (mirrors the CLI's --bg-remove).
        # If rembg is missing or fails, fall back to the original image —
        # the step is skipped, never fatal.
        working_path = image_path
        bg_remove_skipped = False
        if params.get("bg_remove"):
            processed = _preprocess_bg_remove(image_path)
            if processed is None:
                bg_remove_skipped = True
                _log.warning(
                    "bg_remove requested but rembg unavailable or failed; "
                    "converting the original image"
                )
            else:
                working_path = processed

        self._set_status(tr("status_converting", self._lang))
        try:
            result = convert(
                working_path,
                width=params["width"],
                height=params["height"],
                brand=params["brand"],
                max_colors=params["max_colors"],
                cell_mode=params["cell_mode"],
                dither=params["dither"],
                series_range=params["series_range"],
            )
        except Exception as exc:  # noqa: BLE001 — surface any engine error
            message = f"{tr('status_error', self._lang)}：{exc}"
            self._set_status(message)
            if self.isVisible():
                QMessageBox.warning(self, tr("err_title", self._lang), message)
            return

        self._last_result = result
        grid = build_grid_rgb(result["codes"], result["legend"])
        self.preview.set_pattern(grid, result["codes"], result["legend"])

        parts = [
            tr("status_done", self._lang).format(
                n=result["colors_used"], w=result["width"], h=result["height"]
            )
        ]
        if bg_remove_skipped:
            parts.append(tr("bg_remove_skipped", self._lang))
        if params.get("export_pdf") or params.get("export_csv"):
            stem = Path(image_path).stem
            out_dir = Path(params.get("output_dir") or self.settings.output_dir())
            try:
                for saved, err in self._export_result(result, params, stem, out_dir):
                    if err is not None:
                        parts.append(tr("export_failed", self._lang).format(msg=err))
                    else:
                        parts.append(
                            tr("saved_path", self._lang).format(path=str(saved))
                        )
            except Exception as exc:  # noqa: BLE001 — out-dir creation, etc.
                parts.append(tr("export_failed", self._lang).format(msg=exc))
        self._set_status(" | ".join(parts))

    # ------------------------------------------------------------- exports

    def _export_result(
        self,
        result: dict[str, Any],
        params: dict[str, Any],
        stem: str,
        out_dir: Path,
        *,
        with_png: bool = False,
    ) -> list[tuple[Optional[Path], Optional[str]]]:
        """Write the export files for one converted image, CLI-compatible names.

        Naming matches ``beadstudio/core/cli.py`` exactly: ``<stem>_pattern.png``,
        ``<stem>_pattern.pdf``, ``<stem>_shopping.csv``. Every export is
        non-fatal: a failure returns ``(None, error)`` instead of raising, so a
        bad export can never crash the GUI. The palette is loaded once for the
        brand (``None`` on failure — engine falls back to the built-in map).

        Returns a list of ``(saved_path, None)`` / ``(None, error_msg)``.
        """
        try:
            palette = palette_mod.load_palette(params["brand"])
        except Exception:  # noqa: BLE001 — engine falls back to built-in map
            palette = None

        out_dir.mkdir(parents=True, exist_ok=True)
        reports: list[tuple[Optional[Path], Optional[str]]] = []

        if with_png:
            try:
                png_path = out_dir / f"{stem}_pattern.png"
                export_png(
                    result,
                    output_path=str(png_path),
                    palette=palette,
                    max_grid_dimension=1800,
                )
                reports.append((png_path, None))
            except Exception as exc:  # noqa: BLE001
                reports.append((None, f"PNG: {exc}"))

        if params.get("export_pdf"):
            try:
                pdf_path = out_dir / f"{stem}_pattern.pdf"
                export_pdf(
                    result,
                    str(pdf_path),
                    palette=palette,
                    estimate_rate=None,
                    estimate_shop_rate=None,
                    estimate_beginner=False,
                )
                reports.append((pdf_path, None))
            except Exception as exc:  # noqa: BLE001
                reports.append((None, f"PDF: {exc}"))

        if params.get("export_csv"):
            try:
                csv_path = out_dir / f"{stem}_shopping.csv"
                shopping_list_csv(
                    result,
                    palette=palette,
                    output_path=str(csv_path),
                    rate=None,
                    shop_rate=None,
                    beginner=False,
                )
                reports.append((csv_path, None))
            except Exception as exc:  # noqa: BLE001
                reports.append((None, f"CSV: {exc}"))

        return reports

    # ----------------------------------------------------------- batch mode

    def _on_batch_clicked(self) -> None:
        """Open the source-folder picker, then run the batch."""
        source = QFileDialog.getExistingDirectory(
            self, tr("choose_source_folder", self._lang), ""
        )
        if source:
            self.run_batch(source)

    def run_batch(
        self,
        source_dir: str,
        output_dir: Optional[str] = None,
        progress_dialog: Optional[QProgressDialog] = None,
    ) -> dict[str, int]:
        """Batch-convert every supported image under *source_dir*.

        Public (also called by tests — no file dialogs involved). Each image
        runs the same ``convert()`` with the current panel params and writes
        into ``output_dir/<image_stem>/`` (PNG pattern always; PDF/CSV when
        checked), mirroring the CLI's per-stem subfolder layout. A bad image
        never aborts the batch — it is counted as a failure. Returns the
        summary dict ``{"ok", "failed", "total", "cancelled"}``.
        """
        src = Path(source_dir)
        params = self.settings.params()
        images = sorted(
            p
            for p in src.iterdir()
            if p.is_file() and p.suffix.lower() in _SUPPORTED_EXTS
        )
        total = len(images)
        if total == 0:
            self._set_status(tr("batch_no_images", self._lang))
            return {"ok": 0, "failed": 0, "total": 0, "cancelled": False}

        out_base = Path(
            output_dir or params.get("output_dir") or self.settings.output_dir()
        )

        dialog = progress_dialog or QProgressDialog(
            tr("batch_progress_title", self._lang),
            tr("cancel", self._lang),
            0,
            total,
            self,
        )
        self._batch_dialog = dialog
        dialog.setMinimumDuration(0)
        dialog.setWindowTitle(tr("batch_progress_title", self._lang))
        dialog.setAutoReset(False)  # keep value == maximum after completion
        dialog.setAutoClose(False)

        ok = failed = 0
        cancelled = False
        for i, img in enumerate(images, 1):
            dialog.setValue(i - 1)
            dialog.setLabelText(
                tr("batch_progress_label", self._lang).format(
                    i=i, total=total, name=img.name
                )
            )
            if dialog.wasCanceled():
                cancelled = True
                break
            try:
                result = convert(
                    str(img),
                    width=params["width"],
                    height=params["height"],
                    brand=params["brand"],
                    max_colors=params["max_colors"],
                    cell_mode=params["cell_mode"],
                    dither=params["dither"],
                    series_range=params["series_range"],
                )
                stem = img.stem
                self._export_result(result, params, stem, out_base / stem, with_png=True)
                ok += 1
            except Exception:  # noqa: BLE001 — bad file must not abort the batch
                failed += 1
            dialog.setValue(i)
        dialog.setValue(total)

        if cancelled:
            self._set_status(tr("batch_cancelled", self._lang).format(done=ok))
        else:
            self._set_status(tr("batch_done", self._lang).format(ok=ok, fail=failed))
        return {"ok": ok, "failed": failed, "total": total, "cancelled": cancelled}

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)


def main() -> int:
    """Create the QApplication, show the main window, run the event loop."""
    app = QApplication(sys.argv)
    # Dark theme (Fusion + QSS). Optional-safe: a theme failure must never
    # prevent the app from starting with the default native look.
    try:
        from beadstudio.ui.theme import apply_theme

        apply_theme(app)
    except Exception:  # noqa: BLE001 — cosmetic layer, never fatal
        _log.warning("Dark theme failed to apply; using the default style",
                     exc_info=True)
    if _ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(_ICON_PATH)))
    window = MainWindow()
    window.resize(900, 640)
    window.show()
    return app.exec()
