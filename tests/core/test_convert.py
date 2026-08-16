"""Tests for beadstudio.core.convert — the core image-to-bead pipeline."""

import inspect
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from beadstudio.core.convert import (
    PERLER_CODES,
    PERLER_COLORS,
    _MEAN_EDGE_MAX,
    _MEAN_EDGE_REF_CELL_AREA,
    _MEAN_EDGE_SCALE_K_HIGH,
    _MEAN_EDGE_SCALE_K_LOW,
    _MAX_SOURCE_PIXELS,
    _bfs_region_cleanup,
    _dominant_color_cell,
    _edge_scale,
    _load_and_prepare,
    _merge_rare_colors,
    convert,
    nearest_indices,
    parse_cell_mode,
    srgb_to_lab,
    srgb_to_linear,
    srgb_to_oklab,
)
from beadstudio.core.models import EdgeConfig

FIXTURES = Path(__file__).resolve().parent / "fixtures"
GOLDEN = Path(__file__).resolve().parent / "golden"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _render_to_png(result: dict, scale: int = 16) -> bytes:
    """Render conversion result to PNG bytes (for byte-identity comparison)."""
    w, h = result["width"], result["height"]
    canvas = Image.new("RGB", (w * scale, h * scale), "white")
    draw = ImageDraw.Draw(canvas)
    perler_map = dict(PERLER_COLORS)

    for y in range(h):
        for x in range(w):
            code = result["codes"][y][x]
            left, top = x * scale, y * scale
            box = (left, top, left + scale, top + scale)
            if code:
                rgb = perler_map[code]
                draw.rectangle(box, fill=rgb)
            else:
                draw.rectangle(box, fill=(255, 255, 255))
            draw.rectangle(box, outline=(210, 210, 210))

    import io
    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Unit tests: sRGB→Lab gamma correction
# ---------------------------------------------------------------------------

class TestGammaCorrection:
    """Verify sRGB → linear → XYZ → Lab chain with known reference values."""

    def test_black_to_lab(self):
        """Black sRGB (0,0,0) should map to Lab (0, 0, 0)."""
        lab = srgb_to_lab(np.array([[[0, 0, 0]]], dtype=np.uint8))
        assert lab.shape == (1, 1, 3)
        assert lab[0, 0, 0] == pytest.approx(0.0, abs=0.1)
        # a* and b* for perfect black should be near 0
        assert abs(lab[0, 0, 1]) < 1.0
        assert abs(lab[0, 0, 2]) < 1.0

    def test_white_to_lab(self):
        """White sRGB (255,255,255) should map to Lab near (100, 0, 0)."""
        lab = srgb_to_lab(np.array([[[255, 255, 255]]], dtype=np.uint8))
        L = lab[0, 0, 0]
        assert L == pytest.approx(100.0, abs=1.0)
        assert abs(lab[0, 0, 1]) < 0.5
        assert abs(lab[0, 0, 2]) < 0.5

    def test_red_to_lab(self):
        """Pure red sRGB (255,0,0) should have positive a* and L ~ 53."""
        lab = srgb_to_lab(np.array([[[255, 0, 0]]], dtype=np.uint8))
        L = lab[0, 0, 0]
        a = lab[0, 0, 1]
        assert 50 < L < 60, f"Expected L ~ 53, got {L:.1f}"
        assert a > 20, f"Expected a* > 0, got {a:.1f}"

    def test_gamma_linear_roundtrip(self):
        """Linearize then re-encode should be identity for non-clamped values."""
        vals = np.array([0.1, 0.3, 0.5, 0.7, 0.9], dtype=np.float64)
        rgb_3 = np.column_stack([vals, vals, vals])
        linear = srgb_to_linear(rgb_3)
        from beadstudio.core.convert import linear_to_srgb
        back = linear_to_srgb(linear)
        np.testing.assert_allclose(back, rgb_3, atol=1e-6)

    def test_linearize_zero(self):
        """sRGB 0 → linear 0."""
        result = srgb_to_linear(np.zeros(3, dtype=np.float64))
        np.testing.assert_array_equal(result, np.zeros(3))

    def test_linearize_one(self):
        """sRGB 1.0 → linear 1.0."""
        result = srgb_to_linear(np.ones(3, dtype=np.float64))
        np.testing.assert_allclose(result, np.ones(3), atol=1e-6)


# ---------------------------------------------------------------------------
# Unit tests: dominant color per cell
# ---------------------------------------------------------------------------

class TestDominantColor:
    """Verify most-frequent color extraction (not mean, avoids gray halos)."""

    def test_all_same(self):
        """All pixels same → that color."""
        region = np.full((4, 4, 3), (100, 150, 200), dtype=np.uint8)
        result = _dominant_color_cell(region)
        np.testing.assert_array_equal(result, np.array([100, 150, 200], dtype=np.uint8))

    def test_majority_wins(self):
        """Most frequent color should win over minority."""
        region = np.zeros((3, 3, 3), dtype=np.uint8)
        region[:6] = (10, 20, 30)  # 6 pixels
        region[6:] = (40, 50, 60)  # 3 pixels
        result = _dominant_color_cell(region)
        np.testing.assert_array_equal(result, np.array([10, 20, 30], dtype=np.uint8))

    def test_single_pixel(self):
        """Single pixel should return itself."""
        region = np.array([[[255, 128, 0]]], dtype=np.uint8)
        result = _dominant_color_cell(region)
        np.testing.assert_array_equal(result, np.array([255, 128, 0], dtype=np.uint8))

    def test_not_mean(self):
        """Dominant color should NOT be the mean (which could be a gray not in the image)."""
        # Half red, half green — mean is yellow but winner is tied (pick first)
        region = np.zeros((2, 2, 3), dtype=np.uint8)
        region[:2] = (255, 0, 0)  # red
        region[2:] = (0, 255, 0)  # green
        result = _dominant_color_cell(region)
        # Should be one of the actual colors, not a blend
        assert tuple(result) in [(255, 0, 0), (0, 255, 0)]


# ---------------------------------------------------------------------------
# Unit tests: nearest_indices (CIEDE2000 and OKLab)
# ---------------------------------------------------------------------------

class TestNearestIndices:
    """Verify color matching via CIEDE2000 and OKLab."""

    def test_ciede2000_perfect_match(self):
        """A palette color should match itself."""
        palette = np.array([[255, 0, 0], [0, 255, 0], [0, 0, 255]], dtype=np.float64)
        pixels = np.array([[255, 0, 0], [0, 255, 0], [0, 0, 255]], dtype=np.float64)
        indices = nearest_indices(pixels, palette, color_space="cie2000")
        np.testing.assert_array_equal(indices, [0, 1, 2])

    def test_oklab_perfect_match(self):
        """OKLab should also match self."""
        palette = np.array([[255, 0, 0], [0, 255, 0], [0, 0, 255]], dtype=np.float64)
        pixels = np.array([[255, 0, 0], [0, 255, 0], [0, 0, 255]], dtype=np.float64)
        indices = nearest_indices(pixels, palette, color_space="oklab")
        np.testing.assert_array_equal(indices, [0, 1, 2])

    def test_white_matches_white(self):
        """White pixel should match the white palette entry."""
        palette = np.array([[0, 0, 0], [255, 255, 255], [128, 128, 128]], dtype=np.float64)
        pixels = np.array([[254, 254, 254]], dtype=np.float64)
        indices = nearest_indices(pixels, palette, color_space="cie2000")
        assert indices[0] == 1  # should match white (index 1)


# ---------------------------------------------------------------------------
# Unit tests: BFS region cleanup
# ---------------------------------------------------------------------------

class TestBFSRegionCleanup:
    """Verify small-region merging via BFS."""

    def test_single_isolated_pixel_merged(self):
        """A lone pixel in a majority region should be absorbed."""
        # 3x3 grid: center is color 1, rest is color 0
        indices = np.array([
            [0, 0, 0],
            [0, 1, 0],
            [0, 0, 0],
        ], dtype=np.int32)
        active = np.ones((3, 3), dtype=bool)
        result = _bfs_region_cleanup(indices, active, min_region_size=2)
        # Center should be merged to 0 (region size 1 < 2)
        assert result[1, 1] == 0

    def test_large_region_preserved(self):
        """A region at or above min_size should be kept."""
        indices = np.full((4, 4), 0, dtype=np.int32)
        indices[0, 0] = 1  # isolated
        active = np.ones((4, 4), dtype=bool)
        result = _bfs_region_cleanup(indices, active, min_region_size=2)
        # region of color 0 is 15 cells → preserved
        assert np.sum(result == 0) == 16  # isolated 1 merged to 0

    def test_no_cleanup_when_min_size_one(self):
        """min_region_size=1 should be a no-op."""
        indices = np.array([[0, 1], [1, 0]], dtype=np.int32)
        active = np.ones((2, 2), dtype=bool)
        result = _bfs_region_cleanup(indices, active, min_region_size=1)
        np.testing.assert_array_equal(result, indices)

    def test_inactive_cells_ignored(self):
        """Inactive (-1) cells should not participate."""
        indices = np.array([
            [0, -1, 0],
            [0,  1, 0],
            [0,  0, 0],
        ], dtype=np.int32)
        active = np.array([
            [True, False, True],
            [True, True, True],
            [True, True, True],
        ])
        result = _bfs_region_cleanup(indices, active, min_region_size=2)
        # 1 is isolated → merged; -1 stays
        assert result[1, 1] == 0
        assert result[0, 1] == -1


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestConvertPipeline:
    """End-to-end pipeline tests."""

    def test_photo_conversion_basic(self):
        """sample_photo.png should convert without error and return expected keys."""
        result = convert(
            str(FIXTURES / "sample_photo.png"),
            width=20, height=20,
            color_space="cie2000",
        )
        assert result["width"] == 20
        assert result["height"] == 20
        assert "codes" in result
        assert "indices" in result
        assert "legend" in result
        assert "empty_count" in result
        assert "colors_used" in result
        assert result["colors_used"] > 0
        assert len(result["codes"]) == 20
        assert all(len(row) == 20 for row in result["codes"])
        assert all(isinstance(c, (str, type(None))) for row in result["codes"] for c in row)

    def test_pixel_art_conversion(self):
        """sample_pixel_art.png should convert cleanly."""
        result = convert(
            str(FIXTURES / "sample_pixel_art.png"),
            width=16, height=16,
            color_space="oklab",
        )
        assert result["width"] == 16
        assert result["height"] == 16
        assert result["colors_used"] > 0

    def test_alpha_transparency(self):
        """RGBA image with transparency should produce empty pegs."""
        result = convert(
            str(FIXTURES / "sample_alpha.png"),
            width=10, height=10,
            alpha_threshold=128,
        )
        # sample_alpha.png has transparent regions → should have empty pegs
        assert result["empty_count"] > 0, (
            f"Expected empty pegs for transparent regions, got {result['empty_count']}"
        )

    def test_height_derived_from_aspect_ratio(self, tmp_path):
        """When height is None, derive it from the source image's aspect ratio."""
        # 200×100 source → 2:1 → width=20 should give height=10 (NOT 20).
        img = Image.new("RGB", (200, 100), (120, 60, 30))
        img.save(tmp_path / "wide.png")
        result = convert(str(tmp_path / "wide.png"), width=20)
        assert result["width"] == 20
        assert result["height"] == 10

    def test_width_derived_from_aspect_ratio(self, tmp_path):
        """When width is None, derive it from the source image's aspect ratio."""
        # 200×100 source → width=40 should give height=20 (NOT 40).
        img = Image.new("RGB", (200, 100), (120, 60, 30))
        img.save(tmp_path / "wide.png")
        result = convert(str(tmp_path / "wide.png"), height=20)
        assert result["width"] == 40
        assert result["height"] == 20

    def test_derived_dimension_rounded_and_min_one(self, tmp_path):
        """Derived dimension rounds to nearest bead, never below 1."""
        # 999×750 photo → width=52 → height=round(52*750/999)=39.
        img = Image.new("RGB", (999, 750), (120, 60, 30))
        img.save(tmp_path / "photo.png")
        result = convert(str(tmp_path / "photo.png"), width=52)
        assert result["height"] == 39
        # Extreme aspect: 100×1 source → width=1 → height must be ≥ 1.
        img2 = Image.new("RGB", (100, 1), (120, 60, 30))
        img2.save(tmp_path / "strip.png")
        result2 = convert(str(tmp_path / "strip.png"), width=1)
        assert result2["height"] >= 1

    def test_explicit_both_dimensions_kept(self, tmp_path):
        """When both dimensions are given, they are used as-is."""
        img = Image.new("RGB", (200, 100), (120, 60, 30))
        img.save(tmp_path / "wide.png")
        result = convert(str(tmp_path / "wide.png"), width=20, height=13)
        assert result["width"] == 20
        assert result["height"] == 13

    def test_square_source_still_square(self):
        """A square source with only width still gives a square grid."""
        result = convert(
            str(FIXTURES / "sample_photo.png"),
            width=10,
        )
        assert result["width"] == 10
        assert result["height"] == 10

    def test_with_dither(self):
        """Dithering should produce a valid result."""
        result = convert(
            str(FIXTURES / "sample_photo.png"),
            width=10, height=10,
            dither=True,
        )
        assert result["width"] == 10
        assert result["colors_used"] > 0

    def test_no_cleanup(self):
        """cleanup=False should still produce valid output."""
        result = convert(
            str(FIXTURES / "sample_photo.png"),
            width=10, height=10,
            cleanup=False,
        )
        assert result["colors_used"] > 0

    def test_hama_brand_conversion(self):
        """Non-perler brand (hama) must convert successfully."""
        result = convert(
            str(FIXTURES / "sample_photo.png"),
            width=20, height=20,
            brand="hama",
        )
        assert result["width"] == 20
        assert result["height"] == 20
        assert result["colors_used"] > 0
        # Verify codes are Hama-style (H01, H02, ...) not Perler (80-xxxxx)
        for row in result["codes"]:
            for code in row:
                if code is not None:
                    assert isinstance(code, str)
                    # Hama codes start with 'H' followed by digits
                    assert code.startswith("H"), f"Expected Hama code, got {code!r}"

    def test_unknown_brand_raises(self):
        """Completely unknown brand must raise ValueError."""
        with pytest.raises(ValueError, match="不支持的品牌"):
            convert(
                str(FIXTURES / "sample_photo.png"),
                width=10, height=10,
                brand="brand_does_not_exist",
            )


# ---------------------------------------------------------------------------
# Color-count limiting (max_colors / _merge_rare_colors)
# ---------------------------------------------------------------------------

class TestMergeRareColors:
    """Unit tests for the rarest-color merge used by max_colors."""

    def test_noop_when_within_limit(self):
        """≤ max_colors used colors → grid unchanged."""
        indices = np.array([
            [0, 1, 0],
            [2, 0, 1],
            [1, 2, 0],
        ], dtype=np.int32)
        active = np.ones((3, 3), dtype=bool)
        palette_space = np.array([[0, 0, 0], [100, 0, 0], [0, 100, 0]], dtype=np.float64)
        out = _merge_rare_colors(indices, active, palette_space, max_colors=3)
        np.testing.assert_array_equal(out, indices)

    def test_rarest_merged_to_nearest(self):
        """Rarest color is remapped to the nearest other used color."""
        # Colors 0,1,2: 4, 4, 1 cells → color 2 (1 cell) merges into nearest.
        indices = np.array([
            [0, 1, 2],
            [1, 0, 0],
            [1, 1, 0],
        ], dtype=np.int32)
        active = np.ones((3, 3), dtype=bool)
        palette_space = np.array([[0, 0, 0], [10, 0, 0], [11, 0, 0]], dtype=np.float64)
        out = _merge_rare_colors(indices, active, palette_space, max_colors=2)
        used = np.unique(out)
        assert len(used) == 2
        # Color 2 is closer to 1 (dist 1) than to 0 (dist 11) → cell becomes 1.
        assert out[0, 2] == 1

    def test_repeated_merges_reach_limit(self):
        """Loop keeps merging until ≤ max_colors remain."""
        indices = np.array([
            [0, 1, 2, 3],
            [4, 5, 6, 7],
            [0, 1, 2, 3],
            [4, 5, 6, 7],
        ], dtype=np.int32)
        active = np.ones((4, 4), dtype=bool)
        palette_space = np.arange(8 * 3, dtype=np.float64).reshape(8, 3)
        out = _merge_rare_colors(indices, active, palette_space, max_colors=2)
        used = np.unique(out)
        assert len(used) <= 2
        assert np.all(used >= 0)

    def test_inactive_cells_untouched(self):
        """-1 / inactive cells are never remapped."""
        indices = np.array([
            [0, -1, 1],
            [0, -1, 1],
            [0,  1, 1],
        ], dtype=np.int32)
        active = np.array([
            [True, False, True],
            [True, False, True],
            [True, True, True],
        ])
        palette_space = np.array([[0, 0, 0], [100, 0, 0], [101, 0, 0]], dtype=np.float64)
        out = _merge_rare_colors(indices, active, palette_space, max_colors=1)
        # Only one color may remain among active cells (rarest 0 → nearest 1).
        assert len(np.unique(out[active])) == 1
        assert np.all(out[~active] == -1)

    def test_empty_grid_noop(self):
        """No active cells → unchanged."""
        indices = np.full((3, 3), -1, dtype=np.int32)
        active = np.zeros((3, 3), dtype=bool)
        palette_space = np.array([[0, 0, 0], [100, 0, 0]], dtype=np.float64)
        out = _merge_rare_colors(indices, active, palette_space, max_colors=1)
        np.testing.assert_array_equal(out, indices)


class TestMaxColors:
    """End-to-end max_colors limiting in convert()."""

    def test_none_keeps_current_behavior(self):
        """max_colors=None must be byte-identical to the old pipeline."""
        baseline = convert(str(FIXTURES / "sample_photo.png"), width=20, height=20)
        limited = convert(str(FIXTURES / "sample_photo.png"), width=20, height=20, max_colors=None)
        assert limited["codes"] == baseline["codes"]
        assert limited["indices"] == baseline["indices"]
        assert limited["colors_used"] == baseline["colors_used"]

    def test_limits_colors_used(self):
        """max_colors=N → at most N distinct bead colors in the pattern."""
        result = convert(
            str(FIXTURES / "sample_photo.png"),
            width=20, height=20,
            max_colors=6,
        )
        assert 0 < result["colors_used"] <= 6
        assert len(result["legend"]) == result["colors_used"]
        # Every code in the grid appears in the legend.
        used_codes = {c for row in result["codes"] for c in row if c}
        assert used_codes == {entry["code"] for entry in result["legend"]}

    def test_high_limit_has_no_effect(self):
        """max_colors ≥ number of matched colors → unchanged."""
        baseline = convert(str(FIXTURES / "sample_photo.png"), width=20, height=20)
        limited = convert(str(FIXTURES / "sample_photo.png"), width=20, height=20, max_colors=999)
        assert limited["colors_used"] == baseline["colors_used"]
        assert limited["codes"] == baseline["codes"]

    def test_works_with_dither_and_cleanup(self):
        """max_colors composes with dither (and cleanup)."""
        result = convert(
            str(FIXTURES / "sample_photo.png"),
            width=10, height=10,
            dither=True,
            max_colors=5,
        )
        assert 0 < result["colors_used"] <= 5

    def test_invalid_max_colors_raises(self):
        """max_colors < 1 → ValueError."""
        with pytest.raises(ValueError, match="max_colors"):
            convert(
                str(FIXTURES / "sample_photo.png"),
                width=10, height=10,
                max_colors=0,
            )

    def test_deterministic(self):
        """Two runs with max_colors produce identical output."""
        r1 = convert(str(FIXTURES / "sample_photo.png"), width=20, height=20, max_colors=8)
        r2 = convert(str(FIXTURES / "sample_photo.png"), width=20, height=20, max_colors=8)
        assert r1["codes"] == r2["codes"]
        assert r1["indices"] == r2["indices"]
        assert r1["colors_used"] == r2["colors_used"]


# ---------------------------------------------------------------------------
# Series-range filtering (series_range / --series)
# ---------------------------------------------------------------------------

def _prefix(code: str) -> str:
    """Leading alphabetic prefix of a color code ('A1' -> 'A')."""
    return re.match(r"[A-Za-z]+", code).group()


class TestSeriesRange:
    """series_range filtering in convert() (series-structured brands only)."""

    def test_signature_default_none_and_last(self):
        """series_range defaults to None; edge_config is the last convert() parameter."""
        params = list(inspect.signature(convert).parameters.items())
        name, param = params[-1]
        assert name == "edge_config"
        assert param.default is None
        name2, param2 = params[-2]
        assert name2 == "series_range"
        assert param2.default is None

    def test_convert_series_mard_max_M(self):
        """series_range='M' → only A..M codes can be matched (no P/Q/R/T/Y/ZG)."""
        baseline = convert(
            str(FIXTURES / "sample_photo.png"), width=20, height=20, brand="mard_291",
        )
        result = convert(
            str(FIXTURES / "sample_photo.png"), width=20, height=20,
            brand="mard_291", series_range="M",
        )
        legend_prefixes = {_prefix(e["code"]) for e in result["legend"]}
        assert legend_prefixes <= {"A", "B", "C", "D", "E", "F", "G", "H", "M"}
        assert not legend_prefixes & {"P", "Q", "R", "T", "Y", "ZG"}
        # Grid codes and legend agree, and are all in-range.
        used_codes = {c for row in result["codes"] for c in row if c}
        assert used_codes == {e["code"] for e in result["legend"]}
        assert all(_prefix(c) in {"A", "B", "C", "D", "E", "F", "G", "H", "M"} for c in used_codes)
        # Filtering actually changed the outcome vs. the full palette.
        assert result["codes"] != baseline["codes"] or result["legend"] != baseline["legend"]

    def test_convert_series_range(self):
        """series_range='A-G' → only A..G codes."""
        baseline = convert(
            str(FIXTURES / "sample_photo.png"), width=20, height=20, brand="mard_291",
        )
        result = convert(
            str(FIXTURES / "sample_photo.png"), width=20, height=20,
            brand="mard_291", series_range="A-G",
        )
        legend_prefixes = {_prefix(e["code"]) for e in result["legend"]}
        assert legend_prefixes <= {"A", "B", "C", "D", "E", "F", "G"}
        assert not legend_prefixes & {"H", "M", "P", "Q", "R", "T", "Y", "ZG"}
        assert len(result["legend"]) == result["colors_used"]
        # Strictly fewer colors than the full-palette run (A-G ⊂ full palette).
        assert result["colors_used"] < baseline["colors_used"]

    def test_convert_series_flat_noop(self):
        """Flat brand (perler) + series_range → byte-identical to no series."""
        base = convert(str(FIXTURES / "sample_photo.png"), width=20, height=20, brand="perler")
        filtered = convert(
            str(FIXTURES / "sample_photo.png"), width=20, height=20,
            brand="perler", series_range="M",
        )
        assert filtered["codes"] == base["codes"]
        assert filtered["legend"] == base["legend"]
        assert filtered["indices"] == base["indices"]
        assert filtered["colors_used"] == base["colors_used"]

    def test_convert_series_invalid_raises(self):
        """Unknown series spec → ValueError with Chinese message."""
        with pytest.raises(ValueError, match="系列"):
            convert(
                str(FIXTURES / "sample_photo.png"), width=20, height=20,
                brand="mard_291", series_range="ZZ",
            )

    def test_convert_series_none_matches_default(self):
        """series_range=None → byte-identical to calling without the argument."""
        default = convert(str(FIXTURES / "sample_photo.png"), width=20, height=20)
        explicit = convert(
            str(FIXTURES / "sample_photo.png"), width=20, height=20, series_range=None,
        )
        assert explicit["codes"] == default["codes"]
        assert explicit["legend"] == default["legend"]
        assert explicit["indices"] == default["indices"]
        assert explicit["colors_used"] == default["colors_used"]


# ---------------------------------------------------------------------------
# Cell-color mode: whitelist parsing + default threading (--cell-color)
# ---------------------------------------------------------------------------

class TestCellMode:
    """parse_cell_mode whitelist and cell_mode default threading."""

    # -- parse_cell_mode whitelist --------------------------------------

    def test_accepts_four_whitelisted_words(self):
        """dominant/mean/众数/均值 all parse (aliases normalize)."""
        assert parse_cell_mode("dominant") == "dominant"
        assert parse_cell_mode("mean") == "mean"
        assert parse_cell_mode("众数") == "dominant"
        assert parse_cell_mode("均值") == "mean"

    def test_case_insensitive_and_stripped(self):
        """Whitespace and case are ignored."""
        assert parse_cell_mode("  DOMINANT  ") == "dominant"
        assert parse_cell_mode("Mean") == "mean"
        assert parse_cell_mode("  众数 ") == "dominant"

    def test_rejects_unknown_words(self):
        """foo/彩色/1 are not in the whitelist → None."""
        for bad in ("foo", "彩色", "1", "平滑", ""):
            assert parse_cell_mode(bad) is None

    # -- signature defaults (CLI default dominant) ----------------------

    def test_convert_defaults_to_dominant(self):
        """convert() cell_mode defaults to 'dominant' (the CLI default)."""
        assert inspect.signature(convert).parameters["cell_mode"].default == "dominant"

    def test_load_and_prepare_defaults_to_dominant(self):
        """_load_and_prepare() cell_mode defaults to 'dominant'."""
        assert inspect.signature(_load_and_prepare).parameters["cell_mode"].default == "dominant"

    def test_default_behavior_identical_to_explicit_dominant(self):
        """Default cell_mode produces identical output to explicit 'dominant'."""
        default = convert(str(FIXTURES / "sample_photo.png"), width=10, height=10)
        explicit = convert(
            str(FIXTURES / "sample_photo.png"), width=10, height=10, cell_mode="dominant",
        )
        assert default["codes"] == explicit["codes"]
        assert default["indices"] == explicit["indices"]
        assert default["colors_used"] == explicit["colors_used"]

    def test_load_and_prepare_threads_cell_mode(self):
        """_load_and_prepare accepts cell_mode; dominant path unchanged."""
        grid_a, mask_a = _load_and_prepare(FIXTURES / "sample_photo.png", 8, 8)
        grid_b, mask_b = _load_and_prepare(
            FIXTURES / "sample_photo.png", 8, 8, cell_mode="dominant",
        )
        np.testing.assert_array_equal(grid_a, grid_b)
        np.testing.assert_array_equal(mask_a, mask_b)


# ---------------------------------------------------------------------------
# Source image pixel cap (decompression-bomb defense, W0-B/B1)
# ---------------------------------------------------------------------------

def _header_only_png(width: int, height: int) -> bytes:
    """Craft a tiny header-only PNG declaring ``(width, height)``.

    The IHDR declares the oversized dimensions but the IDAT holds a single
    byte of compressed data, so the whole file is only a few dozen bytes on
    disk. PIL's ``Image.open`` reads the size from the header without
    decoding, so this exercises the pre-decode pixel cap without allocating
    any huge arrays.
    """
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    idat = zlib.compress(b"\x00")  # 1 scanline byte; never decoded by the test
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", idat)
        + chunk(b"IEND", b"")
    )


class TestSourcePixelCap:
    """Oversized sources are rejected before decode; normal images pass."""

    def test_cap_constant_and_pil_guard(self):
        """The 24MP cap constant exists and PIL's own guard is set to it."""
        assert _MAX_SOURCE_PIXELS == 24_000_000
        assert Image.MAX_IMAGE_PIXELS == _MAX_SOURCE_PIXELS

    def test_source_pixel_cap_rejects_oversized(self, tmp_path):
        """6000×5000 = 30MP (> 24MP cap) → Chinese ValueError, before decode."""
        img_path = tmp_path / "oversized.png"
        img_path.write_bytes(_header_only_png(6000, 5000))
        # PIL's own bomb guard (Image.MAX_IMAGE_PIXELS = cap) warns at open;
        # our explicit header check then raises the Chinese ValueError.
        with pytest.warns(Image.DecompressionBombWarning):
            with pytest.raises(ValueError, match="图片分辨率过大"):
                _load_and_prepare(img_path, 10, 10)

    def test_source_pixel_cap_allows_normal(self, tmp_path):
        """A normal-size image converts fine (cap does not block valid input)."""
        arr = np.zeros((120, 160, 3), dtype=np.uint8)
        arr[:, :, 0] = 200
        img_path = tmp_path / "normal.png"
        Image.fromarray(arr, "RGB").save(img_path)
        result = convert(str(img_path), width=20, height=15)
        assert result["width"] == 20
        assert result["height"] == 15
        assert len(result["codes"]) == 15
        assert result["empty_count"] == 0


# ---------------------------------------------------------------------------
# Mean cell-color mode (gamma-corrected linear-space mean + alpha mask)
# ---------------------------------------------------------------------------

class TestMeanCellMode:
    """Mean per-cell color extraction: linear-space mean, alpha mask, dither gate."""

    def test_load_and_prepare_accepts_edge_config(self):
        """_load_and_prepare accepts edge_config; None is identical to EdgeConfig().

        The EdgeConfig-aware run must be byte-identical to the default run,
        and an override config must be accepted (and reach the sampler).
        """
        grid_default, mask_default = _load_and_prepare(
            FIXTURES / "sample_photo.png", 8, 8, cell_mode="mean",
        )
        grid_explicit, mask_explicit = _load_and_prepare(
            FIXTURES / "sample_photo.png", 8, 8, cell_mode="mean",
            edge_config=EdgeConfig(),
        )
        np.testing.assert_array_equal(grid_default, grid_explicit)
        np.testing.assert_array_equal(mask_default, mask_explicit)

        # An override (raised LOW/HIGH) is accepted and runs (its effect on
        # the per-cell routing is covered by test_convert_edge_config_changes_output;
        # at 8×8 this photo's cells are all smooth-interior so routing is
        # unchanged here).
        grid_raised, _ = _load_and_prepare(
            FIXTURES / "sample_photo.png", 8, 8, cell_mode="mean",
            edge_config=EdgeConfig(mean_edge_range_low=200, mean_edge_range_high=250),
        )
        assert grid_raised.shape == grid_default.shape

    def test_convert_accepts_edge_config(self):
        """convert() accepts edge_config; None defaults == explicit EdgeConfig()."""
        r1 = convert(
            str(FIXTURES / "sample_photo.png"), width=20, height=20, cell_mode="mean",
        )
        r2 = convert(
            str(FIXTURES / "sample_photo.png"), width=20, height=20, cell_mode="mean",
            edge_config=EdgeConfig(),
        )
        assert r1 == r2, "default (None) and explicit EdgeConfig() must be byte-identical"

        # An explicit override (LOW raised to 200, HIGH 250 — HIGH must exceed
        # LOW per EdgeConfig validation — and min stroke length 6) runs cleanly.
        r3 = convert(
            str(FIXTURES / "sample_photo.png"), width=20, height=20, cell_mode="mean",
            edge_config=EdgeConfig(
                mean_edge_range_low=200, mean_edge_range_high=250, stroke_min_length=6,
            ),
        )
        assert r3["width"] == 20 and r3["height"] == 20
        assert r3["colors_used"] >= 1

    def test_convert_edge_config_changes_output(self, tmp_path):
        """Raising mean_edge_range_low moves a boundary cell onto the smooth-mean path.

        A 6×1 cell half (0,0,80) / half (0,0,230) has per-channel range 150:
        above the default ``low_eff`` ≈ 115 (→ ambiguous zone → dominant, since
        the extreme-pixel ΔE00 ≫ 15) but below the raised ``low_eff`` ≈ 200
        (→ smooth interior → gamma-corrected linear mean ≈ (0,0,176)). So the
        default output is the extreme color while the override is the mean —
        proving edge_config reaches the edge-aware sampler.
        """
        img = Image.new("RGB", (6, 1))
        img.putdata([(0, 0, 80)] * 3 + [(0, 0, 230)] * 3)
        img.save(tmp_path / "edge_cfg.png")

        default_grid, _ = _load_and_prepare(
            tmp_path / "edge_cfg.png", 1, 1, cell_mode="mean",
        )
        raised_grid, _ = _load_and_prepare(
            tmp_path / "edge_cfg.png", 1, 1, cell_mode="mean",
            edge_config=EdgeConfig(mean_edge_range_low=200, mean_edge_range_high=250),
        )
        np.testing.assert_array_equal(default_grid[0, 0], np.array([0, 0, 80], dtype=np.uint8))
        np.testing.assert_array_equal(raised_grid[0, 0], np.array([0, 0, 176], dtype=np.uint8))
        assert not np.array_equal(default_grid, raised_grid), (
            "edge thresholds did not reach the sampler"
        )

    def test_mean_is_deterministic(self):
        """Two mean-mode runs produce byte-identical output."""
        r1 = convert(str(FIXTURES / "sample_photo.png"), width=20, height=20, cell_mode="mean")
        r2 = convert(str(FIXTURES / "sample_photo.png"), width=20, height=20, cell_mode="mean")
        assert r1["codes"] == r2["codes"]
        assert r1["indices"] == r2["indices"]
        assert r1["colors_used"] == r2["colors_used"]
        assert r1["empty_count"] == r2["empty_count"]

    def test_mean_differs_from_dominant_on_gradient(self, tmp_path):
        """On a smooth single-hue gradient, mean stays smooth while dominant snaps.

        Edge-aware sampling keeps MEAN for interior cells (A≤40): a smooth red
        gradient still produces the linear-space mean per cell, which differs
        from dominant mode's most-frequent pick.
        """
        h, w = 60, 60
        arr = np.zeros((h, w, 3), dtype=np.uint8)
        for y in range(h):  # smooth vertical red gradient 100..159 (A≈6/cell)
            arr[y, :] = (int(100 + y), 0, 0)
        img = Image.fromarray(arr, "RGB")
        img.save(tmp_path / "gradient.png")

        mean_grid, mean_mask = _load_and_prepare(
            tmp_path / "gradient.png", 10, 10, cell_mode="mean",
        )
        dom_grid, dom_mask = _load_and_prepare(
            tmp_path / "gradient.png", 10, 10, cell_mode="dominant",
        )
        np.testing.assert_array_equal(mean_mask, dom_mask)
        assert mean_grid.dtype == np.uint8
        assert not np.array_equal(mean_grid, dom_grid), "mean must differ from dominant on a gradient"

    def test_mean_alpha_mask(self, tmp_path):
        """Only pixels with alpha > threshold participate in the mean.

        2×2 cell with two opaque-red and two low-alpha blue pixels → pure red,
        not a purple blend.
        """
        img = Image.new("RGBA", (2, 2))
        img.putdata([
            (255, 0, 0, 255), (255, 0, 0, 255),
            (0, 0, 255, 128), (0, 0, 255, 0),
        ])
        img.save(tmp_path / "alpha.png")
        grid, mask = _load_and_prepare(
            tmp_path / "alpha.png", 1, 1, alpha_threshold=128, cell_mode="mean",
        )
        assert mask[0, 0]
        np.testing.assert_array_equal(grid[0, 0], np.array([255, 0, 0], dtype=np.uint8))

    def test_mean_is_linear_space_blend(self, tmp_path):
        """Mean is computed in gamma-corrected linear space.

        3 green-60 + 3 green-100 pixels → (0, 83, 0), NOT the naive sRGB mean
        (0, 80, 0). The fixture stays in the smooth-interior band (A=40), so
        edge-aware sampling must route it through the unchanged mean logic.
        """
        img = Image.new("RGB", (6, 1))
        img.putdata([
            (0, 60, 0), (0, 60, 0), (0, 60, 0),
            (0, 100, 0), (0, 100, 0), (0, 100, 0),
        ])
        img.save(tmp_path / "blend.png")
        grid, mask = _load_and_prepare(tmp_path / "blend.png", 1, 1, cell_mode="mean")
        assert mask[0, 0]
        np.testing.assert_array_equal(grid[0, 0], np.array([0, 83, 0], dtype=np.uint8))

    def test_mean_smooth_cell_uses_mean(self, tmp_path):
        """A pure-gradient cell (A≈0) keeps the gamma-corrected linear mean.

        Smooth interior regions are unaffected by edge-aware sampling: the
        output is the linear-space mean of the region, not a dominant pick.
        """
        img = Image.new("RGB", (6, 1))
        img.putdata([
            (220, 0, 0), (228, 0, 0), (236, 0, 0),
            (244, 0, 0), (252, 0, 0), (255, 0, 0),
        ])
        img.save(tmp_path / "smooth.png")
        grid, mask = _load_and_prepare(tmp_path / "smooth.png", 1, 1, cell_mode="mean")
        assert mask[0, 0]
        np.testing.assert_array_equal(grid[0, 0], np.array([240, 0, 0], dtype=np.uint8))

    def test_mean_edge_cell_uses_dominant(self, tmp_path):
        """A red+green mixed cell (A>180) is a definite boundary → dominant.

        Mean-averaging would blend (255,0,0)/(0,255,0) into a yellow-green
        gray-halo; edge-aware sampling must output an actual boundary colour
        (red OR green), never an in-between blend.
        """
        img = Image.new("RGB", (4, 1))
        img.putdata([(255, 0, 0)] * 3 + [(0, 255, 0)])
        img.save(tmp_path / "edge.png")
        grid, mask = _load_and_prepare(tmp_path / "edge.png", 1, 1, cell_mode="mean")
        assert mask[0, 0]
        assert tuple(grid[0, 0].tolist()) in ((255, 0, 0), (0, 255, 0)), (
            f"boundary cell blended instead of picking a colour: {grid[0, 0].tolist()}"
        )

    def test_mean_ambiguous_cell_large_deltae_uses_dominant(self, tmp_path):
        """Ambiguous zone (115 < A ≤ 180) with extreme-pixel ΔE00 > 15 → dominant.

        Dark red vs dark green: per-channel range A=140, and the extreme pixels
        differ by ΔE00≈68 → a real boundary, so the cell must not blend.
        """
        img = Image.new("RGB", (4, 1))
        img.putdata([(140, 0, 0)] * 3 + [(0, 140, 0)])
        img.save(tmp_path / "ambig_large.png")
        grid, mask = _load_and_prepare(tmp_path / "ambig_large.png", 1, 1, cell_mode="mean")
        assert mask[0, 0]
        assert tuple(grid[0, 0].tolist()) in ((140, 0, 0), (0, 140, 0)), (
            f"ambiguous high-ΔE cell blended: {grid[0, 0].tolist()}"
        )

    def test_mean_ambiguous_cell_small_deltae_uses_mean(self, tmp_path):
        """A low-A gradient cell (A=80 ≤ 115) is a smooth interior → mean.

        With LOW=115 the (0,0,80)/(0,0,160) pair sits below the fast mean
        path threshold, so it must be blended (linear-space mean), not
        snapped to an extreme colour.
        """
        img = Image.new("RGB", (6, 1))
        img.putdata([(0, 0, 80)] * 3 + [(0, 0, 160)] * 3)
        img.save(tmp_path / "ambig_small.png")
        grid, mask = _load_and_prepare(tmp_path / "ambig_small.png", 1, 1, cell_mode="mean")
        assert mask[0, 0]
        np.testing.assert_array_equal(grid[0, 0], np.array([0, 0, 128], dtype=np.uint8))

    def test_mean_edge_threshold_defaults(self):
        """Pin the evidence-based edge-aware sampling defaults (EdgeConfig)."""
        cfg = EdgeConfig()
        assert cfg.mean_edge_range_low == 115
        assert cfg.mean_edge_range_high == 180
        assert cfg.mean_edge_deltae_threshold == 15.0

    def test_mean_edge_scale_unit(self):
        """_edge_scale(cell_area, k): power-law factor anchored at the golden ref.

        For BOTH decoupled exponents: area == REF → 1.0 (the golden 52×52
        anchor, K-independent); area = REF·4 → 4**k (sub-linear: 4× the pixels
        only raise thresholds by ~15–19%); area = REF·0.25 → 0.25**k;
        degenerate area ≤ 0 → 1.0 so the thresholds are never inflated by a
        broken geometry. The LOW exponent must grow faster than HIGH.
        """
        for k in (_MEAN_EDGE_SCALE_K_LOW, _MEAN_EDGE_SCALE_K_HIGH):
            assert _edge_scale(_MEAN_EDGE_REF_CELL_AREA, k) == pytest.approx(1.0, abs=1e-12)
            assert _edge_scale(_MEAN_EDGE_REF_CELL_AREA * 4.0, k) == pytest.approx(
                4.0 ** k, rel=1e-12,
            )
            assert _edge_scale(_MEAN_EDGE_REF_CELL_AREA * 0.25, k) == pytest.approx(
                0.25 ** k, rel=1e-12,
            )
            assert _edge_scale(0.0, k) == 1.0
            assert _edge_scale(-3.0, k) == 1.0
        # LOW rises faster than HIGH: 4× area → LOW scale > HIGH scale.
        assert _edge_scale(
            _MEAN_EDGE_REF_CELL_AREA * 4.0, _MEAN_EDGE_SCALE_K_LOW,
        ) > _edge_scale(
            _MEAN_EDGE_REF_CELL_AREA * 4.0, _MEAN_EDGE_SCALE_K_HIGH,
        )

    def test_mean_edge_thresholds_adapt_to_grid_size(self):
        """Effective mean thresholds scale with cell area (decoupled exponents).

        Big grids (small cells) get LOWER effective thresholds than the
        nominal 115/180 — a 128×128 source at a 128×128 grid (cell_area=1.0)
        yields low_eff≈91 < 115 and high_eff≈160 < 180. Small grids (big
        cells) get HIGHER effective thresholds — a 100×100 source at a 10×10
        grid (cell_area=100) yields low_eff≈166 > 115 and high_eff≈216 > 180,
        so gradients stay on the smooth-mean path instead of snapping.
        LOW_eff < HIGH_eff must hold at every grid size (LOW rises faster but
        starts lower). The golden anchor (52×52 grid on the 128×128 fixture,
        cell_area≈6.06=REF) stays at scale=1.0 → output byte-identical.
        """
        # Big grid: 128×128 source at 128×128 grid → cell_area = 1.0.
        _edge_cfg = EdgeConfig()
        big_low = min(
            _edge_cfg.mean_edge_range_low * _edge_scale(1.0, _MEAN_EDGE_SCALE_K_LOW),
            _MEAN_EDGE_MAX,
        )
        big_high = min(
            _edge_cfg.mean_edge_range_high * _edge_scale(1.0, _MEAN_EDGE_SCALE_K_HIGH),
            _MEAN_EDGE_MAX,
        )
        assert big_low < _edge_cfg.mean_edge_range_low
        assert big_high < _edge_cfg.mean_edge_range_high
        assert big_low < big_high

        # Small grid: 100×100 source at 10×10 grid → cell_area = 100.0.
        small_low = min(
            _edge_cfg.mean_edge_range_low * _edge_scale(100.0, _MEAN_EDGE_SCALE_K_LOW),
            _MEAN_EDGE_MAX,
        )
        small_high = min(
            _edge_cfg.mean_edge_range_high * _edge_scale(100.0, _MEAN_EDGE_SCALE_K_HIGH),
            _MEAN_EDGE_MAX,
        )
        assert small_low > _edge_cfg.mean_edge_range_low
        assert small_high > _edge_cfg.mean_edge_range_high
        assert small_low < small_high

        # Golden anchor: (128/52)² = 6.059 ≈ REF → scale ≈ 1.0 (both exponents).
        assert _edge_scale(
            (128.0 / 52.0) ** 2, _MEAN_EDGE_SCALE_K_LOW,
        ) == pytest.approx(1.0, abs=1e-3)
        assert _edge_scale(
            (128.0 / 52.0) ** 2, _MEAN_EDGE_SCALE_K_HIGH,
        ) == pytest.approx(1.0, abs=1e-3)

    def test_mean_edge_branch_flips_between_grid_sizes(self, tmp_path):
        """Same checkerboard: big grid → dominant, tiny grid → mean blend.

        Every cell region of the 2×2 tile (3 black + 1 red) has red range
        A=140. On a 100×100 grid (cell_area=4 → scale_low≈0.947 → low_eff≈109,
        scale_high≈0.973 → high_eff≈175) A=140 lands in the ambiguous zone
        (109 < 140 ≤ 175); the red-vs-black ΔE00 is huge, so the refined test
        picks the dominant colour → black (0,0,0). On a 10×10 grid
        (cell_area=400 → scale_low≈1.725 → low_eff≈198, scale_high≈1.313 →
        high_eff≈236) A=140 stays at/below the smooth band → gamma-corrected
        linear-space mean of the 3:1 black:red cell → red≈72, never snapped
        to the boundary colour. The SAME synthetic image flips branches
        between grid sizes (dominant on big, mean on tiny).
        """
        tile = np.array([
            [[0, 0, 0], [0, 0, 0]],
            [[0, 0, 0], [140, 0, 0]],
        ], dtype=np.uint8)
        img = Image.fromarray(np.tile(tile, (100, 100, 1)), "RGB")
        img.save(tmp_path / "checker.png")

        big_grid, _ = _load_and_prepare(tmp_path / "checker.png", 100, 100, cell_mode="mean")
        tiny_grid, _ = _load_and_prepare(tmp_path / "checker.png", 10, 10, cell_mode="mean")

        # Big grid: every 2×2 cell is an ambiguous-but-real boundary (ΔE00
        # red-vs-black ≫ 15) → dominant colour → black (0,0,0), not a blend.
        # (Candidates are only recorded on the a_range > high_eff path, so
        # the stroke-tracking post-pass does not fire here.)
        np.testing.assert_array_equal(
            big_grid, np.zeros((100, 100, 3), dtype=np.uint8),
        )
        # Tiny grid: every 20×20 cell is smooth under the higher thresholds → mean.
        assert np.all(tiny_grid == tiny_grid[0, 0]), (
            "all tiny-grid cells should be identical"
        )
        red = int(tiny_grid[0, 0, 0])
        assert red == 72, (
            f"expected linear-space blend of 0/140 (3:1 black:red) → red=72, got red={red}"
        )
        assert np.all(tiny_grid[:, :, 1:] == 0)

    def test_mean_with_dither_equals_mean_without_dither(self, caplog):
        """Dither is auto-disabled in mean mode (with a warning)."""
        plain = convert(
            str(FIXTURES / "sample_photo.png"), width=10, height=10,
            cell_mode="mean", dither=False,
        )
        with caplog.at_level(logging.WARNING, logger="beadstudio.core.convert"):
            dithered = convert(
                str(FIXTURES / "sample_photo.png"), width=10, height=10,
                cell_mode="mean", dither=True,
            )
        assert dithered["codes"] == plain["codes"]
        assert dithered["indices"] == plain["indices"]
        assert any("抖动已自动禁用" in r.getMessage() for r in caplog.records), (
            "expected a warning that dither was auto-disabled in mean mode"
        )

    def test_dither_still_applies_in_dominant_mode(self):
        """The dither gate is mean-specific: dominant mode still dithers."""
        plain = convert(
            str(FIXTURES / "sample_photo.png"), width=10, height=10,
            cell_mode="dominant", dither=False,
        )
        dithered = convert(
            str(FIXTURES / "sample_photo.png"), width=10, height=10,
            cell_mode="dominant", dither=True,
        )
        assert dithered["indices"] != plain["indices"]

    def test_mean_merge_preserves_contour(self, tmp_path):
        """Red bg + subtle gradient + thin black contour.

        Mean mode (tolerance merge) treats the black line as a structural
        boundary and preserves it, while dominant mode's most-frequent merge
        absorbs it into the red background.
        """
        h = w = 15
        arr = np.zeros((h, w, 3), dtype=np.uint8)
        for x in range(w):  # subtle red-family gradient (lighting variation)
            arr[:, x] = (int(209 - x * 2), int(67 - x * 0.5), int(55 - x * 0.5))
        arr[3:6, 7] = (0, 0, 0)  # thin black contour, 3 cells
        img = Image.fromarray(arr, "RGB")
        img.save(tmp_path / "contour.png")

        mean_res = convert(
            str(tmp_path / "contour.png"), width=15, height=15,
            cell_mode="mean", cleanup=True,
        )
        dom_res = convert(
            str(tmp_path / "contour.png"), width=15, height=15,
            cell_mode="dominant", cleanup=True,
        )

        def luminance(code, result):
            for entry in result["legend"]:
                if entry["code"] == code:
                    return sum(entry["rgb"]) / 3
            return None

        mean_lums = [luminance(mean_res["codes"][y][7], mean_res) for y in range(3, 6)]
        dom_lums = [luminance(dom_res["codes"][y][7], dom_res) for y in range(3, 6)]
        assert all(lum is not None and lum < 60 for lum in mean_lums), (
            f"mean mode lost the black contour: {mean_lums}"
        )
        assert all(lum is not None and lum > 100 for lum in dom_lums), (
            f"dominant mode kept the contour (should absorb it): {dom_lums}"
        )

    def test_stroke_thin_line_preserved(self, tmp_path, monkeypatch):
        """A thin vertical white line on red survives as a continuous column.

        Cells straddling the line have white as a significant minority; the
        dominant (<50% majority) pick would swallow it and scatter the line.
        The stroke-tracking post-pass traces those candidate cells into a
        full-height chain (>= 3 cells) and repaints the chain with the line
        color — the output must contain a full-height white column.
        """
        h = w = 100
        arr = np.full((h, w, 3), (200, 30, 30), dtype=np.uint8)
        arr[:, 49:52] = (255, 255, 255)  # 3-px vertical white line
        img = Image.fromarray(arr, "RGB")
        img.save(tmp_path / "line.png")

        for grid in (33, 50):
            out, _ = _load_and_prepare(tmp_path / "line.png", grid, grid, cell_mode="mean")
            white = np.all(out == 255, axis=2)
            full_cols = [c for c in range(grid) if bool(np.all(white[:, c]))]
            assert full_cols, f"line broken: no full-height white column at grid {grid}"
            # The 3-px line spans ~1-3 grid columns at these scales.
            assert len(full_cols) <= 3, (
                f"line blown up to {len(full_cols)} columns at grid {grid}"
            )

        # REAL feature proof: a 1-px line has no majority column at grid 33 —
        # without the stroke pass the line vanishes entirely; with it, the
        # candidate column becomes one full-height white column.
        thin = np.full((h, w, 3), (200, 30, 30), dtype=np.uint8)
        thin[:, 50] = (255, 255, 255)  # 1-px line
        img = Image.fromarray(thin, "RGB")
        img.save(tmp_path / "thin_line.png")

        out, _ = _load_and_prepare(tmp_path / "thin_line.png", 33, 33, cell_mode="mean")
        white = np.all(out == 255, axis=2)
        assert int(white.sum()) == 33, (
            f"1-px line not preserved: {int(white.sum())} white cells"
        )
        assert any(bool(np.all(white[:, c])) for c in range(33)), (
            "1-px line not contiguous"
        )

        import beadstudio.core.convert as convert_mod
        # The stroke gates now live in EdgeConfig, so "disable the stroke
        # pass" = an EdgeConfig override with every gate maxed; the internal
        # _STROKE_LINE_DELTAE stays a module-level constant.
        monkeypatch.setattr(convert_mod, "_STROKE_LINE_DELTAE", 10 ** 9)
        out_no_stroke, _ = _load_and_prepare(
            tmp_path / "thin_line.png", 33, 33, cell_mode="mean",
            edge_config=EdgeConfig(
                stroke_min_fraction=1.0, stroke_min_deltae=50.0,
                stroke_min_length=10 ** 9,
            ),
        )
        assert not np.any(np.all(out_no_stroke == 255, axis=2)), (
            "without the stroke pass the 1-px line should be swallowed"
        )

    def test_stroke_noise_not_promoted(self, tmp_path):
        """Isolated white blobs on red must NOT be promoted to lines.

        Each blob yields isolated candidate cells (chains < 3 cells), so the
        stroke-tracking post-pass must leave them as the dominant red — no
        full-height white column, and essentially no white cells at all.
        """
        h = w = 100
        arr = np.full((h, w, 3), (200, 30, 30), dtype=np.uint8)
        # 3 isolated 2×2 white blobs, far apart → no 3-cell chain.
        for y0, x0 in ((10, 10), (55, 55), (25, 75)):
            arr[y0:y0 + 2, x0:x0 + 2] = (255, 255, 255)
        img = Image.fromarray(arr, "RGB")
        img.save(tmp_path / "noise.png")

        out, _ = _load_and_prepare(tmp_path / "noise.png", 33, 33, cell_mode="mean")
        white = np.all(out == 255, axis=2)
        assert not any(bool(np.all(white[:, c])) for c in range(33)), (
            "noise promoted to a full-height white column"
        )
        assert int(white.sum()) < 5, (
            f"noise promoted to {int(white.sum())} white cells"
        )

    def test_stroke_gradient_band_unaffected(self, tmp_path, monkeypatch):
        """Smooth gradients must not be treated as strokes.

        Gradient cells have small per-channel ranges and stay on the smooth-
        mean path, so they never reach the dominant branch where candidates
        are recorded — the stroke post-pass must leave the output
        byte-identical to a run with the stroke constants disabled, and must
        not produce a fake white column.
        """
        h = w = 100
        arr = np.zeros((h, w, 3), dtype=np.uint8)
        for x in range(w):
            arr[:, x] = (int(200 + x * 0.55), 30, 30)  # smooth 200→255 red gradient
        img = Image.fromarray(arr, "RGB")
        img.save(tmp_path / "grad.png")

        out, _ = _load_and_prepare(tmp_path / "grad.png", 33, 33, cell_mode="mean")

        import beadstudio.core.convert as convert_mod
        # Stroke gates live in EdgeConfig → disable the pass via an override.
        monkeypatch.setattr(convert_mod, "_STROKE_LINE_DELTAE", 10 ** 9)
        out_disabled, _ = _load_and_prepare(
            tmp_path / "grad.png", 33, 33, cell_mode="mean",
            edge_config=EdgeConfig(
                stroke_min_fraction=1.0, stroke_min_deltae=50.0,
                stroke_min_length=10 ** 9,
            ),
        )
        np.testing.assert_array_equal(out, out_disabled)

        white = np.all(out == 255, axis=2)
        assert not any(bool(np.all(white[:, c])) for c in range(33)), (
            "gradient produced a fake full-height white column"
        )

    def test_stroke_thick_line_dominant_not_erased(self, tmp_path):
        """A THICK white vertical line (white becomes the DOMINANT color) survives.

        The 8-px line on a 200×200 source at a 40×40 grid (5-px cells) covers
        ~80% of its cells, so white is the most-frequent (dominant) color and
        red becomes the second color. The stroke pass must still produce a
        continuous white column: the chain's line color is the color shared
        across the chain that is FARTHEST from the red global background —
        white — so the cells that already output white stay white instead of
        being repainted red (the pre-fix bug erased the line entirely).
        """
        h = w = 200
        arr = np.full((h, w, 3), (200, 30, 30), dtype=np.uint8)
        arr[:, 96:104] = (255, 255, 255)  # 8-px thick vertical white line
        img = Image.fromarray(arr, "RGB")
        img.save(tmp_path / "thick_line.png")

        grid = 40
        out, _ = _load_and_prepare(tmp_path / "thick_line.png", grid, grid, cell_mode="mean")
        white = np.all(out == 255, axis=2)
        full_cols = [c for c in range(grid) if bool(np.all(white[:, c]))]
        assert full_cols, (
            f"thick white line erased to red: no full-height white column"
        )
        assert len(full_cols) <= 3, (
            f"thick line blown up to {len(full_cols)} columns"
        )

    def test_stroke_diagonal_line_preserved(self, tmp_path):
        """A thin white DIAGONAL band survives the stroke pass (not erased).

        Along the diagonal the cells alternate between white-dominant and
        red-dominant (the line flips which side is the majority). The stroke
        pass must trace the whole band as ONE chain (cells join when they
        share the white line color, whichever side it sits on) and repaint
        every chain cell with white — the diagonal is preserved instead of
        being erased to red. Minor gaps (cells where the band covers <10%)
        are tolerated.
        """
        h = w = 200
        arr = np.full((h, w, 3), (200, 30, 30), dtype=np.uint8)
        for y in range(h):  # 3-px white diagonal band y = x ± 1
            for x in (y - 1, y, y + 1):
                if 0 <= x < w:
                    arr[y, x] = (255, 255, 255)
        img = Image.fromarray(arr, "RGB")
        img.save(tmp_path / "diag.png")

        grid = 40
        out, _ = _load_and_prepare(tmp_path / "diag.png", grid, grid, cell_mode="mean")
        white = np.all(out == 255, axis=2)

        rows_with_white = [y for y in range(grid) if bool(np.any(white[y]))]
        assert len(rows_with_white) >= int(grid * 0.8), (
            f"diagonal erased: only {len(rows_with_white)}/{grid} rows have a white cell"
        )
        # The diagonal crosses the whole image; inside the middle ~2/3 every
        # row must keep at least one white cell (no all-red gap).
        lo, hi = int(grid * 0.15), int(grid * 0.85)
        assert all(np.any(white[y]) for y in range(lo, hi)), (
            "diagonal region contains a fully-red row (line erased)"
        )

    def test_stroke_jpeg_shades_line_preserved(self, tmp_path):
        """A line smeared across near-identical JPEG shades survives (cluster-aware).

        Real photos spread a thin line's color over many near-white shades
        (anti-aliasing/JPEG), so no SINGLE distinct RGB reaches 12% of a line
        cell even though the line's TOTAL coverage does. The per-single-RGB
        candidate gate then finds no candidate and swallows the line. The
        color-cluster gate sums the near-identical shades into one "second
        cluster", so the total passes and the stroke pass repaints the whole
        column.
        """
        import beadstudio.core.convert as convert_mod

        h = w = 1024
        arr = np.full((h, w, 3), (200, 30, 30), dtype=np.uint8)
        shades = np.array([
            (255, 255, 255),
            (252, 254, 253),
            (253, 255, 250),
            (250, 255, 254),
        ], dtype=np.uint8)
        # 2-px vertical white line at x=510,511. Grid 128 over 1024 → 8-px
        # cells, so the line covers 2/8 = 25% of every line cell. The pixel
        # color cycles through the 4 near-white shades → each single shade is
        # only 4/64 ≈ 6.25% of a line cell (far below the 12% gate), but the
        # 4 shades TOGETHER total the 25% the line actually covers.
        for y in range(h):
            arr[y, 510] = shades[y % 4]
            arr[y, 511] = shades[(y + 1) % 4]
        img = Image.fromarray(arr, "RGB")
        img.save(tmp_path / "jpeg_shades.png")

        # UNIT proof of the mechanism: in a line cell the most-frequent single
        # shade fails the fraction gate, but the near-white CLUSTER (all four
        # shades summed) passes it, and its rep is far from the red.
        cell = arr[0:8, 504:512]  # grid cell (0, 63), which contains x=510,511
        _, _, single_frac = convert_mod._top2_colors(cell.astype(np.uint8))
        dom, sec, _, cluster_frac = convert_mod._top_clusters(cell.astype(np.uint8))
        assert single_frac < EdgeConfig().stroke_min_fraction, (
            "synthetic setup broken: a single shade already passes the gate"
        )
        assert cluster_frac >= EdgeConfig().stroke_min_fraction, (
            "cluster fraction failed to aggregate the near-white shades"
        )
        assert convert_mod._deltae00_between(dom, sec) >= EdgeConfig().stroke_min_deltae

        # END-TO-END: the full line column is repainted with the chain's line
        # color (a near-white shade), so every row keeps its white cell.
        grid = 128
        out, _ = _load_and_prepare(tmp_path / "jpeg_shades.png", grid, grid, cell_mode="mean")
        near_white = np.all(out > 240, axis=2)
        full_cols = [c for c in range(grid) if bool(np.all(near_white[:, c]))]
        assert full_cols, "JPEG-shades line not preserved: no full-height near-white column"
        assert len(full_cols) <= 2, (
            f"JPEG-shades line blown up to {len(full_cols)} columns"
        )

        # The line color actually output is one of the near-white shades (not
        # the red background): column cells were repainted by the stroke pass.
        col = full_cols[0]
        cell_colors = {tuple(out[y, col]) for y in range(grid)}
        assert all(min(c) > 240 for c in cell_colors), (
            f"line column repainted with non-white color(s): {cell_colors}"
        )

    def test_stroke_jpeg_spread_many_shades_preserved(self, tmp_path):
        """A line spread over MANY near-white shades survives (no top-N truncation).

        Regression for the real-image gap: JPEG/anti-aliasing spreads a thin
        white line's pixels across HUNDREDS of distinct near-white shades, and
        the background's own JPEG shades are individually more frequent than a
        single line shade — so the old top-12 color truncation examined only
        the most-frequent dozen colors of a cell, captured 0-6.7% of the white
        pixels, and failed the 10% second-cluster gate. Clustering over ALL
        distinct colors sums the full white population into one second
        cluster, so the gate passes and the stroke pass traces a continuous
        column.
        """
        import beadstudio.core.convert as convert_mod

        h = w = 1024
        arr = np.full((h, w, 3), (200, 30, 30), dtype=np.uint8)
        # The red background itself has shade spread — 8 near-identical red
        # shades cycling per row, exactly like a JPEG photo. Each red shade is
        # more frequent than a single near-white line shade, so the top-12
        # slots are consumed by the background and the line's white pixels are
        # (almost all) truncated by the old top-12 cap.
        red_shades = np.array([
            (200 + (i % 4), 30 + (i // 4), 30) for i in range(8)
        ], dtype=np.uint8)
        for y in range(h):
            arr[y] = red_shades[y % 8]
        # 50 handcrafted near-white shades, differing only in the low digits
        # (all within ΔE00 ~10 of pure white and of each other).
        white_shades = np.array([
            (255 - (i % 2), 255 - ((i // 2) % 5), 255 - ((i // 10) % 5))
            for i in range(50)
        ], dtype=np.uint8)
        # 2-px vertical white line at x=510,511. Grid 128 over 1024 → 8-px
        # cells; the line covers 2/8 = 25% of every line cell, spread over 16
        # distinct near-white shades per cell (each pixel a different shade →
        # each single shade is only ~1.6% of the cell, far below the gate).
        for y in range(h):
            arr[y, 510] = white_shades[(y * 2) % 50]
            arr[y, 511] = white_shades[(y * 2 + 1) % 50]
        img = Image.fromarray(arr, "RGB")
        img.save(tmp_path / "many_shades_line.png")

        # UNIT proof of the failure mode: a line cell holds 48 red px over 8
        # red shades (6 px each) + 16 white px over 16 distinct shades (1 px
        # each). The top-12 cap grabs the 8 red shades + only 4 white shades,
        # so the second-cluster fraction sits far below the 10% gate...
        cell = arr[0:8, 504:512]  # grid cell (0, 63), which contains x=510,511
        _dom, _sec, _dom_frac, sec12 = convert_mod._top_clusters(
            cell.astype(np.uint8), top_n=12
        )
        assert sec12 < EdgeConfig().stroke_min_fraction, (
            "test premise broken: top-12 truncation already passes the gate "
            f"(second fraction {sec12:.3f})"
        )
        # ...while the full greedy clustering (default, no harmful
        # truncation) sums ALL 16 white shades into one second cluster (~25%)
        # whose rep is far from the red dominant.
        dom, sec, _dom_frac, sec_all = convert_mod._top_clusters(
            cell.astype(np.uint8)
        )
        assert sec_all >= EdgeConfig().stroke_min_fraction, (
            f"greedy clustering lost the white population: {sec_all:.3f}"
        )
        assert convert_mod._deltae00_between(dom, sec) >= EdgeConfig().stroke_min_deltae

        # END-TO-END: the line column is traced and repainted with the chain's
        # line color, so >= 95% of the rows keep a near-white cell in one
        # contiguous column region.
        grid = 128
        out, _ = _load_and_prepare(
            tmp_path / "many_shades_line.png", grid, grid, cell_mode="mean"
        )
        near_white = np.all(out > 240, axis=2)
        best = max(int(near_white[:, c].sum()) for c in range(grid))
        assert best >= int(grid * 0.95), (
            f"many-shade line lost: best column has {best}/{grid} near-white rows"
        )

    def test_stroke_line_in_smooth_range_branch_recovered(self, tmp_path, monkeypatch):
        """A thin line whose cells sit at the smooth/ambiguous boundary IS recovered.

        Plan A tuning: on a coarse grid (30 wide over a 960×1938 source,
        cell_area≈1017) the edge-aware thresholds rise to low_eff≈223.8 at
        LOW=115 (was ≈233.6 at LOW=120), while a white line on red
        (200,30,30) spans a_range=225 (the R channel moves just 200→255;
        G/B span 30→255). The line cells therefore leave the SMOOTH-INTERIOR
        branch and enter the ambiguous zone (223.8 < 225 ≤ 251.1) — and the
        stroke candidate pre-gate (a_range >= max(low_eff,
        _STROKE_A_RANGE_MIN) = 223.8) now ADMITS them: at LOW=120 the gate
        sat at 233.6 > 225 and the white line was swallowed (the old test
        asserted exactly that non-promotion). Plan A deliberately pulls the
        line back into the candidate zone so the white line is recovered as
        a continuous column — the stroke pass repaints the chain and the
        output DIFFERS from a stroke-disabled run (the old byte-identical
        contract is inverted).
        """
        h, w = 1938, 960
        arr = np.full((h, w, 3), (200, 30, 30), dtype=np.uint8)
        arr[:, 480:484] = (255, 255, 255)  # 4-px vertical white line at x=480
        img = Image.fromarray(arr, "RGB")
        img.save(tmp_path / "smooth_line.png")

        # Same geometry as the real white-line image: width 30 → derived
        # height 61, cell_area ≈ 1017 → low_eff ≈ 223.8 → line cells
        # (a_range=225) sit in the ambiguous zone, ABOVE the smooth branch
        # and ABOVE the adaptive pre-gate. Guard the premise so a threshold
        # change is loud.
        import beadstudio.core.convert as convert_mod
        cell_area = (1938.0 / 61.0) * (960.0 / 30.0)
        scale_low = (
            cell_area / convert_mod._MEAN_EDGE_REF_CELL_AREA
        ) ** convert_mod._MEAN_EDGE_SCALE_K_LOW
        scale_high = (
            cell_area / convert_mod._MEAN_EDGE_REF_CELL_AREA
        ) ** convert_mod._MEAN_EDGE_SCALE_K_HIGH
        low_eff = min(
            EdgeConfig().mean_edge_range_low * scale_low, convert_mod._MEAN_EDGE_MAX,
        )
        high_eff = min(
            EdgeConfig().mean_edge_range_high * scale_high, convert_mod._MEAN_EDGE_MAX,
        )
        assert 225 > low_eff, (
            "test premise broken: line cells are back in the smooth branch "
            "(smooth-interior cells are never stroke candidates)"
        )
        assert 225 <= high_eff, (
            "test premise broken: line cells exceed HIGH — the refined Lab "
            "test no longer runs and the ambiguous-zone premise is gone"
        )
        gate = max(low_eff, convert_mod._STROKE_A_RANGE_MIN)
        assert 225 >= gate, (
            "test premise broken: the adaptive pre-gate no longer admits "
            "the line cells"
        )

        out, _ = _load_and_prepare(tmp_path / "smooth_line.png", 30, 61, cell_mode="mean")

        # Stroke gates live in EdgeConfig → disable the pass via an override.
        monkeypatch.setattr(convert_mod, "_STROKE_LINE_DELTAE", 10 ** 9)
        out_disabled, _ = _load_and_prepare(
            tmp_path / "smooth_line.png", 30, 61, cell_mode="mean",
            edge_config=EdgeConfig(
                stroke_min_fraction=1.0, stroke_min_deltae=50.0,
                stroke_min_length=10 ** 9,
            ),
        )
        repainted = int(np.count_nonzero(np.any(out != out_disabled, axis=2)))
        assert repainted >= 45, (
            f"line column not repainted by the stroke pass: only {repainted}/61 "
            "cells differ from the stroke-disabled run"
        )

        white = np.all(out >= 200, axis=2)  # near-white: min RGB >= 200
        assert int(white.sum()) >= 45, (
            f"white line not recovered: {int(white.sum())}/61 near-white cells "
            "(Plan A contract: >= 45)"
        )
        col = white[:, 15]
        runs = best = 0
        for v in col:
            runs = runs + 1 if v else 0
            best = max(best, runs)
        assert best >= 30, (
            f"white line fragmented: max vertical run {best} (Plan A contract: >= 30)"
        )
        assert any(bool(np.all(white[:, c])) for c in range(30)), (
            "white line not recovered to a full-height white column"
        )
        # Observed on this synthetic (straight 4-px line): 61/61 near-white
        # cells in column 15, max run 61, 61 repainted cells.

    def test_stroke_photo_texture_not_promoted(self, tmp_path, monkeypatch):
        """Photo-like texture (gradient + two-tone noise patches) must NOT be strokes.

        Regression for the real-photo false positives: on a 1000×750 source at
        width 30 (grid 30×23, cell_area≈1087 — the exact geometry of the
        failing real photo) the adaptive smooth threshold is low_eff≈225.7.
        Two-tone texture patches (blue+tan, ΔE00 ≫ 35, ~50/50 mix — a strong
        second cluster) span only a_range≈195, so the mean edge-detector
        classifies them SMOOTH INTERIOR and the adaptive pre-gate
        (a_range >= max(low_eff, _STROKE_A_RANGE_MIN) = 225.7) excludes them.
        The OLD fixed 180 gate admitted exactly such cells — that is how 77%
        of the false candidates on the real photo came from smooth-interior
        cells — and their chains repainted whole gradient areas. With the
        adaptive gate the stroke pass must repaint nothing: the output is
        byte-identical to a stroke-disabled run, far below the 5% budget.
        """
        import beadstudio.core.convert as convert_mod

        h, w = 1000, 750
        rng = np.random.default_rng(42)
        arr = np.zeros((h, w, 3), dtype=np.uint8)
        # Smooth vertical gradient (mid-tone, photo-like lighting).
        for y in range(h):
            t = y / h
            arr[y] = (
                int(100 + 100 * t),
                int(120 + 60 * t),
                int(110 + 50 * t),
            )
        # Two-tone texture patches (simulated photo noise): 30×30 areas of a
        # random 50/50 blue+tan mix, scattered on a jittered lattice. The two
        # tones are perceptually far apart (ΔE00 ≫ 35) but the mix is a
        # regular pattern, not a line — and spans only a_range ≈ 195.
        blue = np.array((20, 80, 230), dtype=np.uint8)
        tan = np.array((215, 180, 120), dtype=np.uint8)
        for cy in range(50, h - 50, 55):
            for cx in range(50, w - 50, 55):
                if rng.random() > 0.85:
                    continue  # ~15% fill: keeps ~35 patches over the image
                y0 = max(0, min(h - 30, int(cy + rng.integers(-20, 21))))
                x0 = max(0, min(w - 30, int(cx + rng.integers(-20, 21))))
                patch = np.where(
                    rng.random((30, 30, 1)) < 0.5, blue, tan
                ).astype(np.uint8)
                arr[y0:y0 + 30, x0:x0 + 30] = patch
        img = Image.fromarray(arr, "RGB")
        img.save(tmp_path / "photo_texture.png")

        # PREMISE GUARD: some patch cells must clear EVERY old gate (fixed
        # 180 pre-gate, 10% fraction, ΔE25) — so the test discriminates: the
        # old code promoted them, the new code must not. And EVERY cell's
        # a_range must stay below the adaptive low_eff, so the new gate
        # excludes all of them (0 candidates → 0 repaints).
        cell_h, cell_w = h / 23.0, w / 30.0
        low_eff = min(
            EdgeConfig().mean_edge_range_low
            * (cell_h * cell_w / convert_mod._MEAN_EDGE_REF_CELL_AREA)
            ** convert_mod._MEAN_EDGE_SCALE_K_LOW,
            convert_mod._MEAN_EDGE_MAX,
        )
        old_gate_cells = 0
        max_a_range = 0
        for gy in range(23):
            for gx in range(30):
                y0, x0 = int(gy * cell_h), int(gx * cell_w)
                y1, x1 = max(int((gy + 1) * cell_h), y0 + 1), max(int((gx + 1) * cell_w), x0 + 1)
                reg = arr[y0:y1, x0:x1].reshape(-1, 3)
                a_range = int((reg.max(axis=0) - reg.min(axis=0)).max())
                max_a_range = max(max_a_range, a_range)
                if a_range < convert_mod._STROKE_A_RANGE_MIN:
                    continue
                dom, sec, _df, second_frac = convert_mod._top_clusters(reg)
                if (
                    second_frac >= EdgeConfig().stroke_min_fraction
                    and convert_mod._deltae00_between(dom, sec) >= EdgeConfig().stroke_min_deltae
                ):
                    old_gate_cells += 1
        assert old_gate_cells >= 5, (
            "premise broken: too few texture cells clear the OLD gates "
            f"({old_gate_cells} cells) — the test no longer discriminates"
        )
        assert max_a_range < low_eff, (
            "premise broken: some cell exceeds the adaptive low_eff — texture "
            f"cells are no longer smooth interior (max a_range={max_a_range}, "
            f"low_eff={low_eff:.1f})"
        )

        out, _ = _load_and_prepare(tmp_path / "photo_texture.png", 30, 23, cell_mode="mean")
        # Stroke gates live in EdgeConfig → disable the pass via an override.
        monkeypatch.setattr(convert_mod, "_STROKE_LINE_DELTAE", 10 ** 9)
        out_disabled, _ = _load_and_prepare(
            tmp_path / "photo_texture.png", 30, 23, cell_mode="mean",
            edge_config=EdgeConfig(
                stroke_min_fraction=1.0, stroke_min_deltae=50.0,
                stroke_min_length=10 ** 9,
            ),
        )
        repainted = int(np.count_nonzero(np.any(out != out_disabled, axis=2)))
        budget = int(30 * 23 * 0.05)
        assert repainted < budget, (
            f"photo texture promoted to strokes: {repainted}/{30 * 23} cells "
            f"repainted (budget < {budget})"
        )

    def test_stroke_dark_line_color_not_repainted(self, tmp_path, monkeypatch):
        """A chain mixing a light line with an adjacent dark stripe must NOT be
        repainted with the dark color (BLACK-EDGE artifact, 黑边).

        The chain crosses cells that contain BOTH the white line and a black
        stripe (mid-gray background so white and black are both far enough
        from it to survive the background-near restriction). The dark color is
        FARTHEST from the mid-gray background, so the plain vote (old
        behavior) picks black and repaints every chain cell black. The dark
        exclusion (_STROKE_DARK_MAX) bars near-black colors from the vote —
        the chain falls back to white, leaving no dark cells.
        """
        import beadstudio.core.convert as convert_mod

        h = w = 100
        arr = np.full((h, w, 3), (150, 150, 150), dtype=np.uint8)
        arr[:, 8:10] = (255, 255, 255)  # white vertical line (2 px)
        arr[:, 10:12] = (0, 0, 0)       # adjacent black stripe (2 px)
        img = Image.fromarray(arr, "RGB")
        img.save(tmp_path / "light_line_dark_stripe.png")

        # NEW behavior (default _STROKE_DARK_MAX=80): black is excluded from
        # the line-vote, the chain is repainted white — zero dark cells.
        out, _ = _load_and_prepare(
            tmp_path / "light_line_dark_stripe.png", 25, 25, cell_mode="mean",
        )
        dark = int(np.count_nonzero(np.all(out <= 80, axis=2)))
        assert dark == 0, (
            f"black-edge repaint: {dark} cells painted with a dark color"
        )

        # OLD behavior (_STROKE_DARK_MAX=0 disables the exclusion): the same
        # chain votes black (farthest from the mid-gray background) and
        # repaints the whole column black. This premise check proves the test
        # really discriminates against the old code path.
        monkeypatch.setattr(convert_mod, "_STROKE_DARK_MAX", 0)
        out_old, _ = _load_and_prepare(
            tmp_path / "light_line_dark_stripe.png", 25, 25, cell_mode="mean",
        )
        dark_old = int(np.count_nonzero(np.all(out_old <= 80, axis=2)))
        assert dark_old >= 25, (
            f"premise broken: old behavior repainted only {dark_old} dark cells"
        )

    def test_stroke_black_line_fallback(self, tmp_path, monkeypatch):
        """A genuinely black-on-white image still recovers its black line.

        Every candidate color on the chain is dark, so the dark exclusion
        would leave no vote candidates — the fallback restores the full list
        and the (legitimate) black line is repainted black. Without the stroke
        pass the 1-px line is swallowed entirely, proving the fallback path is
        what recovered it.
        """
        import beadstudio.core.convert as convert_mod

        h = w = 100
        arr = np.full((h, w, 3), (255, 255, 255), dtype=np.uint8)
        arr[:, 50] = (0, 0, 0)  # 1-px vertical black line
        img = Image.fromarray(arr, "RGB")
        img.save(tmp_path / "black_line.png")

        grid = 33
        out, _ = _load_and_prepare(tmp_path / "black_line.png", grid, grid, cell_mode="mean")
        black = np.all(out <= 40, axis=2)
        full_cols = [c for c in range(grid) if bool(np.all(black[:, c]))]
        assert full_cols, "black line lost: no full-height black column"
        assert len(full_cols) <= 3, (
            f"black line blown up to {len(full_cols)} columns"
        )

        # Without the stroke pass the 1-px line is swallowed (its boundary
        # cells output the dominant white), so the black column above can only
        # come from the fallback repaint. Stroke gates live in EdgeConfig →
        # disable the pass via an override.
        monkeypatch.setattr(convert_mod, "_STROKE_LINE_DELTAE", 10 ** 9)
        out_disabled, _ = _load_and_prepare(
            tmp_path / "black_line.png", grid, grid, cell_mode="mean",
            edge_config=EdgeConfig(
                stroke_min_fraction=1.0, stroke_min_deltae=50.0,
                stroke_min_length=10 ** 9,
            ),
        )
        assert not np.any(np.all(out_disabled <= 40, axis=2)), (
            "black column appears even without the stroke pass — "
            "test no longer discriminates"
        )


# ---------------------------------------------------------------------------
# Tolerance-aware region merge (_bfs_region_cleanup color_tolerance)
# ---------------------------------------------------------------------------

class TestToleranceRegionMerge:
    """color_tolerance merging: closest-neighbour selection + contour protection."""

    def test_dominant_merge_unchanged(self):
        """color_tolerance=0 reproduces the legacy most-frequent merge exactly."""
        indices = np.array([
            [0, 0, 0, 0, 0, 1, 1, 1, 1, 1],
            [0, 0, 0, 0, 0, 1, 1, 1, 1, 1],
            [0, 0, 0, 0, 2, 1, 1, 1, 1, 1],
            [0, 0, 0, 0, 2, 1, 1, 1, 1, 1],
            [0, 0, 0, 0, 0, 1, 1, 1, 1, 1],
            [0, 0, 0, 0, 0, 1, 1, 1, 1, 1],
            [0, 0, 0, 0, 0, 1, 1, 1, 1, 1],
        ], dtype=np.int32)
        active = np.ones(indices.shape, dtype=bool)
        legacy = _bfs_region_cleanup(indices, active, min_region_size=4)
        explicit = _bfs_region_cleanup(indices, active, min_region_size=4, color_tolerance=0.0)
        np.testing.assert_array_equal(legacy, explicit)
        # Legacy picks the most-frequent neighbour (index 0), not the closest (1).
        assert legacy[2, 4] == 0
        assert legacy[3, 4] == 0

    def test_merge_tolerance_respects_structure(self):
        """tolerance>0 merges to the closest in-tolerance neighbour (not the most
        frequent) and preserves regions whose every neighbour is far (contours)."""
        # Small fragment (index 2) between a big index-0 region (majority
        # neighbour) and a big index-1 region. In Lab, 2 is closest to 1.
        indices = np.array([
            [0, 0, 0, 0, 0, 1, 1, 1, 1, 1],
            [0, 0, 0, 0, 0, 1, 1, 1, 1, 1],
            [0, 0, 0, 0, 2, 1, 1, 1, 1, 1],
            [0, 0, 0, 0, 2, 1, 1, 1, 1, 1],
            [0, 0, 0, 0, 0, 1, 1, 1, 1, 1],
            [0, 0, 0, 0, 0, 1, 1, 1, 1, 1],
            [0, 0, 0, 0, 0, 1, 1, 1, 1, 1],
        ], dtype=np.int32)
        palette_lab = np.array([
            [80.0, 0.0, 0.0],   # 0: far from the fragment (ΔE 30)
            [51.0, 0.0, 0.0],   # 1: close to the fragment (ΔE 1)
            [50.0, 0.0, 0.0],   # 2: the small fragment
        ], dtype=np.float64)
        out = _bfs_region_cleanup(
            indices, np.ones(indices.shape, dtype=bool), min_region_size=4,
            color_tolerance=6.0, palette_lab=palette_lab,
        )
        # Closest in-tolerance neighbour wins → index 1, not the most frequent 0.
        assert out[2, 4] == 1
        assert out[3, 4] == 1

        # Protection rule: a small region whose nearest neighbour is farther than
        # tolerance is a structural boundary → preserved.
        contour = np.array([
            [0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 2, 2, 0, 0, 0, 0, 0],   # small fragment, ΔE 2 from 0
            [0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 1, 1, 1, 0, 0, 0, 0, 0],   # thin contour, ΔE 40 from 0/2
            [0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0],
        ], dtype=np.int32)
        palette_lab2 = np.array([
            [50.0, 0.0, 0.0],   # 0: red bg
            [10.0, 0.0, 0.0],   # 1: black-ish contour (ΔE 40)
            [52.0, 0.0, 0.0],   # 2: subtle-gradient fragment (ΔE 2)
        ], dtype=np.float64)
        out2 = _bfs_region_cleanup(
            contour, np.ones(contour.shape, dtype=bool), min_region_size=4,
            color_tolerance=6.0, palette_lab=palette_lab2,
        )
        # Fragment merged into the close background; the contour is untouched.
        assert out2[2, 2] == 0 and out2[2, 3] == 0
        assert out2[4, 1] == 1 and out2[4, 2] == 1 and out2[4, 3] == 1

    def test_adaptive_min_region_size_when_tolerance_enabled(self):
        """tolerance>0 overrides min_region_size with max(4, min(h,w)//10).

        A 3-cell region is kept when the caller asks for size 2 (legacy honours
        it) but merged when tolerance is enabled (adaptive size 4 for a 5×5 grid).
        """
        indices = np.array([
            [0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0],
            [0, 1, 1, 1, 0],
            [0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0],
        ], dtype=np.int32)
        active = np.ones(indices.shape, dtype=bool)
        palette_lab = np.array([[50.0, 0.0, 0.0], [52.0, 0.0, 0.0]], dtype=np.float64)
        out = _bfs_region_cleanup(
            indices, active, min_region_size=2,
            color_tolerance=6.0, palette_lab=palette_lab,
        )
        # Adaptive size max(4, 5//10)=4 overrides the caller's 2 → merges.
        assert np.all(out[2, 1:4] == 0)
        # Default (tolerance=0) honours the caller's size 2 → region kept.
        legacy = _bfs_region_cleanup(indices, active, min_region_size=2)
        np.testing.assert_array_equal(legacy[2, 1:4], np.array([1, 1, 1], dtype=np.int32))

    def test_tolerance_requires_palette_lab(self):
        """color_tolerance>0 without palette_lab must raise ValueError."""
        indices = np.array([[0, 1], [1, 0]], dtype=np.int32)
        active = np.ones((2, 2), dtype=bool)
        with pytest.raises(ValueError, match="palette_lab"):
            _bfs_region_cleanup(indices, active, min_region_size=4, color_tolerance=6.0)


# ---------------------------------------------------------------------------
# Determinism test
# ---------------------------------------------------------------------------

class TestDeterminism:
    """Same input twice → byte-identical output."""

    def test_deterministic_ciede2000(self):
        """CIEDE2000 conversion should be deterministic."""
        r1 = convert(str(FIXTURES / "sample_photo.png"), width=20, height=20, color_space="cie2000")
        r2 = convert(str(FIXTURES / "sample_photo.png"), width=20, height=20, color_space="cie2000")
        assert r1["codes"] == r2["codes"]
        assert r1["indices"] == r2["indices"]
        assert r1["empty_count"] == r2["empty_count"]
        assert r1["colors_used"] == r2["colors_used"]

    def test_deterministic_oklab(self):
        """OKLab conversion should be deterministic."""
        r1 = convert(str(FIXTURES / "sample_photo.png"), width=20, height=20, color_space="oklab")
        r2 = convert(str(FIXTURES / "sample_photo.png"), width=20, height=20, color_space="oklab")
        assert r1["codes"] == r2["codes"]
        assert r1["indices"] == r2["indices"]

    def test_deterministic_dithered(self):
        """Dithered conversion should be deterministic."""
        r1 = convert(str(FIXTURES / "sample_photo.png"), width=10, height=10, dither=True)
        r2 = convert(str(FIXTURES / "sample_photo.png"), width=10, height=10, dither=True)
        assert r1["codes"] == r2["codes"]
        assert r1["indices"] == r2["indices"]


# ---------------------------------------------------------------------------
# Golden test (byte-identical PNG output)
# ---------------------------------------------------------------------------

class TestGolden:
    """Golden file: byte-identical PNG output for sample_photo at 52×52."""

    def test_golden_photo_png_byte_identical(self):
        """Regenerated PNG must match tests/golden/photo.png byte-for-byte."""
        golden_path = GOLDEN / "photo.png"
        if not golden_path.exists():
            pytest.skip("Golden file tests/golden/photo.png not found—generate it first.")

        result = convert(
            str(FIXTURES / "sample_photo.png"),
            width=52, height=52,
            color_space="cie2000",
        )
        new_png = _render_to_png(result)

        with open(golden_path, "rb") as f:
            golden_png = f.read()

        assert new_png == golden_png, (
            "Golden PNG mismatch. The pipeline output differs from the committed golden file. "
            "If you intentionally changed the pipeline, regenerate the golden file and visual-verify."
        )


# ---------------------------------------------------------------------------
# Performance test (CIEDE2000 timing at 100×100 grid)
# ---------------------------------------------------------------------------

class TestPerformance:
    """Performance: 100×100 CIEDE2000 conversion. NOT a hard failure."""

    def test_ciede2000_perf_100x100(self):
        """Measure CIEDE2000 time for 100×100 grid; flag if >5s."""
        # Use a small fixture image but scale to 100×100
        start = time.perf_counter()
        result = convert(
            str(FIXTURES / "sample_photo.png"),
            width=100, height=100,
            color_space="cie2000",
        )
        elapsed = time.perf_counter() - start

        assert result["width"] == 100
        assert result["height"] == 100
        assert result["colors_used"] > 0

        if elapsed > 5.0:
            import sys
            print(f"PERF>5s: CIEDE2000 100x100 took {elapsed:.2f}s", file=sys.stderr)
            # NOT a hard failure — just flag it
