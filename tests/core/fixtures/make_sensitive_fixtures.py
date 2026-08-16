"""Generate the W4 parameter-sensitivity PNG fixtures (reproducible).

Each fixture is designed so a specific ``EdgeConfig`` parameter provably
reaches its algorithm path — a directional, observable output change on that
fixture (see ``tests/test_regression_sensitive.py`` for the assertions):

* ``thin_line.png``       — red background + a 2px pale-pink vertical line that
  spans exactly 6 of the 8 grid cells. SENSITIVE to ``stroke_min_fraction``
  (0.12 recovers the line, 0.30 drops it), ``stroke_min_length`` (chain of 6:
  length 5 recovers, 8 drops) and ``stroke_min_deltae`` (the line is ΔE00 ≈ 43.5
  from the background: gate 35 accepts it, 45 rejects it).
* ``gradient.png``        — smooth horizontal red→light-red gradient whose
  middle band is steep enough that its per-cell channel range (≈183) lands in
  the edge-aware AMBIGUOUS zone under default thresholds. SENSITIVE to
  ``mean_edge_range_low``: raising it routes those cells onto the smooth-mean
  path (cell flips from the dark-red extreme to the gradient mean).
* ``transparent.png``     — RGBA: left half fully transparent, right half an
  opaque red field with the same pale-pink line. Alpha-handling regression
  guard (no specific parameter sensitivity).
* ``hard_boundary.png``   — top half: hard red/blue edge (channel range 225 →
  DOMINANT branch, always stays dominant). Bottom half: hard dark-blue/light-blue
  edge with ΔE00 ≈ 45 in the AMBIGUOUS zone. SENSITIVE to
  ``mean_edge_deltae_threshold`` (15 keeps dominant, 50 blends to the mean).
  ``mean_edge_range_high``: raising it visibly changes NOTHING (cells newly
  admitted to the ambiguous zone still have ΔE00 > threshold and stay dominant)
  — pinned as a documented invariant test, see
  ``test_mean_edge_range_high_preserves_boundary_dominant``.
* ``photo_like.png``      — blue+tan two-tone texture; every cell carries a
  5-7 px tan patch (7.8-10.9% of the cell, below the 12% tuned gate). SENSITIVE
  to ``stroke_min_fraction``: the tuned 0.12 keeps every cell suppressed
  (identical output to 0.30), while loosening to 0.05 promotes the whole grid
  into one runaway "stroke" and repaints it tan.

Deterministic: pure numpy/PIL, fixed random seed, no external state.
Regeneration is idempotent — files are written only when missing (pass
``--force`` to overwrite).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

# tests/fixtures/make_sensitive_fixtures.py — fixtures live next to this file.
FIXTURE_DIR = Path(__file__).resolve().parent

# Thin line: red background, pale-pink line. The line is ΔE00 ≈ 43.5 from the
# background (measured) so the stroke_min_deltae gate at 35 accepts it and 45
# rejects it, while a 2px-wide line is 25% of an 8px-wide cell (recovers at
# stroke_min_fraction 0.12, drops at 0.30).
THIN_LINE_BG = (200, 30, 30)
THIN_LINE_COLOR = (255, 220, 200)

# Gradient: per-column R follows a piecewise-linear curve with a steep middle
# band (cols 24..31) whose cell range ≈ 183 lands in the ambiguous zone
# (default low_eff ≈ 156 < 183 < high_eff ≈ 210 at grid 8x8 / 64px cells).
GRADIENT_LOW = (10, 0, 0)
GRADIENT_MID_START = (30, 0, 0)
GRADIENT_MID_END = (240, 50, 20)
GRADIENT_HIGH = (250, 60, 30)

# Hard boundary: top red|blue (hard edge, channel range 225 → dominant branch),
# bottom dark-blue|light-blue (edge ΔE00 ≈ 45 → ambiguous zone, deltae gate 15
# keeps dominant, 50 blends).
TOP_LEFT = (200, 30, 30)
TOP_RIGHT = (20, 90, 200)
BOTTOM_LEFT = (0, 0, 80)
BOTTOM_RIGHT = (0, 0, 230)

# Photo-like texture: blue cells with 5-7 tan pixels each (7.8-10.9%).
PHOTO_BLUE = (30, 30, 200)
PHOTO_TAN = (255, 220, 100)
PHOTO_SEED = 7


def _make_thin_line() -> Image.Image:
    arr = np.zeros((64, 64, 3), dtype=np.uint8)
    arr[:, :, 0] = THIN_LINE_BG[0]
    arr[:, :, 1] = THIN_LINE_BG[1]
    arr[:, :, 2] = THIN_LINE_BG[2]
    # 2px vertical line at x=26..27, spanning rows 0..47 (6 cells at grid 8).
    arr[0:48, 26:28] = THIN_LINE_COLOR
    return Image.fromarray(arr, "RGB")


def _make_gradient() -> Image.Image:
    arr = np.zeros((64, 64, 3), dtype=np.uint8)
    for c in range(64):
        if c < 24:  # gentle ramp toward the steep band
            t = c / 24
            col = tuple(
                int(GRADIENT_LOW[i] + (GRADIENT_MID_START[i] - GRADIENT_LOW[i]) * t)
                for i in range(3)
            )
        elif c < 32:  # steep band — the deltae/range-sensitive cells
            t = (c - 24) / 8
            col = tuple(
                int(GRADIENT_MID_START[i] + (GRADIENT_MID_END[i] - GRADIENT_MID_START[i]) * t)
                for i in range(3)
            )
        else:  # gentle ramp toward the light end
            t = (c - 32) / 32
            col = tuple(
                int(GRADIENT_MID_END[i] + (GRADIENT_HIGH[i] - GRADIENT_MID_END[i]) * t)
                for i in range(3)
            )
        arr[:, c] = col
    return Image.fromarray(arr, "RGB")


def _make_transparent() -> Image.Image:
    arr = np.zeros((64, 64, 4), dtype=np.uint8)
    arr[:, :, 3] = 0  # left half fully transparent
    # right half opaque red field
    arr[:, 32:, 0] = THIN_LINE_BG[0]
    arr[:, 32:, 1] = THIN_LINE_BG[1]
    arr[:, 32:, 2] = THIN_LINE_BG[2]
    arr[:, 32:, 3] = 255
    # same pale-pink line, full height (8 cells -> chain of 8, a real stroke)
    arr[:, 48:50, 0] = THIN_LINE_COLOR[0]
    arr[:, 48:50, 1] = THIN_LINE_COLOR[1]
    arr[:, 48:50, 2] = THIN_LINE_COLOR[2]
    arr[:, 48:50, 3] = 255
    return Image.fromarray(arr, "RGBA")


def _make_hard_boundary() -> Image.Image:
    arr = np.zeros((64, 64, 3), dtype=np.uint8)
    # Top half: red | blue, hard edge at x=35 (not cell-aligned at grid 32 wide).
    arr[0:32, :35] = TOP_LEFT
    arr[0:32, 35:] = TOP_RIGHT
    # Bottom half: dark blue | light blue, hard edge at x=17 (not cell-aligned).
    arr[32:, :17] = BOTTOM_LEFT
    arr[32:, 17:] = BOTTOM_RIGHT
    return Image.fromarray(arr, "RGB")


def _make_photo_like() -> Image.Image:
    arr = np.zeros((64, 64, 3), dtype=np.uint8)
    rng = np.random.default_rng(PHOTO_SEED)
    for cy in range(8):
        for cx in range(8):
            y0, x0 = cy * 8, cx * 8
            arr[y0:y0 + 8, x0:x0 + 8] = PHOTO_BLUE
            # 5-7 tan pixels per cell: below the 12% gate (max 10.9%), above 5%.
            n = int(rng.integers(5, 8))
            for k in range(n):
                arr[y0 + (k % 8), x0 + (k % 8)] = PHOTO_TAN
    return Image.fromarray(arr, "RGB")


_BUILDERS = {
    "thin_line": _make_thin_line,
    "gradient": _make_gradient,
    "transparent": _make_transparent,
    "hard_boundary": _make_hard_boundary,
    "photo_like": _make_photo_like,
}


def ensure_fixtures(force: bool = False) -> None:
    """Write every fixture PNG that is missing (or all, with ``force``).

    Idempotent: keeps existing files untouched so a normal test run never
    churns the committed fixtures.
    """
    for name, builder in _BUILDERS.items():
        path = FIXTURE_DIR / f"{name}.png"
        if force or not path.exists():
            builder().save(path)
            print(f"wrote {path.name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true",
        help="overwrite existing fixture PNGs (default: write only missing ones)",
    )
    args = parser.parse_args()
    ensure_fixtures(force=args.force)
    sys.exit(0)
