"""Settings panel: image picker + conversion parameter controls.

Emits :attr:`params_changed` (with a params dict) on every control change,
:attr:`generate_preview_clicked` when the Generate Preview button is pressed,
and :attr:`batch_clicked` when the batch button is pressed. Conversion is an
explicit user action — parameter changes only report state via
``params_changed`` and never trigger a conversion by themselves. The panel
also captures the export output directory (defaults to the source image's
folder, or the user's Pictures when no image is selected yet).

The series/max-colors visibility rule follows the engine: brands with letter
series (``get_series(brand)`` non-empty, e.g. mard) show 系列 and hide 颜色数;
flat brands (perler, …) show 颜色数 and hide 系列.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from beadstudio.core.models import EdgeConfig
from beadstudio.core.palette import get_series, list_brands
from beadstudio.ui.i18n import get_language, tr

#: Per-cell color extraction modes (radio order).
_CELL_MODES = ("dominant", "mean")

#: Cell-size zoom options for the preview (px per bead cell).
_ZOOM_SIZES = (4, 6, 8, 10, 12, 16, 20, 24, 28, 32)

#: Advanced (EdgeConfig) slider configs, in display order: key → (min, max,
#: default-on-slider, value formatter). The slider scale differs per field:
#: ``mean_edge_deltae_threshold``/``stroke_min_deltae`` are floats in the core
#: but integers here, and ``stroke_min_fraction`` is a fraction in the core but
#: a percentage on the slider. Defaults mirror ``EdgeConfig()`` so the sliders
#: start at the engine's defaults and ``params()["edge_config"]`` is ``None``
#: until the user actually changes something.
_ADVANCED_CONFIG = {
    "smoothness": (60, 180, 115, str),
    "edge_sensitivity": (5, 30, 15, lambda v: f"{v:.1f}"),
    "thin_line": (5, 30, 12, lambda v: f"{v}%"),
    "min_line_len": (3, 10, 5, str),
    "high_boundary": (120, 255, 180, str),
    "line_color_diff": (20, 50, 35, str),
}
_ADVANCED_KEYS = tuple(_ADVANCED_CONFIG)


def _advanced_defaults() -> dict[str, int]:
    """Slider-scale defaults derived from the engine's ``EdgeConfig()``.

    Deriving from the core (instead of hardcoding) keeps the GUI in sync if the
    engine's defaults ever change.
    """
    ec = EdgeConfig()
    return {
        "smoothness": ec.mean_edge_range_low,
        "edge_sensitivity": int(ec.mean_edge_deltae_threshold),
        "thin_line": int(round(ec.stroke_min_fraction * 100)),
        "min_line_len": ec.stroke_min_length,
        "high_boundary": ec.mean_edge_range_high,
        "line_color_diff": int(ec.stroke_min_deltae),
    }


def _rembg_available() -> bool:
    """True when the optional rembg dependency is importable.

    rembg is an optional extra (pip install rembg onnxruntime) — the GUI must
    work without it, so availability is probed per use rather than at import.
    """
    try:
        import rembg  # noqa: F401
        return True
    except ImportError:
        return False


class SettingsPanel(QWidget):
    """Parameter panel for a single-image conversion."""

    #: Emitted with a params dict whenever any control changes.
    params_changed = Signal(object)
    #: Emitted when the Generate Preview button is pressed.
    generate_preview_clicked = Signal()
    #: Emitted when the batch-folder button is pressed.
    batch_clicked = Signal()

    def __init__(self, parent: Optional[QWidget] = None, lang: Optional[str] = None) -> None:
        super().__init__(parent)
        self._lang = lang or get_language()
        self._image_path: Optional[str] = None
        #: User-chosen export dir (None = auto: source-image folder / Pictures).
        self._output_dir: Optional[str] = None

        # -- image picker ---------------------------------------------------
        file_box = QGroupBox(self)
        file_layout = QVBoxLayout(file_box)
        image_row = QHBoxLayout()
        self.choose_button = QPushButton(tr("choose_image", self._lang), file_box)
        self.choose_button.clicked.connect(self._on_choose_clicked)
        self.image_label = QLabel(tr("image_path_default", self._lang), file_box)
        self.image_label.setWordWrap(True)
        self.image_label.setToolTip(tr("image_path_default", self._lang))
        image_row.addWidget(self.choose_button)
        image_row.addWidget(self.image_label, 1)
        file_layout.addLayout(image_row)

        # quick-input hint: drag an image onto the window or press Ctrl+V
        # (reuses the subtle #hintLabel secondary-text style from theme QSS)
        self.input_hint = QLabel(tr("image_input_hint", self._lang), file_box)
        self.input_hint.setObjectName("hintLabel")  # styled via theme QSS
        self.input_hint.setWordWrap(True)
        file_layout.addWidget(self.input_hint)

        # output directory (button + path label)
        output_row = QHBoxLayout()
        self._output_dir_label = QLabel(tr("output_dir", self._lang), file_box)
        output_row.addWidget(self._output_dir_label)
        self.output_dir_button = QPushButton(
            tr("choose_output_dir", self._lang), file_box
        )
        self.output_dir_button.clicked.connect(self._on_choose_output_clicked)
        self.output_dir_label = QLabel(self._default_output_dir(), file_box)
        self.output_dir_label.setWordWrap(True)
        self.output_dir_label.setToolTip(self._default_output_dir())
        output_row.addWidget(self.output_dir_button)
        output_row.addWidget(self.output_dir_label, 1)
        file_layout.addLayout(output_row)

        # -- parameters -----------------------------------------------------
        param_box = QGroupBox(self)
        param_layout = QVBoxLayout(param_box)

        # brand
        brand_row = QHBoxLayout()
        self._brand_label = QLabel(tr("brand", self._lang), param_box)
        brand_row.addWidget(self._brand_label)
        self.brand_combo = QComboBox(param_box)
        for name in list_brands():
            self.brand_combo.addItem(name)
        brand_row.addWidget(self.brand_combo, 1)
        param_layout.addLayout(brand_row)

        # width / height
        size_row = QHBoxLayout()
        self._width_label = QLabel(tr("width", self._lang), param_box)
        size_row.addWidget(self._width_label)
        self.width_spin = QSpinBox(param_box)
        self.width_spin.setRange(1, 300)
        self.width_spin.setValue(100)
        size_row.addWidget(self.width_spin, 1)
        self._height_label = QLabel(tr("height", self._lang), param_box)
        size_row.addWidget(self._height_label)
        self.height_spin = QSpinBox(param_box)
        self.height_spin.setRange(0, 300)
        self.height_spin.setValue(0)
        self.height_spin.setToolTip(tr("height", self._lang))
        size_row.addWidget(self.height_spin, 1)
        param_layout.addLayout(size_row)

        # series (shown only for series-structured brands)
        self.series_box = QWidget(param_box)
        series_row = QHBoxLayout(self.series_box)
        series_row.setContentsMargins(0, 0, 0, 0)
        self._series_label = QLabel(tr("series", self._lang), self.series_box)
        series_row.addWidget(self._series_label)
        self.series_combo = QComboBox(self.series_box)
        self.series_combo.addItem(tr("series_all", self._lang))
        series_row.addWidget(self.series_combo, 1)
        param_layout.addWidget(self.series_box)

        # max colors (shown only for flat brands)
        self.max_colors_box = QWidget(param_box)
        colors_row = QHBoxLayout(self.max_colors_box)
        colors_row.setContentsMargins(0, 0, 0, 0)
        self._colors_label = QLabel(tr("max_colors", self._lang), self.max_colors_box)
        colors_row.addWidget(self._colors_label)
        self.max_colors_spin = QSpinBox(self.max_colors_box)
        self.max_colors_spin.setRange(0, 100)
        self.max_colors_spin.setValue(30)
        self.max_colors_spin.setToolTip(tr("max_colors", self._lang))
        colors_row.addWidget(self.max_colors_spin, 1)
        param_layout.addWidget(self.max_colors_box)

        # cell mode (dominant / mean), default mean
        mode_row = QHBoxLayout()
        self._cell_mode_label = QLabel(tr("cell_mode", self._lang), param_box)
        mode_row.addWidget(self._cell_mode_label)
        self.mode_radios: Dict[str, QRadioButton] = {}
        for mode in _CELL_MODES:
            radio = QRadioButton(tr(f"cell_mode_{mode}", self._lang), param_box)
            self.mode_radios[mode] = radio
            mode_row.addWidget(radio)
        self.mode_radios["mean"].setChecked(True)
        mode_row.addStretch(1)
        param_layout.addLayout(mode_row)

        # dither (auto-disabled in mean mode)
        dither_row = QHBoxLayout()
        self.dither_check = QCheckBox(tr("dither", self._lang), param_box)
        self.dither_hint = QLabel(tr("dither_mean_hint", self._lang), param_box)
        self.dither_hint.setObjectName("hintLabel")  # styled via theme QSS
        dither_row.addWidget(self.dither_check)
        dither_row.addWidget(self.dither_hint)
        dither_row.addStretch(1)
        param_layout.addLayout(dither_row)

        # background removal (optional dependency: rembg)
        bg_remove_row = QHBoxLayout()
        self.bg_remove_check = QCheckBox(tr("bg_remove", self._lang), param_box)
        self.bg_remove_hint = QLabel(tr("bg_remove_hint", self._lang), param_box)
        self.bg_remove_hint.setObjectName("hintLabel")  # styled via theme QSS
        self.bg_remove_hint.setWordWrap(True)
        bg_remove_row.addWidget(self.bg_remove_check)
        bg_remove_row.addWidget(self.bg_remove_hint, 1)
        param_layout.addLayout(bg_remove_row)
        if not _rembg_available():
            # Pre-disabled at construction so the missing dependency is
            # visible up front (the toggle handler re-applies this too).
            self.bg_remove_check.setEnabled(False)
            self.bg_remove_check.setToolTip(tr("bg_remove_disabled", self._lang))
            self.bg_remove_hint.setVisible(True)

        # export format (W2: parameter capture only; W3 wires real export)
        export_row = QHBoxLayout()
        self._export_label = QLabel(tr("export_format", self._lang), param_box)
        export_row.addWidget(self._export_label)
        self.export_pdf_check = QCheckBox(tr("export_pdf", self._lang), param_box)
        self.export_png_check = QCheckBox(tr("export_png", self._lang), param_box)
        self.export_csv_check = QCheckBox(tr("export_csv", self._lang), param_box)
        export_row.addWidget(self.export_pdf_check)
        export_row.addWidget(self.export_png_check)
        export_row.addWidget(self.export_csv_check)
        export_row.addStretch(1)
        param_layout.addLayout(export_row)

        # advanced parameters (W6: EdgeConfig tunables — collapsible)
        # The checkable title is the Qt collapse toggle: checked = expanded,
        # unchecked = collapsed (the contents are hidden, not just disabled).
        self.advanced_group = QGroupBox(tr("advanced_params", self._lang), param_box)
        self.advanced_group.setCheckable(True)
        self.advanced_group.setChecked(False)  # collapsed by default
        advanced_shell = QVBoxLayout(self.advanced_group)
        self.advanced_contents = QWidget(self.advanced_group)
        advanced_shell.addWidget(self.advanced_contents)
        advanced_layout = QVBoxLayout(self.advanced_contents)
        advanced_layout.setContentsMargins(0, 0, 0, 0)

        self.advanced_hint = QLabel(
            tr("advanced_params_hint", self._lang), self.advanced_contents
        )
        self.advanced_hint.setObjectName("hintLabel")  # styled via theme QSS
        self.advanced_hint.setWordWrap(True)
        advanced_layout.addWidget(self.advanced_hint)

        self.advanced_name_labels: dict[str, QLabel] = {}
        self.advanced_sliders: dict[str, QSlider] = {}
        self.advanced_value_labels: dict[str, QLabel] = {}
        defaults = _advanced_defaults()
        for key in _ADVANCED_KEYS:
            low, high, _default, fmt = _ADVANCED_CONFIG[key]
            row = QHBoxLayout()
            name_label = QLabel(tr(key, self._lang), self.advanced_contents)
            row.addWidget(name_label)
            slider = QSlider(Qt.Horizontal, self.advanced_contents)
            slider.setRange(low, high)
            slider.setValue(defaults[key])
            slider.valueChanged.connect(self._on_advanced_slider_changed)
            row.addWidget(slider, 1)
            value_label = QLabel(self.advanced_contents)
            value_label.setMinimumWidth(40)
            value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row.addWidget(value_label)
            advanced_layout.addLayout(row)
            self.advanced_name_labels[key] = name_label
            self.advanced_sliders[key] = slider
            self.advanced_value_labels[key] = value_label

        self.reset_defaults_button = QPushButton(
            tr("reset_defaults", self._lang), self.advanced_contents
        )
        self.reset_defaults_button.clicked.connect(self._reset_advanced_defaults)
        advanced_layout.addWidget(self.reset_defaults_button)

        self._update_advanced_value_labels()
        self.advanced_contents.setVisible(False)  # collapsed by default
        # Expand/collapse toggles the contents' visibility (Qt's checkable
        # group box only disables children; hiding them is the collapse part).
        self.advanced_group.toggled.connect(self.advanced_contents.setVisible)
        param_layout.addWidget(self.advanced_group)

        # -- actions --------------------------------------------------------
        action_layout = QHBoxLayout()
        self.generate_preview_button = QPushButton(tr("generate_preview", self._lang), self)
        self.generate_preview_button.setObjectName("primaryButton")  # accent CTA via theme QSS
        self.generate_preview_button.clicked.connect(self.generate_preview_clicked)
        self.batch_button = QPushButton(tr("batch", self._lang), self)
        self.batch_button.clicked.connect(self.batch_clicked)
        action_layout.addWidget(self.generate_preview_button)
        action_layout.addWidget(self.batch_button)

        root = QVBoxLayout(self)
        root.addWidget(file_box)
        root.addWidget(param_box)
        root.addLayout(action_layout)
        root.addStretch(1)

        # -- wiring ---------------------------------------------------------
        self.brand_combo.currentTextChanged.connect(self._on_brand_changed)
        self.series_combo.currentTextChanged.connect(self._emit_params)
        for mode in _CELL_MODES:
            self.mode_radios[mode].toggled.connect(self._on_mode_toggled)
        self.width_spin.valueChanged.connect(self._emit_params)
        self.height_spin.valueChanged.connect(self._emit_params)
        self.max_colors_spin.valueChanged.connect(self._emit_params)
        self.dither_check.toggled.connect(self._emit_params)
        self.bg_remove_check.toggled.connect(self._on_bg_remove_toggled)
        self.export_pdf_check.toggled.connect(self._emit_params)
        self.export_png_check.toggled.connect(self._emit_params)
        self.export_csv_check.toggled.connect(self._emit_params)

        # Initial brand-dependent visibility (keeps combo order authoritative
        # even before any user interaction).
        self._on_brand_changed(self.brand_combo.currentText())

    # ------------------------------------------------------------------ API

    def set_image_path(self, path: str) -> None:
        """Set the selected source image (also used by the picker dialog)."""
        self._image_path = path or None
        self._apply_image_label()
        self._refresh_output_dir_label()
        self._emit_params()

    def set_image_hint_active(self, active: bool) -> None:
        """Swap the image label to a transient drag-over hint (or restore it).

        The window-level drag & drop uses this as the visual affordance: on
        drag-enter the label reads "release to load", and on drag-leave/drop
        it is restored to the filename / default text. Never touches
        ``_image_path`` and never emits ``params_changed``.
        """
        if active:
            self.image_label.setText(tr("drop_accept", self._lang))
            self.image_label.setToolTip(tr("drop_hint", self._lang))
        else:
            self._apply_image_label()

    def _apply_image_label(self) -> None:
        """Render the image label from ``_image_path`` (shared by all paths)."""
        if self._image_path:
            self.image_label.setText(Path(self._image_path).name)
            self.image_label.setToolTip(self._image_path)
        else:
            self.image_label.setText(tr("image_path_default", self._lang))
            self.image_label.setToolTip("")

    def image_path(self) -> Optional[str]:
        """Currently selected source image path (or None)."""
        return self._image_path

    def _default_output_dir(self) -> str:
        """Auto output dir: the source image's folder, else user Pictures."""
        if self._image_path:
            return str(Path(self._image_path).parent)
        return str(Path.home() / "Pictures")

    def output_dir(self) -> str:
        """Effective export directory (user override or auto default)."""
        return self._output_dir or self._default_output_dir()

    def set_output_dir(self, path: str) -> None:
        """Override the export directory (used by the picker dialog / tests)."""
        self._output_dir = path or None
        self._refresh_output_dir_label()
        self._emit_params()

    def _refresh_output_dir_label(self) -> None:
        text = self.output_dir()
        self.output_dir_label.setText(text)
        self.output_dir_label.setToolTip(text)

    def set_brand(self, brand: str) -> None:
        """Switch the brand combo (repopulates series, updates visibility)."""
        self.brand_combo.setCurrentText(brand)

    def retranslate(self, lang: str) -> None:
        """Re-apply every user-visible text for ``lang`` without touching values.

        Called by the app's language switcher: spins keep their numbers,
        combos keep their selection and checkboxes keep their checked state.
        ``self._lang`` is updated first so ``params()`` keeps comparing the
        series combo against the translated "全部 / All" item correctly.
        """
        self._lang = lang

        # image picker
        self.choose_button.setText(tr("choose_image", lang))
        # Filename / path are value text, not translations.
        self._apply_image_label()
        self.input_hint.setText(tr("image_input_hint", lang))
        self._output_dir_label.setText(tr("output_dir", lang))
        self.output_dir_button.setText(tr("choose_output_dir", lang))
        # self.output_dir_label shows the actual path — value text, untouched.

        # parameters
        self._brand_label.setText(tr("brand", lang))
        self._width_label.setText(tr("width", lang))
        self._height_label.setText(tr("height", lang))
        self.height_spin.setToolTip(tr("height", lang))
        self._series_label.setText(tr("series", lang))
        self._colors_label.setText(tr("max_colors", lang))
        self.max_colors_spin.setToolTip(tr("max_colors", lang))

        # cell mode (dominant / mean)
        self._cell_mode_label.setText(tr("cell_mode", lang))
        for mode in _CELL_MODES:
            self.mode_radios[mode].setText(tr(f"cell_mode_{mode}", lang))

        # dither + hint (re-apply the mean-mode visibility rule)
        self.dither_check.setText(tr("dither", lang))
        self.dither_hint.setText(tr("dither_mean_hint", lang))
        mean_active = self.mode_radios["mean"].isChecked()
        self.dither_check.setEnabled(not mean_active)
        self.dither_hint.setVisible(mean_active)

        # background removal (tooltip only when the optional dep is missing)
        self.bg_remove_check.setText(tr("bg_remove", lang))
        self.bg_remove_hint.setText(tr("bg_remove_hint", lang))
        if not self.bg_remove_check.isEnabled():
            self.bg_remove_check.setToolTip(tr("bg_remove_disabled", lang))

        # export format
        self._export_label.setText(tr("export_format", lang))
        self.export_pdf_check.setText(tr("export_pdf", lang))
        self.export_png_check.setText(tr("export_png", lang))
        self.export_csv_check.setText(tr("export_csv", lang))

        # advanced parameters (slider values are numbers — untouched)
        self.advanced_group.setTitle(tr("advanced_params", lang))
        self.advanced_hint.setText(tr("advanced_params_hint", lang))
        for key in _ADVANCED_KEYS:
            self.advanced_name_labels[key].setText(tr(key, lang))
        self.reset_defaults_button.setText(tr("reset_defaults", lang))

        # actions
        self.generate_preview_button.setText(tr("generate_preview", lang))
        self.batch_button.setText(tr("batch", lang))

        # series combo: translate only the "全部 / All" first item; the
        # brand's series prefixes are language-independent. setItemText does
        # not emit selection signals, but guard anyway.
        if self.series_combo.count() > 0:
            self.series_combo.blockSignals(True)
            self.series_combo.setItemText(0, tr("series_all", lang))
            self.series_combo.blockSignals(False)

    def params(self) -> dict[str, Any]:
        """Snapshot of the current parameter state (dict emitted on changes).

        Semantics mirror the engine's ``convert()``: ``height=0`` means
        auto-aspect (None), ``max_colors=0`` means unlimited (None),
        ``series_range`` is None for flat brands and for series "全部",
        ``edge_config`` is None when all advanced sliders sit at the
        ``EdgeConfig()`` defaults (the engine then uses its own default).
        """
        brand = self.brand_combo.currentText()
        series_active = bool(get_series(brand))
        return {
            "image_path": self._image_path,
            "brand": brand,
            "width": self.width_spin.value(),
            "height": self.height_spin.value() or None,
            "series_range": (
                None
                if not series_active
                or self.series_combo.currentText() == tr("series_all", self._lang)
                else self.series_combo.currentText()
            ),
            "max_colors": (
                None
                if series_active or self.max_colors_spin.value() == 0
                else self.max_colors_spin.value()
            ),
            "cell_mode": next(
                mode for mode in _CELL_MODES if self.mode_radios[mode].isChecked()
            ),
            "dither": self.dither_check.isChecked(),
            "bg_remove": self.bg_remove_check.isChecked(),
            "export_pdf": self.export_pdf_check.isChecked(),
            "export_png": self.export_png_check.isChecked(),
            "export_csv": self.export_csv_check.isChecked(),
            "edge_config": self._edge_config(),
            "output_dir": self.output_dir(),
        }

    # ------------------------------------------------------------ internals

    def _on_choose_clicked(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self, tr("choose_image", self._lang), "", tr("img_filter", self._lang)
        )
        if path:
            self.set_image_path(path)

    def _on_choose_output_clicked(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self,
            tr("choose_output_dir", self._lang),
            self._default_output_dir(),
        )
        if chosen:
            self.set_output_dir(chosen)

    def _on_brand_changed(self, brand: str) -> None:
        series = get_series(brand)
        self.series_active = bool(series)
        self.colors_active = not series
        self.series_box.setVisible(self.series_active)
        self.max_colors_box.setVisible(self.colors_active)
        if series:
            self.series_combo.blockSignals(True)
            self.series_combo.clear()
            self.series_combo.addItem(tr("series_all", self._lang))
            for prefix in series:
                self.series_combo.addItem(prefix)
            self.series_combo.setCurrentIndex(0)
            self.series_combo.blockSignals(False)
        self._emit_params()

    def _on_mode_toggled(self, checked: bool) -> None:
        # The radio pair emits two toggles per click; only react to the one
        # that just turned ON so dither handling runs once.
        if not checked:
            return
        sender = self.sender()
        mean_active = sender is self.mode_radios["mean"]
        self.dither_check.setEnabled(not mean_active)
        self.dither_hint.setVisible(mean_active)
        if mean_active and self.dither_check.isChecked():
            self.dither_check.setChecked(False)
        self._emit_params()

    def _on_bg_remove_toggled(self, checked: bool) -> None:
        # Optional-dependency guard: enabling bg removal requires rembg to be
        # importable. If it is missing, snap the checkbox back, disable it and
        # surface the bilingual install hint — never crash.
        if checked and not _rembg_available():
            self.bg_remove_check.blockSignals(True)
            self.bg_remove_check.setChecked(False)
            self.bg_remove_check.blockSignals(False)
            self.bg_remove_check.setEnabled(False)
            self.bg_remove_check.setToolTip(tr("bg_remove_disabled", self._lang))
            self.bg_remove_hint.setVisible(True)
        elif checked:
            self.bg_remove_hint.setVisible(False)
        self._emit_params()

    def _emit_params(self, *_args) -> None:
        self.params_changed.emit(self.params())

    # ------------------------------------------------------ advanced params

    def _edge_config(self) -> Optional[EdgeConfig]:
        """EdgeConfig from the advanced sliders, or ``None`` when all defaults.

        ``None`` preserves the pre-W6 behavior exactly — the engine falls back
        to ``EdgeConfig()`` — so a default panel emits the same params dict as
        before. When any slider differs, an ``EdgeConfig`` is built that always
        satisfies the core's ``__post_init__`` validation: the LOW < HIGH pair
        is enforced by the slider linkage and re-clamped here as a
        belt-and-braces guarantee.
        """
        values = {key: self.advanced_sliders[key].value() for key in _ADVANCED_KEYS}
        defaults = _advanced_defaults()
        if all(values[key] == defaults[key] for key in _ADVANCED_KEYS):
            return None
        low = values["smoothness"]
        high = values["high_boundary"]
        if low >= high:
            high = min(low + 1, self.advanced_sliders["high_boundary"].maximum())
        return EdgeConfig(
            mean_edge_range_low=low,
            mean_edge_range_high=high,
            mean_edge_deltae_threshold=float(values["edge_sensitivity"]),
            stroke_min_fraction=values["thin_line"] / 100.0,
            stroke_min_length=values["min_line_len"],
            stroke_min_deltae=float(values["line_color_diff"]),
        )

    def _on_advanced_slider_changed(self, *_args) -> None:
        # LOW < HIGH linkage: the GUI must never hand the core an invalid
        # EdgeConfig (its __post_init__ would raise). When the smoothness
        # (low) slider catches up to / passes the high-boundary slider, the
        # high one snaps to low + 1. smoothness caps at 180 so low + 1 always
        # fits the high slider's 120-255 range.
        low = self.advanced_sliders["smoothness"].value()
        high_slider = self.advanced_sliders["high_boundary"]
        if low >= high_slider.value():
            high_slider.blockSignals(True)
            high_slider.setValue(min(low + 1, high_slider.maximum()))
            high_slider.blockSignals(False)
        self._update_advanced_value_labels()
        self._emit_params()

    def _reset_advanced_defaults(self) -> None:
        """Snap all six sliders back to the engine's ``EdgeConfig()`` defaults."""
        defaults = _advanced_defaults()
        for key, slider in self.advanced_sliders.items():
            slider.blockSignals(True)
            slider.setValue(defaults[key])
            slider.blockSignals(False)
        self._update_advanced_value_labels()
        self._emit_params()

    def _update_advanced_value_labels(self) -> None:
        for key, slider in self.advanced_sliders.items():
            _min, _max, _default, fmt = _ADVANCED_CONFIG[key]
            self.advanced_value_labels[key].setText(fmt(slider.value()))
