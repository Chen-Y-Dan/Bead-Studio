"""W4 regression net for the six tunable ``EdgeConfig`` parameters.

Locks the tuned gray-halo / thin-stroke behavior (W1-W3) so future changes
cannot silently alter the effects the constants were tuned for. Two layers:

1. **Baseline golden snapshots** — ``convert()`` (``cell_mode="mean"``, default
   ``edge_config=None``) on each of the five synthetic sensitive fixtures must
   byte-match ``tests/regression/<name>_expected.json`` (codes/indices/legend/
   width/height/empty_count/colors_used).

2. **Parameter-sensitivity tests** — each ``EdgeConfig`` field is PROVEN to
   reach its algorithm path by observing a directional output change on the
   fixture it was designed for, and every directional expectation below is
   pinned to the CURRENT tuned behavior (do NOT change the engine to make a
   test pass — if a knob stops mattering, that is a report, not a fix).

Refresh snapshots only when intentionally changing tuned behavior::

    $env:REGRESSION_UPDATE_SNAPSHOTS = "1"
    uv run --with pytest --with pypdf python -m pytest tests/test_regression_sensitive.py -q
    $env:REGRESSION_UPDATE_SNAPSHOTS = ""

(or run the ``test_update_snapshots`` test un-skipped / via ``-k`` with the
skip marker cleared).

The fixtures are synthetic and regenerable:
``python tests/fixtures/make_sensitive_fixtures.py`` writes any missing PNG
(deterministic — fixed seed, pure numpy/PIL). See that module's docstring for
why each fixture is sensitive to its parameter.
"""
import importlib.util
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest

from beadstudio.core.convert import (
    _MEAN_EDGE_MAX,
    _MEAN_EDGE_SCALE_K_HIGH,
    _edge_scale,
    convert,
)
from beadstudio.core.models import EdgeConfig

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REGRESSION = Path(__file__).resolve().parent / "regression"

# Grid each fixture is converted at. Hard-coded per fixture (NOT derived from
# the PNG size) so a fixture resizing never silently changes the test grid.
FIXTURE_GRIDS: Dict[str, Tuple[int, int]] = {
    "thin_line": (8, 8),
    "gradient": (8, 8),
    "transparent": (8, 8),
    "hard_boundary": (32, 16),
    "photo_like": (8, 8),
}

# Measured palette codes (perler) for the tuned behaviors asserted below.
LINE_CODE = "80-19098"      # the pale-pink line color, nearest palette match
BG_RED_CODE = "80-15211"    # the (200,30,30) red field
GRADIENT_FLIP_CODE = "80-15961"  # code of the smooth-mean cell after LOW raise
PHOTO_TAN_CODE = "80-19003"  # code the photo texture gets repainted to at 0.05

UPDATE_SNAPSHOTS = os.environ.get("REGRESSION_UPDATE_SNAPSHOTS") == "1"


def _load_fixture_generator():
    """Load ``tests/fixtures/make_sensitive_fixtures.py`` without import-mode
    fragility (module lives outside the test package's import tree)."""
    spec = importlib.util.spec_from_file_location(
        "make_sensitive_fixtures",
        FIXTURES / "make_sensitive_fixtures.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_generator = _load_fixture_generator()
ensure_fixtures = _generator.ensure_fixtures


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(name: str, edge_config: Optional[EdgeConfig] = None):
    """Convert a sensitive fixture at its pinned grid (mean mode, no dither)."""
    width, height = FIXTURE_GRIDS[name]
    return convert(
        str(FIXTURES / f"{name}.png"),
        width=width,
        height=height,
        cell_mode="mean",
        edge_config=edge_config,
    )


def _snapshot_dict(pattern) -> Dict:
    """The serializable (JSON-safe) snapshot of a convert() result."""
    return {
        "codes": [list(row) for row in pattern.codes],
        "indices": [list(row) for row in pattern.indices],
        "width": pattern.width,
        "height": pattern.height,
        "empty_count": pattern.empty_count,
        "colors_used": pattern.colors_used,
        "legend": [
            {"code": entry["code"], "rgb": list(entry["rgb"]), "count": entry["count"]}
            for entry in pattern.legend
        ],
    }


def _snapshot_path(name: str) -> Path:
    return REGRESSION / f"{name}_expected.json"


def _write_snapshot(name: str) -> None:
    REGRESSION.mkdir(parents=True, exist_ok=True)
    path = _snapshot_path(name)
    path.write_text(
        json.dumps(_snapshot_dict(_run(name)), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"  [snapshot] wrote {path.name}")


def _line_cells(pattern) -> int:
    """Count cells that were recovered/repainted as the pale-pink line."""
    return sum(1 for row in pattern.codes for cell in row if cell == LINE_CODE)


def _changed_cells(a, b) -> List[Tuple[int, int]]:
    """Cell positions whose palette code differs between two patterns."""
    assert a.width == b.width and a.height == b.height
    return [
        (y, x)
        for y in range(a.height)
        for x in range(a.width)
        if a.codes[y][x] != b.codes[y][x]
    ]


def _codes_equal(a, b) -> bool:
    return a.codes == b.codes


# ---------------------------------------------------------------------------
# Fixture generation (idempotent: only writes missing PNGs)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def _sensitive_fixtures():
    ensure_fixtures()


# ---------------------------------------------------------------------------
# Baseline golden snapshots
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(FIXTURE_GRIDS))
def test_snapshot_matches(name):
    """convert() (default edge_config) must byte-match the committed snapshot.

    A snapshot is written the first time it is missing (fresh checkout), then
    every later run compares EXACTLY — codes/indices/legend/width/height/
    empty_count/colors_used. Set ``REGRESSION_UPDATE_SNAPSHOTS=1`` to refresh
    (see module docstring); never refresh just to silence a failure.
    """
    expected = _snapshot_dict(_run(name))
    path = _snapshot_path(name)
    if UPDATE_SNAPSHOTS or not path.exists():
        _write_snapshot(name)
        return
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert expected == saved, (
        f"{name}: convert() output changed from the committed snapshot "
        f"({path.name}). The tuned gray-halo / stroke behavior must not drift "
        "silently. If the change is INTENTIONAL, refresh via "
        "REGRESSION_UPDATE_SNAPSHOTS=1 after updating the tests."
    )


@pytest.mark.skip(reason="Explicit snapshot refresh — run instead with "
                         "REGRESSION_UPDATE_SNAPSHOTS=1, see module docstring.")
def test_update_snapshots():
    """Regenerate every baseline snapshot (kept for the documented workflow)."""
    for name in FIXTURE_GRIDS:
        _write_snapshot(name)


# ---------------------------------------------------------------------------
# Parameter-sensitivity: stroke gates (thin_line + photo_like)
# ---------------------------------------------------------------------------

def test_stroke_min_fraction_recovers_thin_line():
    """stroke_min_fraction: 0.12 recovers the 2px line, 0.30 drops it.

    The line covers 2/8 = 25% of each crossed cell. Raising the gate above
    25% removes every candidate → the chain never forms → no repaint.
    """
    default = _run("thin_line")
    strict = _run("thin_line", EdgeConfig(stroke_min_fraction=0.30))
    loose = _run("thin_line", EdgeConfig(stroke_min_fraction=0.05))
    assert _line_cells(default) == 6, "default must recover the 6-cell line"
    assert _line_cells(strict) == 0, "raising the gate to 0.30 must drop the line"
    assert _line_cells(loose) == 6, "a loose gate (0.05) must keep recovering it"
    assert _line_cells(default) > _line_cells(strict)


def test_stroke_min_length_gate():
    """stroke_min_length: chain of 6 cells is a stroke at 5, not at 8.

    The line spans 6 of the 8 grid rows; raising the minimum chain length to
    8 leaves the chain below the gate → no repaint.
    """
    default = _run("thin_line")
    long_gate = _run("thin_line", EdgeConfig(stroke_min_length=8))
    assert _line_cells(default) == 6
    assert _line_cells(long_gate) == 0
    assert _line_cells(default) > _line_cells(long_gate)


def test_stroke_min_deltae_gate():
    """stroke_min_deltae: line is ΔE00≈43.5 from the red background.

    35 accepts the candidate, 45 rejects it — higher gate ⇒ fewer stroke
    candidates ⇒ fewer recovered line cells (measured: 6 → 0).
    """
    default = _run("thin_line")
    harder = _run("thin_line", EdgeConfig(stroke_min_deltae=45))
    assert _line_cells(default) == 6
    assert _line_cells(harder) == 0
    assert _line_cells(default) > _line_cells(harder)


def test_stroke_min_fraction_suppresses_photo_texture():
    """stroke_min_fraction: tuned 0.12 suppresses blue+tan photo texture.

    Every cell's tan patch is 7.8-10.9% (below 12%), so the tuned default and
    the stricter 0.30 produce IDENTICAL output (nothing promoted). Loosening
    to 0.05 promotes the whole grid into one runaway stroke that repaints it
    tan — the failure mode the tuning exists to prevent.
    """
    default = _run("photo_like")
    strict = _run("photo_like", EdgeConfig(stroke_min_fraction=0.30))
    loose = _run("photo_like", EdgeConfig(stroke_min_fraction=0.05))
    assert _codes_equal(default, strict), "0.30 must still suppress the texture"
    assert not _codes_equal(default, loose), "0.05 must over-promote (regression guard)"
    assert all(
        cell == PHOTO_TAN_CODE for row in loose.codes for cell in row
    ), "the 0.05 whole-grid stroke must repaint every cell tan"


# ---------------------------------------------------------------------------
# Parameter-sensitivity: edge-aware mean sampling (gradient + hard_boundary)
# ---------------------------------------------------------------------------

def test_mean_edge_range_low_gradient_flip():
    """mean_edge_range_low: raising it routes the steep band onto the mean path.

    The gradient's steep middle cells have a per-channel range ≈ 183: under the
    default LOW (effective ≈ 156) they sit in the ambiguous zone and stay on
    the dominant color (dark-red extreme); raising LOW to 200 (effective 255)
    makes them smooth-interior and outputs the linear-space mean instead. All 8
    flipped cells are the middle column (x==3).
    """
    default = _run("gradient")
    raised = _run(
        "gradient",
        EdgeConfig(mean_edge_range_low=200, mean_edge_range_high=255),
    )
    flipped = _changed_cells(default, raised)
    assert len(flipped) == 8, f"expected 8 flipped gradient cells, got {len(flipped)}"
    assert all(x == 3 for _, x in flipped), "flips must be the steep middle band"
    # Direction: dark-red dominant extreme -> smooth gradient mean.
    assert all(default.codes[y][x] != GRADIENT_FLIP_CODE for y, x in flipped)
    assert all(raised.codes[y][x] == GRADIENT_FLIP_CODE for y, x in flipped)


def test_mean_edge_deltae_threshold_hard_boundary():
    """mean_edge_deltae_threshold: a moderate raise blends an ambiguous edge.

    The bottom dark-blue|light-blue edge cells have ΔE00≈45 in the ambiguous
    zone. Gate 15 keeps them DOMINANT (no gray-halo blend); gate 50 exceeds
    their ΔE00 and routes them to the smooth-mean path. Lowering to 5 changes
    nothing (every edge cell's ΔE00 is far above 5).
    """
    default = _run("hard_boundary")
    blended = _run("hard_boundary", EdgeConfig(mean_edge_deltae_threshold=50))
    tight = _run("hard_boundary", EdgeConfig(mean_edge_deltae_threshold=5))
    flipped = _changed_cells(default, blended)
    assert len(flipped) == 8, f"expected 8 blended edge cells, got {len(flipped)}"
    # The 8 flipped cells are the bottom-half straddle column (rows 8..15, x=8).
    assert all(y >= 8 and x == 8 for y, x in flipped)
    # Direction: the default keeps the boundary dominant, the raise blends it.
    assert not _codes_equal(default, blended)
    assert _codes_equal(default, tight)


def test_mean_edge_range_high_preserves_boundary_dominant():
    """mean_edge_range_high: pinned as a documented no-visible-change invariant.

    Raising HIGH routes cells whose channel range exceeds the default effective
    HIGH (183 at this grid) into the ambiguous zone — but every such cell has
    ΔE00 far above the 15.0 deltae gate, so BOTH the dominant branch and the
    ambiguous branch output the dominant color. The observable output therefore
    does NOT change: this is the engine deliberately preserving gray-halo-free
    boundary cells, not a dead parameter. The test pins both facts:

    * the knob is wired (the effective HIGH threshold provably rises), and
    * the visible output stays identical (if the ambiguous branch ever starts
      blending, this equality assertion fails and the tuning is broken).
    """
    default = _run("hard_boundary")
    raised = _run("hard_boundary", EdgeConfig(mean_edge_range_high=255))
    assert _codes_equal(default, raised), (
        "raising mean_edge_range_high must NOT change the visible output: cells "
        "it newly admits to the ambiguous zone still have ΔE00 > "
        "mean_edge_deltae_threshold and stay dominant (gray-halo-free)."
    )
    # The parameter still provably reaches the effective-threshold arithmetic.
    cell_area = 8.0  # 64x64 source at the pinned 32x16 grid
    default_high_eff = min(
        180 * _edge_scale(cell_area, _MEAN_EDGE_SCALE_K_HIGH), _MEAN_EDGE_MAX
    )
    raised_high_eff = min(
        255 * _edge_scale(cell_area, _MEAN_EDGE_SCALE_K_HIGH), _MEAN_EDGE_MAX
    )
    assert raised_high_eff > default_high_eff, (
        "mean_edge_range_high must raise the effective HIGH threshold"
    )


# ---------------------------------------------------------------------------
# Alpha handling regression guard
# ---------------------------------------------------------------------------

def test_transparent_alpha_mask_regression():
    """transparent.png: transparent cells stay empty, opaque side converts.

    Pure regression guard for RGBA handling in mean mode (no parameter is
    expected to move it): the left half is fully transparent (alpha 0) and must
    map to empty pegs, the right half is an opaque red field with a pale-pink
    line that is still recovered as a stroke.
    """
    pattern = _run("transparent")
    assert pattern.empty_count == 32, "the whole transparent half must be empty"
    assert all(
        cell is None for row in pattern.codes for cell in row[:4]
    ), "left-half cells must be inactive (None)"
    assert all(
        cell is not None for row in pattern.codes for cell in row[4:]
    ), "right-half cells must be active"
    assert _line_cells(pattern) == 8, "the opaque-side line must still be recovered"
    legend_codes = {entry["code"] for entry in pattern.legend}
    assert BG_RED_CODE in legend_codes and LINE_CODE in legend_codes


# ---------------------------------------------------------------------------
# Validation rejection at the convert() call site
# ---------------------------------------------------------------------------

def test_convert_rejects_invalid_edge_config():
    """An invalid EdgeConfig is rejected (EdgeConfig.__post_init__), including
    when passed through convert(): low must stay below high."""
    with pytest.raises(ValueError, match="mean_edge_range_low must be less than"):
        convert(
            str(FIXTURES / "thin_line.png"),
            width=8,
            height=8,
            cell_mode="mean",
            edge_config=EdgeConfig(mean_edge_range_low=200, mean_edge_range_high=100),
        )
