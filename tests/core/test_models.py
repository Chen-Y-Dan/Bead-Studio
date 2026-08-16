"""Tests for beadstudio.core.models — typed domain dataclasses."""

import numpy as np
import pytest

from beadstudio.core.models import BeadColor, EdgeConfig, Palette, Pattern


def _make_pattern() -> Pattern:
    """Small Pattern with tiny arrays, shaped like convert()'s dict output."""
    return Pattern(
        codes=(("A", "B"), (None, "C")),
        indices=((0, 1), (-1, 2)),
        width=2,
        height=2,
        empty_count=1,
        colors_used=3,
        legend=({"code": "A", "rgb": (255, 0, 0), "count": 1},),
        grid_rgb=np.zeros((2, 2, 3), dtype=np.uint8),
        active_mask=np.ones((2, 2), dtype=bool),
    )


# ---------------------------------------------------------------------------
# EdgeConfig
# ---------------------------------------------------------------------------

def test_edge_config_defaults_match_convert_constants():
    """EdgeConfig() defaults match the current convert.py constants.

    The values below are the CURRENT constants in convert.py
    (_MEAN_EDGE_RANGE_LOW=115, _MEAN_EDGE_RANGE_HIGH=180,
    _MEAN_EDGE_DELTAE_THRESHOLD=15.0, _STROKE_MIN_FRACTION=0.12,
    _STROKE_MIN_LENGTH=5, _STROKE_MIN_DELTAE=35.0). They are pinned as
    literals here because the convert.py constants will be deleted in W1b.
    """
    cfg = EdgeConfig()
    assert cfg.mean_edge_range_low == 115
    assert cfg.mean_edge_range_high == 180
    assert cfg.mean_edge_deltae_threshold == 15.0
    assert cfg.stroke_min_fraction == 0.12
    assert cfg.stroke_min_length == 5
    assert cfg.stroke_min_deltae == 35.0


def test_edge_config_validation():
    """Out-of-range/contradictory values raise ValueError (English message)."""
    with pytest.raises(ValueError, match="mean_edge_range_low must be less than"):
        EdgeConfig(mean_edge_range_low=180, mean_edge_range_high=115)
    with pytest.raises(ValueError, match="mean_edge_range_low must be in \\(0, 255\\]"):
        EdgeConfig(mean_edge_range_low=0)
    with pytest.raises(ValueError, match="mean_edge_range_high must be in \\(0, 255\\]"):
        EdgeConfig(mean_edge_range_high=256)
    with pytest.raises(ValueError, match="stroke_min_length must be >= 3"):
        EdgeConfig(stroke_min_length=2)
    with pytest.raises(ValueError, match="stroke_min_fraction must be in \\(0, 1\\]"):
        EdgeConfig(stroke_min_fraction=0)


def test_edge_config_as_dict():
    """as_dict() round-trips all 6 fields."""
    cfg = EdgeConfig(
        mean_edge_range_low=120,
        mean_edge_range_high=200,
        mean_edge_deltae_threshold=18.0,
        stroke_min_fraction=0.15,
        stroke_min_length=6,
        stroke_min_deltae=40.0,
    )
    d = cfg.as_dict()
    assert d == {
        "mean_edge_range_low": 120,
        "mean_edge_range_high": 200,
        "mean_edge_deltae_threshold": 18.0,
        "stroke_min_fraction": 0.15,
        "stroke_min_length": 6,
        "stroke_min_deltae": 40.0,
    }
    # Round-trip: defaults with overrides from the dict reconstruct an equal config.
    assert EdgeConfig(**d) == cfg
    assert EdgeConfig(**EdgeConfig().as_dict()) == EdgeConfig()


# ---------------------------------------------------------------------------
# Pattern: dict-compat shim + frozen semantics
# ---------------------------------------------------------------------------

def test_pattern_dict_compat():
    """Pattern behaves like a dict for the migration shim."""
    p = _make_pattern()
    assert p["codes"] == p.codes
    assert p["legend"] == p.legend
    assert list(p.keys()) == [
        "codes", "indices", "width", "height", "empty_count",
        "colors_used", "legend", "grid_rgb", "active_mask",
    ]
    assert len(list(p.keys())) == 9
    assert dict(p)["width"] == p.width
    assert {**p}["colors_used"] == p.colors_used
    assert p.get("empty_count") == p.empty_count
    # Missing-key fallback via get().
    assert p.get("no_such_key", "fallback") == "fallback"


def test_pattern_frozen_rejects_rebind():
    """frozen=True: field re-binding raises AttributeError."""
    p = _make_pattern()
    with pytest.raises(AttributeError):
        p.width = 99


def test_pattern_array_mutable_in_place():
    """numpy array fields stay mutable in place (documented non-deep-immutability)."""
    p = _make_pattern()
    p.grid_rgb[0, 0] = 5  # must NOT raise
    assert p.grid_rgb[0, 0].tolist() == [5, 5, 5]
    p.active_mask[0, 0] = False  # must NOT raise
    assert not p.active_mask[0, 0]


# ---------------------------------------------------------------------------
# BeadColor + Palette
# ---------------------------------------------------------------------------

def test_beadcolor_palette():
    """BeadColor and Palette construct and expose their fields."""
    red = BeadColor(code="80-15199", name="Dark Green", rgb=(0, 143, 83))
    assert red.code == "80-15199"
    assert red.name == "Dark Green"
    assert red.rgb == (0, 143, 83)

    palette = Palette(
        brand="perler",
        source="https://github.com/maxcleme/beadcolors",
        license="MIT",
        colors=(red,),
    )
    assert palette.brand == "perler"
    assert palette.source == "https://github.com/maxcleme/beadcolors"
    assert palette.license == "MIT"
    assert palette.colors == (red,)
    assert palette.colors[0].rgb == (0, 143, 83)

    # Both are frozen.
    with pytest.raises(AttributeError):
        red.code = "other"
    with pytest.raises(AttributeError):
        palette.brand = "hama"
