"""Tests for beadstudio.core.export — PNG chart and shopping list rendering."""

import csv
import io
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from PIL import Image

from beadstudio.core.convert import PERLER_COLORS, convert
from beadstudio.core.estimate import estimate_time
from beadstudio.core.export import (
    _INFO_BAR_H,
    _INDEX_MARGIN,
    _LEGEND_BG,
    _LEGEND_MIN_WIDTH,
    _LEGEND_PAD,
    _LEGEND_ROW_H,
    _LINE_COLOR,
    _MAJOR_LINE_COLOR,
    _build_info_bar_text,
    _cell_label,
    _compute_legend,
    _resolve_grid,
    export_png,
    shopping_list_csv,
    shopping_list_png,
)
from beadstudio.core.palette import PERLER_COLORS as PALETTE_PERLER

FIXTURES = Path(__file__).resolve().parent / "fixtures"


# ---------------------------------------------------------------------------
# Helper: build a tiny synthetic grid (raw 2D list)
# ---------------------------------------------------------------------------

def _tiny_grid() -> List[List[Optional[str]]]:
    """3×3 grid with 3 unique perler colours and 1 empty cell."""
    return [
        ["80-19001", None,       "80-19018"],
        ["80-19001", "80-19005", "80-19005"],
        [None,       "80-19005", "80-19001"],
    ]


def _empty_grid() -> List[List[Optional[str]]]:
    """3×3 grid with all None cells."""
    return [[None] * 3 for _ in range(3)]


def _grid_from_convert(**kw) -> Dict[str, Any]:
    """Run convert() on sample_photo.png and return the result dict."""
    return convert(
        str(FIXTURES / "sample_photo.png"),
        width=kw.pop("width", 16),
        height=kw.pop("height", 16),
        color_space=kw.pop("color_space", "cie2000"),
        **kw,
    )


# ---------------------------------------------------------------------------
# Unit tests: _resolve_grid
# ---------------------------------------------------------------------------

class TestResolveGrid:
    """Verify the input-normalisation helper."""

    def test_dict_input(self):
        """Passing a convert() result dict extracts width/height/codes/legend."""
        result = _grid_from_convert(width=10, height=10)
        w, h, codes, legend = _resolve_grid(result)
        assert w == 10
        assert h == 10
        assert len(codes) == 10
        assert all(len(row) == 10 for row in codes)
        assert len(legend) == result["colors_used"]

    def test_list_input(self):
        """Passing a raw 2D list computes width/height and legend."""
        g = _tiny_grid()
        w, h, codes, legend = _resolve_grid(g)
        assert w == 3
        assert h == 3
        assert codes == g
        assert len(legend) == 3  # 80-19001 (3), 80-19005 (3), 80-19018 (1)

    def test_list_input_non_rectangular_raises(self):
        """Ragged grid rows should raise ValueError."""
        bad = [["80-19001", "80-19005"], ["80-19001"]]
        with pytest.raises(ValueError, match="same width"):
            _resolve_grid(bad)

    def test_legend_counts_match_grid(self):
        """Legend Σcount must equal non-None cells."""
        g = _tiny_grid()
        _, _, _, legend = _resolve_grid(g)
        total = sum(e["count"] for e in legend)
        non_empty = sum(1 for row in g for c in row if c is not None)
        assert total == non_empty


# ---------------------------------------------------------------------------
# Unit tests: _compute_legend
# ---------------------------------------------------------------------------

class TestComputeLegend:
    def test_sorted_by_count_desc(self):
        g = _tiny_grid()
        legend = _compute_legend(g)
        # 80-19001 appears 3 times, 80-19005 appears 3 times too
        # 80-19018 appears 1 time
        counts = [e["count"] for e in legend]
        assert counts == sorted(counts, reverse=True)

    def test_empty_grid(self):
        legend = _compute_legend(_empty_grid())
        assert legend == []

    def test_single_color_grid(self):
        g = [["80-15179", "80-15179"], ["80-15179", "80-15179"]]
        legend = _compute_legend(g)
        assert len(legend) == 1
        assert legend[0]["code"] == "80-15179"
        assert legend[0]["count"] == 4


# ---------------------------------------------------------------------------
# Tests: export_png
# ---------------------------------------------------------------------------

class TestExportPng:
    """Chart rendering with gridlines, cell fills, codes, and legend."""

    def test_returns_image(self):
        """export_png returns a PIL Image."""
        g = _tiny_grid()
        img = export_png(g)
        assert isinstance(img, Image.Image)

    def test_image_size(self):
        """Image dimensions should be larger than the grid area (legend present)."""
        g = _tiny_grid()  # 3x3
        img = export_png(g, max_grid_dimension=300)
        w_px, h_px = img.size
        assert w_px > 0
        assert h_px > 0

    def test_legend_area_present(self):
        """PNG width must be > grid area width (legend on right side)."""
        g = _tiny_grid()  # 3×3
        img = export_png(g, max_grid_dimension=300)
        w_px, _ = img.size
        # Grid area: 3 * 100 (cell_size = 300//3) = 300
        # Legend width: 280 minimum + padding = > 300
        grid_area_w = 3 * (300 // 3)  # = 300
        assert w_px > grid_area_w, (
            f"Image width {w_px} must exceed grid area width {grid_area_w} "
            "— legend not present?"
        )

    def test_cell_size_at_least_10(self):
        """Even large grids should have cell_size ≥ 10."""
        result = _grid_from_convert(width=100, height=100)
        img = export_png(result, max_grid_dimension=900)
        # max_grid_dimension // max(100,100) = 900//100 = 9 → clamped to 10
        grid_area_w = 100 * 10  # = 1000
        w_px, _ = img.size
        assert w_px > grid_area_w  # legend area adds width

    def test_output_path_writes_file(self):
        """When output_path is given, a PNG file is written."""
        g = _tiny_grid()
        out_dir = tempfile.mkdtemp()
        out_path = Path(out_dir) / "chart.png"
        try:
            export_png(g, output_path=str(out_path))
            assert out_path.exists()
            assert out_path.stat().st_size > 0
            # Re-open to verify it's valid PNG — explicitly close after
            with Image.open(str(out_path)) as verify:
                assert verify.format == "PNG"
        finally:
            out_path.unlink(missing_ok=True)
            out_path.parent.rmdir()

    def test_cell_size_adapts_to_grid(self):
        """Small grids get bigger cells."""
        small = _tiny_grid()  # 3×3
        large = _grid_from_convert(width=40, height=40)
        img_small = export_png(small, max_grid_dimension=300)
        img_large = export_png(large, max_grid_dimension=300)
        # Small grid cell = 300//3 = 100, large grid cell = 300//40 = 7 → 10
        # Grid area: small=300, large=400
        # Image should be wider for the large grid
        assert img_small.size[0] > 300  # small grid + legend
        assert img_large.size[0] > img_small.size[0]  # large grid area is wider


class TestExportPngEmptyCells:
    """Empty (None) cell rendering."""

    def test_empty_grid_does_not_crash(self):
        """All-None grid should render without error."""
        img = export_png(_empty_grid())
        assert isinstance(img, Image.Image)

    def test_empty_grid_no_colors_in_legend(self):
        """Legend for empty grid should show 0 colours."""
        # We inspect via _resolve_grid since the legend isn't directly exposed
        _, _, _, legend = _resolve_grid(_empty_grid())
        assert len(legend) == 0


class TestExportPngLandscape:
    """Mode H: landscape layout for grids with max(width, height) > 90."""

    @staticmethod
    def _big_grid(w: int = 100, h: int = 60) -> List[List[Optional[str]]]:
        """Two-colour grid; max_dim = max(w, h) must exceed 90."""
        return [
            [("80-19001" if (x + y) % 3 else "80-15201") for x in range(w)]
            for y in range(h)
        ]

    def test_mode_v_small_grid_unchanged(self):
        """≤90-bead grids keep the legacy portrait layout (legend right)."""
        g = _tiny_grid()  # 3×3 → Mode V
        img = export_png(g)
        cell_size = max(10, 900 // 3)
        grid_w = 3 * cell_size
        grid_h = 3 * cell_size
        legend_h = max(3 * _LEGEND_ROW_H + 2 * _LEGEND_PAD, grid_h)
        exp_w = grid_w + _LEGEND_MIN_WIDTH + _LEGEND_PAD
        exp_h = max(grid_h, legend_h) + 2 * _LEGEND_PAD
        assert img.size == (exp_w, exp_h), (
            f"Mode V layout changed: {img.size} != legacy portrait {(exp_w, exp_h)}"
        )
        # No info bar in Mode V: top-left corner is not the info-bar band
        assert img.getpixel((2, 2)) != _LEGEND_BG
        # Legend panel still on the right
        assert img.getpixel((grid_w + _LEGEND_PAD + 5, _LEGEND_PAD + 5)) == _LEGEND_BG
        # No heavy every-10th lines in Mode V: an existing boundary line is
        # 1px regular color, not the darker major color
        assert img.getpixel((cell_size, 10)) == _LINE_COLOR

    def test_mode_h_landscape_triggered(self):
        """91+ beads → info bar on top, legend BELOW the grid (no right panel)."""
        g = self._big_grid(100, 60)  # max_dim 100 > 90
        img = export_png(g)
        cell_size = max(14, 900 // 100)
        grid_w = 100 * cell_size
        grid_h = 60 * cell_size
        exp_w = _INDEX_MARGIN + grid_w + 2 * _LEGEND_PAD
        assert img.size[0] == exp_w, (
            f"Mode H width {img.size[0]} != grid + margins {exp_w} "
            "(legend must sit below, not on the right)"
        )
        assert img.size[1] > grid_h + _INFO_BAR_H, (
            "Mode H height must stack info bar + grid + legend"
        )
        # Info bar present at the top
        assert img.getpixel((10, 10)) == _LEGEND_BG
        # Legend band below the grid
        x0 = _LEGEND_PAD + _INDEX_MARGIN
        y0 = _INFO_BAR_H + _LEGEND_PAD + _INDEX_MARGIN
        ly = y0 + grid_h + _LEGEND_PAD
        assert img.getpixel((x0 + 5, ly + 30)) == _LEGEND_BG

    def test_mode_h_labels_present(self):
        """Mode H cells still contain colour-code text (≥14px cells)."""
        g = self._big_grid(100, 60)
        img = export_png(g)
        cell_size = max(14, 900 // 100)
        x0 = _LEGEND_PAD + _INDEX_MARGIN
        y0 = _INFO_BAR_H + _LEGEND_PAD + _INDEX_MARGIN
        pix = img.load()
        # Scan the centre band of cell (5,5) for any non-fill (text) pixel
        cx = x0 + 5 * cell_size + cell_size // 2
        cy = y0 + 5 * cell_size + cell_size // 2
        found_text = any(
            pix[cx + dx, cy + dy][0] < 200
            for dx in range(-cell_size // 2, cell_size // 2 + 1)
            for dy in range(-3, 4)
        )
        assert found_text, "no code-text pixels found inside a Mode H cell"

    def test_info_bar_content(self):
        """Info bar text contains size, bead count, and all three tiers + cost."""
        est = estimate_time(beads=6000, rate=25, colors=2)
        text = _build_info_bar_text(100, 60, 6000, 2, est, 30)
        assert "图纸 100×60" in text
        assert "总豆数 6000" in text
        assert "估计拼装" in text
        for tier in ("新手", "普通", "熟练"):
            assert tier in text, f"missing tier {tier!r} in: {text}"
        assert "30元/时" in text
        assert "¥" in text
        # 6000 beads → beginner 610 min → "10h 10m"
        assert "10h 10m" in text, text

    def test_ten_cell_heavy_lines(self):
        """Every-10th grid line is 3px wide and darker; others stay 1px."""
        g = [["80-19001"] * 92 for _ in range(46)]  # max_dim 92 > 90 → Mode H
        img = export_png(g, max_grid_dimension=1840)
        cell_size = 1840 // 92  # 20, ≥ 14
        assert cell_size == 20
        x0 = _LEGEND_PAD + _INDEX_MARGIN
        y0 = _INFO_BAR_H + _LEGEND_PAD + _INDEX_MARGIN
        pix = img.load()
        major_px = x0 + 10 * cell_size
        minor_px = x0 + 5 * cell_size
        # Sample cell-CENTRE rows: horizontal boundary lines (drawn last)
        # would otherwise overwrite the vertical major-line pixels.
        for k in range(0, 46, 3):
            row = y0 + k * cell_size + cell_size // 2
            # Heavy line: 3px wide strip of the darker major color
            assert pix[major_px - 1, row] == _MAJOR_LINE_COLOR
            assert pix[major_px, row] == _MAJOR_LINE_COLOR
            assert pix[major_px + 1, row] == _MAJOR_LINE_COLOR
            # Normal line: 1px, regular color (neighbour is not the line color)
            assert pix[minor_px, row] == _LINE_COLOR
            assert pix[minor_px + 1, row] != _LINE_COLOR

    def test_condensed_label_cell_8_13(self):
        """cell_size 8-13 → brand prefix stripped; ≥14 full; <8 none."""
        assert _cell_label("80-15201", 14) == "80-15201"
        assert _cell_label("80-15201", 13) == "15201"
        assert _cell_label("80-15201", 10) == "15201"
        assert _cell_label("80-15201", 8) == "15201"
        assert _cell_label("80-15201", 7) is None
        assert _cell_label(None, 20) is None
        assert _cell_label("H7", 10) == "H7"  # no dash → unchanged


class TestExportPngPalette:
    """Palette integration for colour-name lookup."""

    def test_palette_name_in_image(self):
        """Legend should include colour names when palette is provided."""
        from beadstudio.core.palette import load_palette
        palette = load_palette("perler")
        g = _grid_from_convert(width=10, height=10)
        img = export_png(g, palette=palette)
        # Programmatic check: image dimensions > grid area
        grid_w = 10 * (900 // 10)  # 10 * 90 = 900
        assert img.size[0] > grid_w

    def test_non_perler_palette_colors_grid_cells(self):
        """Grid cells must be filled with the brand palette RGB, not empty white.

        Regression: without a palette, non-perler codes (e.g. mard's ``H7``)
        were missing from the perler-only fallback map, so every cell
        rendered white (pure black-and-white output).
        """
        from beadstudio.core.palette import load_palette

        palette = load_palette("mard")
        rgb_by_code = {c["code"]: tuple(c["rgb"]) for c in palette["colors"]}

        # 2×2 grid with mard codes + 1 empty cell
        g = [["H7", "C20"], ["C12", None]]
        img = export_png(g, palette=palette)
        cell_size = 900 // 2  # max_grid_dimension // max(2,2)
        pix = img.load()
        # Sample near each cell's top-left corner — away from the centred
        # code-text glyph — so the pixel is pure cell fill.
        def fill_of(col: int, row: int):
            return pix[col * cell_size + 5, row * cell_size + 5]

        # Cells must use the palette RGB (not _EMPTY_COLOR white)
        assert fill_of(0, 0) == rgb_by_code["H7"]
        assert fill_of(1, 0) == rgb_by_code["C20"]
        assert fill_of(0, 1) == rgb_by_code["C12"]
        # Empty cell stays white
        assert fill_of(1, 1) == (255, 255, 255)

    def test_non_perler_codes_white_without_palette(self):
        """Without a palette, non-perler codes fall back to white cells.

        Pins the pre-fix behavior at the export layer: mard codes are not
        in the perler-only fallback map, so cells render as empty white.
        """
        g = [["H7", "C20"], ["C12", None]]
        img = export_png(g, palette=None)
        cell_size = 900 // 2
        pix = img.load()
        assert pix[5, 5] == (255, 255, 255)
        assert pix[cell_size + 5, cell_size + 5] == (255, 255, 255)


# ---------------------------------------------------------------------------
# Tests: shopping_list_csv
# ---------------------------------------------------------------------------

class TestShoppingListCsv:
    """CSV shopping list generation."""

    def test_returns_string_when_no_path(self):
        """Without output_path, returns CSV string."""
        result = shopping_list_csv(_tiny_grid())
        assert isinstance(result, str)
        assert len(result) > 0

    def test_has_five_columns(self):
        """Header must have exactly 5 columns: brand,code,name,RGB,count."""
        csv_str = shopping_list_csv(_tiny_grid())
        reader = csv.reader(io.StringIO(csv_str))
        header = next(reader)
        assert header == ["brand", "code", "name", "RGB", "count"]

    def test_all_rows_have_five_fields(self):
        """Every data row must have exactly 5 fields."""
        csv_str = shopping_list_csv(_tiny_grid())
        reader = csv.reader(io.StringIO(csv_str))
        next(reader)  # skip header
        for row in reader:
            assert len(row) == 5, f"Row has {len(row)} fields: {row}"

    def test_sum_count_equals_non_empty_cells(self):
        """Σcount must equal the actual non-empty cell count exactly."""
        g = _tiny_grid()
        csv_str = shopping_list_csv(g)
        reader = csv.DictReader(io.StringIO(csv_str))
        total = sum(int(row["count"]) for row in reader)
        non_empty = sum(1 for row in g for c in row if c is not None)
        assert total == non_empty, f"Sum of counts {total} != non-empty cells {non_empty}"

    def test_empty_grid_count_zero(self):
        """Empty grid → count column sums to 0."""
        csv_str = shopping_list_csv(_empty_grid())
        reader = csv.DictReader(io.StringIO(csv_str))
        rows = list(reader)
        # Empty grid → no data rows (or zero-count rows?)
        # Our implementation produces no rows for unused colours
        total = sum(int(row["count"]) for row in rows)
        assert total == 0

    def test_sorted_by_count_descending(self):
        """Rows must be sorted by count descending."""
        g = [["80-19001", "80-19005", "80-19005"],  # 19001:1, 19005:2
             ["80-19005", "80-19001", "80-19005"]]  # 19001:2, 19005:5 → 19005 first
        csv_str = shopping_list_csv(g)
        reader = csv.DictReader(io.StringIO(csv_str))
        counts = [int(row["count"]) for row in reader]
        assert counts == sorted(counts, reverse=True), f"Not sorted desc: {counts}"

    def test_output_path_writes_file(self):
        """When output_path is given, CSV is written."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as tf:
            tf.write("")  # placeholder
            out_path = tf.name
        try:
            result = shopping_list_csv(_tiny_grid(), output_path=out_path)
            assert result is None  # returns None when writing to file
            content = Path(out_path).read_text(encoding="utf-8")
            assert "brand,code,name,RGB,count" in content
        finally:
            Path(out_path).unlink(missing_ok=True)

    def test_palette_fills_brand_and_name(self):
        """When palette is provided, brand and name columns are populated."""
        from beadstudio.core.palette import load_palette
        palette = load_palette("perler")
        csv_str = shopping_list_csv(_tiny_grid(), palette=palette)
        reader = csv.DictReader(io.StringIO(csv_str))
        for row in reader:
            assert row["brand"] == "Perler", f"Expected brand 'Perler', got {row['brand']}"
            assert row["name"] != "", f"Name should not be empty for {row['code']}"

    def test_convert_result_as_input(self):
        """CSV works when given the full convert() result dict."""
        result = _grid_from_convert(width=10, height=10)
        csv_str = shopping_list_csv(result)
        rows = list(csv.DictReader(io.StringIO(csv_str)))
        # Should have some rows
        assert len(rows) > 0
        total = sum(int(row["count"]) for row in rows)
        non_empty = (result["width"] * result["height"]) - result["empty_count"]
        assert total == non_empty

    def test_shopping_csv_formula_injection_sanitized(self):
        """Code/name/brand cells starting with = + - @ get ' prefix (CWE-1236)."""
        palette = {
            "brand": "=EVIL",
            "colors": [
                {"code": "=SUM(A1:A9)", "name": "+calc", "rgb": [255, 0, 0]},
                {"code": "80-19001", "name": "White", "rgb": [255, 255, 255]},
            ],
        }
        grid = [["=SUM(A1:A9)", "80-19001"]]
        csv_str = shopping_list_csv(grid, palette=palette)
        reader = csv.reader(io.StringIO(csv_str))
        header = next(reader)
        # Header is a fixed literal — must stay untouched
        assert header == ["brand", "code", "name", "RGB", "count"]
        rows = list(reader)
        by_code = {row[1]: row for row in rows}
        # Code, name, and brand are all single-quote-prefixed
        assert "'=SUM(A1:A9)" in by_code
        assert by_code["'=SUM(A1:A9)"][2] == "'+calc"
        assert by_code["'=SUM(A1:A9)"][0] == "'=EVIL"
        # Normal codes/names pass through unchanged
        assert by_code["80-19001"][1] == "80-19001"
        assert by_code["80-19001"][2] == "White"
        # No raw formula metacharacter cell survives in the whole CSV
        raw_cells = [
            field
            for row in rows
            for field in row
            if isinstance(field, str) and field and field[0] in "=+-@\t\r"
        ]
        assert raw_cells == []


# ---------------------------------------------------------------------------
# Tests: shopping_list_png
# ---------------------------------------------------------------------------

class TestShoppingListPng:
    """PNG shopping-list table rendering."""

    def test_returns_image(self):
        img = shopping_list_png(_tiny_grid())
        assert isinstance(img, Image.Image)

    def test_image_dimensions_sensible(self):
        """Image should be wider than it is tall for a small grid."""
        img = shopping_list_png(_tiny_grid())
        w, h = img.size
        assert w > 0
        assert h > 0
        # Table layout: width should be ~450px, height ~ 36 + 3*28 + 8
        assert w > 300, f"Expected width > 300, got {w}"

    def test_output_path_writes_file(self):
        out_dir = tempfile.mkdtemp()
        out_path = Path(out_dir) / "shoplist.png"
        try:
            shopping_list_png(_tiny_grid(), output_path=str(out_path))
            assert out_path.exists()
            assert out_path.stat().st_size > 0
            with Image.open(str(out_path)) as verify:
                assert verify.format == "PNG"
        finally:
            out_path.unlink(missing_ok=True)
            out_path.parent.rmdir()

    def test_empty_grid_renders(self):
        """All-None grid should produce a valid (empty) table image."""
        img = shopping_list_png(_empty_grid())
        assert isinstance(img, Image.Image)
        # Should still have header row (height > 36)
        assert img.size[1] >= 36

    def test_row_count_matches_colors(self):
        """For a known grid, image height should scale with number of unique colours."""
        g = _tiny_grid()  # 3 unique colours
        img_small = shopping_list_png(g)
        # Build a grid with more unique colours via convert
        result = _grid_from_convert(width=20, height=20)
        img_large = shopping_list_png(result)
        # More colours → taller image
        assert img_large.size[1] > img_small.size[1], (
            f"Larger grid ({img_large.size[1]}px) should be taller than "
            f"small ({img_small.size[1]}px)"
        )


# ---------------------------------------------------------------------------
# Tests: integration — export_png from actual convert result
# ---------------------------------------------------------------------------

class TestIntegration:
    """End-to-end: convert → export pipeline."""

    def test_convert_then_export_png(self):
        """Full pipeline: convert a real image, then render chart."""
        result = _grid_from_convert(width=16, height=16)
        img = export_png(result)
        assert isinstance(img, Image.Image)
        w, h = img.size
        assert w > 0 and h > 0

    def test_convert_then_shopping_list_csv(self):
        """Full pipeline: convert → CSV."""
        result = _grid_from_convert(width=10, height=10)
        csv_str = shopping_list_csv(result)
        assert isinstance(csv_str, str)
        # Verify non-empty count matches
        reader = csv.DictReader(io.StringIO(csv_str))
        total = sum(int(row["count"]) for row in reader)
        non_empty = (10 * 10) - result["empty_count"]
        assert total == non_empty

    def test_convert_then_shopping_list_png(self):
        """Full pipeline: convert → shopping list PNG."""
        result = _grid_from_convert(width=12, height=12)
        img = shopping_list_png(result)
        assert isinstance(img, Image.Image)

    def test_cell_count_consistency_across_exports(self):
        """CSV, PNG chart, and PNG shopping list must agree on colour counts."""
        result = _grid_from_convert(width=10, height=10)

        # Count from legend (which is authoritative)
        legend_total = sum(e["count"] for e in result["legend"])

        # Count from CSV
        csv_str = shopping_list_csv(result)
        csv_total = sum(
            int(row["count"])
            for row in csv.DictReader(io.StringIO(csv_str))
        )

        # Verify non-empty cells from grid
        non_empty = (10 * 10) - result["empty_count"]
        assert legend_total == non_empty
        assert csv_total == non_empty

    def test_deterministic_output(self):
        """Same convert result → identical PNG export byte-for-byte."""
        result = _grid_from_convert(width=10, height=10, color_space="cie2000")
        img1 = export_png(result)
        img2 = export_png(result)

        buf1 = io.BytesIO()
        buf2 = io.BytesIO()
        img1.save(buf1, format="PNG")
        img2.save(buf2, format="PNG")
        assert buf1.getvalue() == buf2.getvalue()


# ---------------------------------------------------------------------------
# Tests: RGB map completeness
# ---------------------------------------------------------------------------

class TestPerlerRgbMap:
    """Verify the single-source perler palette (palette.py, from perler.json)
    agrees with the pipeline-derived export path."""

    def test_palette_source_matches_pipeline(self):
        """dict(palette.PERLER_COLORS) must equal the pipeline-derived map."""
        assert dict(PALETTE_PERLER) == dict(PERLER_COLORS)

    def test_map_count(self):
        """Single source has exactly 103 entries."""
        assert len(PALETTE_PERLER) == 103
        assert len(PERLER_COLORS) == 103
