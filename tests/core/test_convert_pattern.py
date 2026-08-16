"""convert() returns a typed Pattern — dict-compat shim + new-field invariants.

The byte-identical golden PNG test (``test_golden_photo_png_byte_identical``
in test_convert.py) already proves the pipeline output is unchanged; these
tests pin the Pattern return type and the ``grid_rgb``/``active_mask`` fields.
"""

from pathlib import Path

import numpy as np

from beadstudio.core.convert import (
    _get_palette_codes,
    _get_palette_rgb,
    convert,
    nearest_indices,
)
from beadstudio.core.models import Pattern

FIXTURES = Path(__file__).resolve().parent / "fixtures"

GRID_W = 12
GRID_H = 12

PATTERN_KEYS = [
    "codes", "indices", "width", "height", "empty_count",
    "colors_used", "legend", "grid_rgb", "active_mask",
]


def _convert(**kw) -> Pattern:
    return convert(str(FIXTURES / "sample_photo.png"), width=GRID_W, height=GRID_H, **kw)


def test_convert_returns_pattern():
    """convert() returns a typed Pattern; the dict-compat shim still works."""
    result = _convert()
    assert isinstance(result, Pattern)
    # __getitem__ shim mirrors the attributes exactly.
    assert result["codes"] == result.codes
    assert result["width"] == result.width == GRID_W
    assert result["height"] == result.height == GRID_H
    # keys() covers all 9 Pattern fields.
    assert list(result.keys()) == PATTERN_KEYS
    # dict(result) and {**result} work through keys()+__getitem__.
    assert dict(result)["legend"] == result.legend
    assert {**result}["colors_used"] == result.colors_used
    # get() with and without fallback.
    assert result.get("empty_count") == result.empty_count
    assert result.get("no_such_key", "fallback") == "fallback"
    # `in result` membership.
    assert "codes" in result
    assert "no_such_key" not in result


def test_pattern_grid_rgb_matches_codes():
    """grid_rgb is the per-cell source color; codes are its nearest palette match.

    ``cleanup=False`` so indices are exactly the nearest palette index of each
    cell's grid_rgb (region-merging would legitimately diverge). The check runs
    in the SAME quantization color space the pipeline uses.
    """
    result = _convert(cleanup=False, dither=False)
    g = result.grid_rgb
    assert g.shape == (GRID_H, GRID_W, 3)
    assert g.dtype == np.uint8
    assert g.min() >= 0 and g.max() <= 255

    palette_rgb = _get_palette_rgb("perler")
    palette_codes = _get_palette_codes("perler")
    active = result.active_mask
    indices = np.array(result.indices)
    codes = result.codes

    # Inactive cells stay at -1; active cells are nearest-palette matches.
    assert indices[~active].tolist() == [-1] * int((~active).sum())
    if active.any():
        expected = nearest_indices(g[active], palette_rgb, color_space="cie2000")
        np.testing.assert_array_equal(indices[active], expected)
        # codes are the palette codes of the matched indices.
        for y, x in zip(*np.where(active)):
            assert codes[y][x] == palette_codes[int(indices[y, x])]

    # Legend is exactly the set of used colors, with 3-tuple sRGB entries.
    legend_codes = {e["code"] for e in result.legend}
    assert len(legend_codes) == len(result.legend) == result.colors_used
    assert all(isinstance(e["rgb"], tuple) and len(e["rgb"]) == 3 for e in result.legend)


def test_pattern_active_mask():
    """active_mask has the grid shape, bool dtype, and agrees with codes/indices."""
    result = _convert()
    m = result.active_mask
    assert m.shape == (GRID_H, GRID_W)
    assert m.dtype == np.bool_

    # non-None code exactly iff the cell is active.
    for y in range(GRID_H):
        for x in range(GRID_W):
            assert (result.codes[y][x] is not None) == bool(m[y, x])

    idx = np.array(result.indices)
    assert (idx[~m] == -1).all()
    assert (idx[m] >= 0).all()
