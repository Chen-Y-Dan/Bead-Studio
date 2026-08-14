"""Pattern preview: renders the convert() output grid as a zoomable QImage.

The engine's ``convert()`` does not return a grid RGB array, so the app builds
one from ``codes`` + ``legend`` (see :func:`build_grid_rgb`) and hands it to
:meth:`PreviewWidget.render`. Each cell is a filled square of the palette RGB;
thin grid lines separate cells (toggle via :meth:`PreviewWidget.set_show_grid`),
and the bead code is drawn inside cells when zoomed in enough
(``cell_size >= 14``, toggle via :meth:`PreviewWidget.set_show_codes`).
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPen
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from beadstudio.ui.i18n import get_language, tr

#: Available cell sizes in px (zoom levels).
ZOOM_SIZES = (4, 6, 8, 10, 12, 16, 20, 24, 28, 32)
_DEFAULT_CELL_SIZE = 16
#: Minimum cell size (px) for drawing the bead code text inside cells.
_CODE_TEXT_MIN_SIZE = 14
#: Grid line color (light gray).
_GRID_COLOR = QColor(190, 190, 190)
#: Empty (transparent) cell fill.
_EMPTY_COLOR = QColor(238, 238, 238)
_GRID_LUMINANCE_THRESHOLD = 140


def build_grid_rgb(
    codes: Sequence[Sequence[Optional[str]]],
    legend: Sequence[dict[str, Any]],
) -> np.ndarray:
    """Build a ``(H, W, 3)`` uint8 RGB grid from the engine's codes + legend.

    Empty cells (``None`` code) become white; every legend code maps to its
    palette RGB. Returns a zero-size array ``(0, 0, 3)`` when ``codes`` is
    empty so callers can always check ``size``.
    """
    if not codes or not codes[0]:
        return np.zeros((0, 0, 3), dtype=np.uint8)
    rgb_by_code = {entry["code"]: entry["rgb"] for entry in legend}
    height, width = len(codes), len(codes[0])
    grid = np.full((height, width, 3), 255, dtype=np.uint8)
    for y, row in enumerate(codes):
        for x, code in enumerate(row):
            rgb = rgb_by_code.get(code)
            if rgb is not None:
                grid[y, x] = rgb
    return grid


class _Canvas(QWidget):
    """Inner paint surface; draws the current QImage at natural size."""

    def __init__(self, owner: "PreviewWidget") -> None:
        super().__init__(owner)
        self._owner = owner

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt naming)
        image = self._owner.image()
        if image is None:
            return
        painter = QPainter(self)
        painter.drawImage(0, 0, image)


class PreviewWidget(QWidget):
    """Scrollable bead pattern preview with a cell-size zoom control."""

    def __init__(self, parent: Optional[QWidget] = None, lang: Optional[str] = None) -> None:
        super().__init__(parent)
        self._lang = lang or get_language()
        self._cell_size = _DEFAULT_CELL_SIZE
        #: Grid lines drawn by default; code text default-on (still zoom-gated).
        self._show_grid = True
        self._show_codes = True
        self.grid_rgb: Optional[np.ndarray] = None
        self.codes: Optional[List[List[Optional[str]]]] = None
        self.legend: Optional[List[dict[str, Any]]] = None
        self._image: Optional[QImage] = None

        header = QHBoxLayout()
        header.addWidget(QLabel(tr("cell_size", self._lang), self))
        self.zoom_combo = QComboBox(self)
        for size in ZOOM_SIZES:
            self.zoom_combo.addItem(f"{size} px", size)
        self.zoom_combo.setCurrentIndex(
            ZOOM_SIZES.index(_DEFAULT_CELL_SIZE)
        )
        self.zoom_combo.currentIndexChanged.connect(self._on_zoom_changed)
        header.addWidget(self.zoom_combo)
        header.addStretch(1)

        self._canvas = _Canvas(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(header)
        layout.addWidget(self._canvas, 1)

    # ------------------------------------------------------------------ API

    def image(self) -> Optional[QImage]:
        """Current rendered QImage (None until a pattern is set)."""
        return self._image

    @property
    def cell_size(self) -> int:
        """Current cell size in px (zoom level)."""
        return self._cell_size

    def set_show_grid(self, show: bool) -> None:
        """Toggle grid-line drawing and re-render the current pattern."""
        self._show_grid = bool(show)
        self.render()

    def set_show_codes(self, show: bool) -> None:
        """Toggle bead-code text inside cells and re-render.

        Codes still only appear when the cell is large enough (existing
        ``cell_size >= _CODE_TEXT_MIN_SIZE`` zoom gate).
        """
        self._show_codes = bool(show)
        self.render()

    def set_pattern(
        self,
        grid_rgb: np.ndarray,
        codes: Optional[Sequence[Sequence[Optional[str]]]] = None,
        legend: Optional[Sequence[dict[str, Any]]] = None,
    ) -> None:
        """Store a pattern and render it (grid_rgb is ``(H, W, 3)`` uint8)."""
        self.grid_rgb = np.asarray(grid_rgb, dtype=np.uint8)
        self.codes = [list(row) for row in codes] if codes is not None else None
        self.legend = list(legend) if legend is not None else None
        self.render()

    def render(
        self,
        grid_rgb: Optional[np.ndarray] = None,
        codes: Optional[Sequence[Sequence[Optional[str]]]] = None,
        legend: Optional[Sequence[dict[str, Any]]] = None,
    ) -> QImage:
        """(Re)draw the pattern into a QImage and return it.

        With arguments, also updates the stored pattern first (useful for
        tests and one-shot rendering). The image is ``(W*c+1, H*c+1)`` px —
        one extra pixel for the outer border of the grid.
        """
        if grid_rgb is not None:
            self.set_pattern(grid_rgb, codes, legend)
            return self._image
        if self.grid_rgb is None or self.grid_rgb.size == 0:
            self._image = None
            self._canvas.update()
            return QImage()
        height, width, _ = self.grid_rgb.shape
        self._image = self._draw(self.grid_rgb, self.codes, width, height)
        self._canvas.setFixedSize(self._image.size())
        self._canvas.update()
        return self._image

    # ------------------------------------------------------------ internals

    def _draw(
        self,
        grid_rgb: np.ndarray,
        codes: Optional[List[List[Optional[str]]]],
        width: int,
        height: int,
    ) -> QImage:
        cell = self._cell_size
        image = QImage(width * cell + 1, height * cell + 1, QImage.Format_RGB32)
        image.fill(QColor(255, 255, 255))
        painter = QPainter(image)
        try:
            for y in range(height):
                for x in range(width):
                    rgb = grid_rgb[y, x]
                    code = codes[y][x] if codes is not None else None
                    color = (
                        _EMPTY_COLOR
                        if code is None
                        else QColor(int(rgb[0]), int(rgb[1]), int(rgb[2]))
                    )
                    painter.fillRect(x * cell, y * cell, cell, cell, color)
                    if (
                        code is not None
                        and self._show_codes
                        and cell >= _CODE_TEXT_MIN_SIZE
                    ):
                        self._paint_code(painter, code, x * cell, y * cell, cell)
            # Grid lines (drawn last so they stay crisp on top of fills).
            if self._show_grid:
                pen = QPen(_GRID_COLOR, 1)
                painter.setPen(pen)
                for x in range(width + 1):
                    painter.drawLine(x * cell, 0, x * cell, height * cell)
                for y in range(height + 1):
                    painter.drawLine(0, y * cell, width * cell, y * cell)
        finally:
            painter.end()
        return image

    def _paint_code(self, painter: QPainter, code: str, x: int, y: int, cell: int) -> None:
        # Luminance of the cell fill decides text color.
        rgb = self.grid_rgb[y // cell, x // cell]
        lum = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
        painter.setPen(QColor(0, 0, 0) if lum >= _GRID_LUMINANCE_THRESHOLD else QColor(255, 255, 255))
        font = QFont(painter.font())
        font.setPixelSize(max(6, cell // 3))
        painter.setFont(font)
        metrics = QFontMetrics(font)
        elided = metrics.elidedText(code, Qt.ElideRight, cell - 2)
        painter.drawText(x, y, cell, cell, Qt.AlignCenter, elided)

    def _on_zoom_changed(self) -> None:
        self._cell_size = int(self.zoom_combo.currentData())
        self.render()
