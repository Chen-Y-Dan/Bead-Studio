"""
Image-to-bead-pattern conversion pipeline.

Core pipeline: load image → scale to grid → per-cell dominant color → sRGB→Lab
gamma-correct conversion (or OKLab) → CIEDE2000 palette matching (default)
or OKLab Euclidean → Floyd-Steinberg dithering → BFS region cleanup → output grid.

Ported from HansBug/pypindou (Apache-2.0), upgraded with CIEDE2000 color matching
(via ``colour-science``), gamma-correct sRGB→Lab, OKLab support, and deterministic
dominant-color-per-cell extraction.

References
----------
- sRGB→Lab: IEC 61966-2-1:1999 gamma, CIE 1931 2° observer, D65 illuminant.
  Matrix from Lindbloom (http://www.brucelindbloom.com).
- CIEDE2000: CIE 142-2001 via ``colour.difference.delta_E_CIE2000``.
- OKLab: Björn Ottosson (2020), https://bottosson.github.io/posts/oklab/.
- Floyd-Steinberg: R. W. Floyd, L. Steinberg, "An Adaptive Algorithm for Spatial
  Grey Scale", SID 1975.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

from beadstudio.core.models import EdgeConfig, Pattern
from beadstudio.core.palette import PERLER_COLORS

from .cleanup import _bfs_region_cleanup, _merge_rare_colors
from .color import _convert_colors, linear_to_srgb, srgb_to_lab, srgb_to_linear
from .dither import _apply_floyd_steinberg
from .edge import (
    _channel_range,
    _deltae00_between,
    _dominant_color_cell,
    _extreme_pixel_deltae00,
    _top_clusters,
)
from .matching import nearest_indices
from .stroke import (
    _global_background_color,
    _record_stroke_candidate,
    _trace_strokes,
)

_log = logging.getLogger(__name__)

# Public names re-exported by the ``beadstudio.core.convert`` shell via
# ``from .conversion.pipeline import *``.
__all__ = [
    "SEED",
    "PERLER_COLORS",
    "PERLER_RGB",
    "PERLER_CODES",
    "MEAN_MERGE_COLOR_TOLERANCE",
    "parse_cell_mode",
    "convert",
]

# ---------------------------------------------------------------------------
# Fixed random seed for determinism
# ---------------------------------------------------------------------------
SEED = 42

# ---------------------------------------------------------------------------
# Source image pixel cap (decompression-bomb defense, W0-B/B1)
# ---------------------------------------------------------------------------
# Attacker-controlled source images are decoded without any pixel limit by
# default: a 9000×9000 PNG (~340KB) decompresses to ~1.35GB of RAM. Reject
# sources above 24 megapixels (~4× a typical large photo) BEFORE decoding.
_MAX_SOURCE_PIXELS: int = 24_000_000
# Defense-in-depth: make PIL itself enforce the cap (DecompressionBombError
# at 2× the cap, DecompressionBombWarning above it) on every open/decode in
# this process instead of PIL's default ~178MP limit.
Image.MAX_IMAGE_PIXELS = _MAX_SOURCE_PIXELS

# ---------------------------------------------------------------------------
# Perler bead palette (103 colors) — single source: palette.PERLER_COLORS,
# loaded from data/palettes/perler.json (see beadstudio.core.palette).
# ---------------------------------------------------------------------------
PERLER_RGB = np.array([rgb for _, rgb in PERLER_COLORS], dtype=np.float64)
PERLER_CODES = [code for code, _ in PERLER_COLORS]

# Palette cache: brand → (rgb_array, codes_list)
# Hardcoded perler data retained as ultimate fallback.
_CACHED_PALETTES: Dict[str, Tuple[np.ndarray, List[str]]] = {}


def _get_palette_rgb(brand: str) -> np.ndarray:
    """Load palette RGB array (float64 N×3) for a brand via palette.load_palette.

    Falls back to hardcoded PERLER_RGB only when the perler JSON is missing.
    Unknown brands raise ValueError with Chinese message listing all brands.
    """
    if brand in _CACHED_PALETTES:
        return _CACHED_PALETTES[brand][0].copy()

    try:
        from beadstudio.core.palette import list_brands, load_palette
        data = load_palette(brand)
    except FileNotFoundError:
        if brand == "perler":
            _CACHED_PALETTES["perler"] = (PERLER_RGB.copy(), list(PERLER_CODES))
            return PERLER_RGB.copy()
        from beadstudio.core.palette import list_brands
        available = "、".join(list_brands())
        raise ValueError(f"不支持的品牌: {brand!r}。可用品牌: {available}")

    colors = data["colors"]
    if not colors:
        raise ValueError(f"品牌 {brand!r} 的色盘为空")

    rgb_list: List[List[int]] = []
    codes: List[str] = []
    for c in colors:
        r, g, b = c["rgb"]
        for val in (r, g, b):
            if not isinstance(val, int) or val < 0 or val > 255:
                raise ValueError(
                    f"品牌 {brand!r} 色号 {c['code']!r} 的 RGB 值无效: "
                    f"({r}, {g}, {b})"
                )
        rgb_list.append([r, g, b])
        codes.append(c["code"])

    rgb_array = np.array(rgb_list, dtype=np.float64)
    _CACHED_PALETTES[brand] = (rgb_array, codes)
    return rgb_array.copy()


def _get_palette_codes(brand: str) -> List[str]:
    """Load palette color codes for a brand (same order as RGB array)."""
    if brand in _CACHED_PALETTES:
        return list(_CACHED_PALETTES[brand][1])
    _get_palette_rgb(brand)  # populates the cache
    return list(_CACHED_PALETTES[brand][1])


def _palette_arrays_from_colors(
    brand: str, colors: List[Dict[str, Any]]
) -> Tuple[np.ndarray, List[str]]:
    """Build ``(rgb_array, codes)`` from a palette ``colors`` list.

    Same validation and ordering rules as :func:`_get_palette_rgb` (RGB values
    validated, codes kept in list order), so a filtered palette feeds both the
    matching array and the code grid consistently.
    """
    if not colors:
        raise ValueError(f"品牌 {brand!r} 的色盘为空")

    rgb_list: List[List[int]] = []
    codes: List[str] = []
    for c in colors:
        r, g, b = c["rgb"]
        for val in (r, g, b):
            if not isinstance(val, int) or val < 0 or val > 255:
                raise ValueError(
                    f"品牌 {brand!r} 色号 {c['code']!r} 的 RGB 值无效: "
                    f"({r}, {g}, {b})"
                )
        rgb_list.append([r, g, b])
        codes.append(c["code"])

    return np.array(rgb_list, dtype=np.float64), codes


# ---------------------------------------------------------------------------
# Cell-color mode parsing (--cell-color)
# ---------------------------------------------------------------------------

# Whitelist: English + Chinese aliases normalize to the canonical mode.
_CELL_MODE_ALIASES = {
    "dominant": "dominant",
    "mean": "mean",
    "众数": "dominant",
    "均值": "mean",
}

# Tolerance-aware region-merge threshold (Euclidean distance in CIE L*a*b*,
# ΔE*ab). Used for ``cell_mode="mean"``: subtle lighting/gradient variation
# whose palette colours are within this distance is merged, while farther
# neighbours are treated as structural boundaries (contours) and preserved.
MEAN_MERGE_COLOR_TOLERANCE = 6.0

# ---------------------------------------------------------------------------
# Edge-aware mean sampling thresholds (evidence-based)
# ---------------------------------------------------------------------------
#
# ``cell_mode="mean"`` must not blend across a hard colour boundary — a
# gamma-corrected linear-space average turns a red/green boundary into a
# gray-brown halo (灰边). Per cell we decide with a two-stage test:
#
#   1. ``A`` = max per-channel range (fast sRGB pre-filter):
#        A <= mean_edge_range_low    → smooth interior → linear-space mean.
#        A >  mean_edge_range_high   → unambiguous boundary → dominant colour.
#        otherwise                   → ambiguous zone → refined Lab decision.
#   2. Pairwise CIEDE2000 ΔE00 among the extreme (per-channel max/min) pixels:
#        ΔE00 > mean_edge_deltae_threshold → real chromatic boundary → dominant.
#        otherwise                        → lightness gradient / noise → mean.

# OpenCV floodFill ``loDiff/upDiff = (20,20,20)`` sampling and the skimage
# ``RAG`` mean-colour merge band (29–35) are both common practice for "same
# colour" detection. 115 is a deliberately generous "smooth interior" bound:
# gradient cells (which must stay on the mean path) routinely exceed 40 in
# per-channel range, and true colour boundaries are almost always far above
# this band, so widening the fast mean path cuts false boundary picks with
# negligible risk of reintroducing the gray halo.
#
# Plan A tuning (parameter sweep on the 30×61 grids): LOW=115 (was 120) pulls
# the white-line image's three smooth-branch gap cells (a_range 228–233) into
# the candidate zone (LOW_eff@115 ≈ 223.8 < 228), so the line's max vertical
# run reaches 33 (was 22 at LOW=120) — the line is now continuous through
# those gaps — while the complex photo still repaints only its 10 genuine
# cells (1.4%, real 5-cell dark clusters, not noise).
#
# The six USER-TUNABLE thresholds (mean_edge_range_low=115,
# mean_edge_range_high=180, mean_edge_deltae_threshold=15.0,
# stroke_min_fraction=0.12, stroke_min_length=5, stroke_min_deltae=35.0) now
# live in ``EdgeConfig`` (beadstudio.core/models.py); ``_load_and_prepare``
# reads them from its ``edge_config`` argument (``None`` = ``EdgeConfig()``
# defaults). The tuning notes that follow describe those defaults.
#
# No literature precedent found (librarian research): this is a conservative
# "unambiguous boundary" fast-path heuristic. Any cell whose per-channel range
# exceeds it is treated as a definite boundary without running the Lab test.
#
# ΔE00 (CIEDE2000, CIE 142-2001): BCGSC guidance treats ΔE >= 5 as "two
# different colors"; aggressive palette merge uses 5–10. 15 sits above the
# aggressive-merge band: real chromatic boundaries land far above it, while
# lightness-only gradients in the ambiguous zone (ΔE00 ~5-12) stay on the mean
# path — keeping smooth transitions smooth without reintroducing the halo.

# ── Adaptive (cell-area) scaling of the two sRGB range thresholds ─────────
#
# The raw ``A`` (max per-channel range) of a cell grows with the cell's pixel
# area: a 33×33 grid over a 1050×1047 source gives each cell ~1009 px² and a
# median A of ~105, while a 73×73 grid gives ~206 px² and a median A of ~5.
# Absolute thresholds therefore misclassify big cells as "boundary" (gradients
# flattened on small grids) while small cells stay on the mean path. To keep
# the mean/dominant balance across grid sizes, the LOW/HIGH thresholds are
# scaled by power laws of the cell area relative to a reference area — with
# DECOUPLED exponents so the two thresholds adapt at different rates:
#
#     scale_low  = (cell_area / _MEAN_EDGE_REF_CELL_AREA) ** _MEAN_EDGE_SCALE_K_LOW
#     scale_high = (cell_area / _MEAN_EDGE_REF_CELL_AREA) ** _MEAN_EDGE_SCALE_K_HIGH
#     LOW_eff  = min(mean_edge_range_low  * scale_low,  _MEAN_EDGE_MAX)
#     HIGH_eff = min(mean_edge_range_high * scale_high, _MEAN_EDGE_MAX)
#
# LOW rises FASTER than HIGH (K_LOW=0.13 > K_HIGH=0.065), which is what makes
# small grids VASTLY mean-dominant: with cell_area≈1009 at width 33 over the
# 1050×1047 source (median A≈105), LOW_eff@33≈233 sits far above the median
# per-channel range, so the vast majority of cells take the smooth mean path.
# HIGH_eff@33≈251, meanwhile, stays just below the 255 clamp, so a real colour
# boundary (A≈255) still exceeds it and hits the dominant branch — only
# large-difference cells are kept dominant, and the gray halo (灰边) does not
# return on very small grids.
#
# K_LOW must stay below ~0.135 (at 0.135, HIGH_eff@33 clamps to 255 and the
# dominant branch dies on small grids → gray halo returns); K_HIGH=0.065 keeps
# HIGH_eff@33≈251 < 255 while LOW_eff < HIGH_eff holds at every grid width.
# On big grids the decoupling is mild (73-grid mean share stays ≈80%, largely
# unchanged from the single K=0.06 behaviour).
#
# _MEAN_EDGE_REF_CELL_AREA (6.06 px²) is the cell area of the golden test
# (sample_photo 128×128 at a 52×52 grid → (128/52)² ≈ 6.06), so the golden
# output is byte-identical (both scales = 1, K-independent). The clamp at 255
# keeps a huge cell from sending EVERY cell down the mean path.
_MEAN_EDGE_SCALE_K_LOW: float = 0.13
_MEAN_EDGE_SCALE_K_HIGH: float = 0.065
_MEAN_EDGE_REF_CELL_AREA: float = 6.06
_MEAN_EDGE_MAX: int = 255

# ── Stroke-tracking: fine-line retention ─────────────────────────────────
# A thin line crossing a cell occupies a minority of the cell's pixels, so
# the dominant (most-frequent) pick swallows it → the line breaks into
# scattered pixels. A cell whose 2nd-most-frequent color is significant and
# perceptually far from the dominant color is a "candidate line cell" — and
# the line can be EITHER the dominant or the second color of the cell (a
# thick line, or a diagonal crossing a coarse cell, becomes the majority).
# After per-cell extraction we trace candidate cells across the grid
# (8-neighbour, cells sharing any candidate color within ΔE00); chains of
# >= stroke_min_length cells are real strokes, every cell in the chain is
# repainted with the chain's line color (the color shared across the most
# chain cells, tie-broken by distance from the global background color), and
# scattered noise (short chains) is left untouched.
#
# The gates are deliberately STRICT (measured on real photos): photo texture
# rarely reaches a 12% second-cluster share or ΔE00 35 against the dominant
# cluster, while thin real lines do — so raising the gates drops photo-noise
# candidates without losing genuine strokes.
#
# Plan A tuning (parameter sweep on the 30×61 grids): 0.12 (was 0.18) exactly
# catches the white-line image's line cells, where the 4-px line covers
# 12.5% of a 32-px-wide cell — 0.18 rejected them and the line broke into
# scattered cells. At 0.12 the line is recovered (56/61 near-white cells, max
# vertical run 33) while the complex photo still repaints only its 10 genuine
# cells (1.4%, real 5-cell dark clusters, not noise).
# stroke_min_fraction=0.12  — 2nd color cluster must be >= 12% of the cell
# stroke_min_deltae=35.0    — dominant vs 2nd color ΔE00 must be large
# stroke_min_length=5       — chain must span >= 5 cells to be a stroke
# (These three live in ``EdgeConfig`` — models.py — read via ``edge_config``;
# the internal _STROKE_* constants below remain module-level.)
_STROKE_LINE_DELTAE: float = 15.0    # a candidate cell joins a chain when one
                                     # of its colors is within this ΔE00 of a
                                     # color the chain already contains
_STROKE_CLUSTER_DELTAE: float = 12.0  # colors within this ΔE00 of a cluster
                                      # representative belong to the same
                                      # cluster (absorbs JPEG/anti-aliasing
                                      # shade spread around a thin line)
_STROKE_TOP_N: int = 1024             # SAFETY CAP on the number of most-
                                      # frequent distinct colors examined
                                      # when clustering a cell (applied AFTER
                                      # the histogram). _top_clusters greedily
                                      # clusters EVERY distinct color up to
                                      # this cap so a thin line's full white
                                      # population is captured — the real-
                                      # image failing cells held 337-643
                                      # distinct near-white shades, so a
                                      # small cap (12) truncated the white
                                      # population to 0-6.7% and lost the
                                      # line. 1024 never bites the line case
                                      # while bounding pathological photo
                                      # cells (thousands of colors).
_STROKE_A_RANGE_MIN: float = 180.0   # FLOOR of the adaptive per-channel-range
                                      # pre-gate for the stroke candidate check.
                                      # The effective gate is
                                      # ``max(low_eff, _STROKE_A_RANGE_MIN)``:
                                      # low_eff is the SAME adaptive threshold
                                      # the mean edge-detector uses to decide
                                      # "boundary vs smooth", so a cell the
                                      # mean sampler calls smooth-interior
                                      # (a_range <= low_eff) is NEVER a stroke
                                      # candidate — on coarse photo grids
                                      # low_eff ≈ 235 far exceeds this floor
                                      # (the old fixed 180 gate admitted photo
                                      # gradient/noise cells in the smooth
                                      # branch and spawned runaway repaint
                                      # chains). The floor protects fine grids
                                      # where low_eff can drop below 180: it
                                      # stays ABOVE mid-range two-tone textures
                                      # (e.g. a black/red mix spans only
                                      # ~140) whose large second cluster is a
                                      # regular pattern, not a thin line —
                                      # recording every such cell would trace
                                      # one whole-grid "stroke" that repaints
                                      # the entire image.
_STROKE_DARK_MAX: int = 80            # chain line colors with max(R,G,B) < this
                                      # are treated as shadow/background noise
                                      # and EXCLUDED from the line-color vote
                                      # (see _chain_line_color). Painting a
                                      # chain with a near-black color turns
                                      # white/light cells black → BLACK-EDGE
                                      # artifacts (黑边) on photo grids where
                                      # JPEG shadows/dark spots sit next to a
                                      # genuine light line. A DARK color is
                                      # usually shadow, not a clear visual
                                      # feature, so it must never win the
                                      # vote. If excluding dark colors leaves
                                      # NO candidates, the exclusion is
                                      # dropped so genuinely black-on-light
                                      # images still recover their black
                                      # lines.


def _edge_scale(cell_area: float, k: float) -> float:
    """Adaptive threshold scale factor for a cell of ``cell_area`` source px².

    ``1.0`` at the reference area (golden 52×52 test), growing sub-linearly
    with cell area via a power law with exponent ``k`` — big cells (small
    grids) get higher effective thresholds so their naturally larger
    per-channel ranges stay on the mean path. Called twice from
    :func:`_load_and_prepare` with the decoupled LOW/HIGH exponents
    (``_MEAN_EDGE_SCALE_K_LOW`` > ``_MEAN_EDGE_SCALE_K_HIGH``) so the LOW
    threshold rises faster than the HIGH one on small grids.

    :param cell_area: Source pixels covered by one grid cell (float).
    :param k: Power-law exponent (``0`` → 1.0, i.e. no adaptation).
    :return: ``(cell_area / ref) ** k``.
    """
    if cell_area <= 0:
        return 1.0
    return float((cell_area / _MEAN_EDGE_REF_CELL_AREA) ** k)


def parse_cell_mode(raw: str) -> Optional[str]:
    """Parse and normalize a per-cell color extraction mode.

    Accepts ``dominant``/``mean`` and their Chinese aliases
    (``众数``/``均值``), case-insensitive and whitespace-stripped.
    Unknown values return ``None`` so callers can raise their own errors.
    """
    if raw is None:
        return None
    return _CELL_MODE_ALIASES.get(str(raw).strip().lower())


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def _load_and_prepare(
    image_path: Path,
    width: int,
    height: int,
    alpha_threshold: int = 128,
    cell_mode: str = "dominant",
    edge_config: Optional[EdgeConfig] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Load image, resize to grid, extract per-cell color.

    In ``"mean"`` mode a stroke-tracking post-pass runs after per-cell
    extraction: cells with a significant, perceptually distinct second color
    cluster are recorded as candidate line cells (keeping BOTH the dominant
    and the second color — a thin line can be either side of the cell),
    provided the cell's per-channel range reaches the ADAPTIVE gate
    ``max(low_eff, _STROKE_A_RANGE_MIN)`` — i.e. the cell must at least be
    boundary-flagged by the mean edge-detector; smooth-interior cells
    (``a_range <= low_eff``) are never stroke candidates. Chains of
    ``>= stroke_min_length`` candidates (8-neighbour, cells sharing any
    candidate color) are real strokes and every cell in the chain is repainted
    with the chain's line color (the candidate color shared by the most cells,
    tie-broken by distance from the global background) — keeping thin lines
    continuous while scattered noise (short chains) is left untouched.

    :return: ``(grid_rgb, active_mask)`` where grid_rgb has shape ``(height, width, 3)``
             and active_mask has shape ``(height, width)``.
    :param cell_mode: Per-cell color extraction mode: ``"dominant"`` (default) or
        ``"mean"``. ``"mean"`` uses edge-aware sampling: smooth interior cells
        get a gamma-corrected linear-space mean (gradients preserved), while
        cells straddling a colour boundary use the dominant colour — no gray
        halo (灰边) at boundaries.
    :param edge_config: User-tunable algorithm parameters (edge-aware mean
        sampling thresholds + stroke gates); ``None`` (default) uses
        ``EdgeConfig()`` defaults.
    """
    ec = edge_config or EdgeConfig()
    # Open lazily — Image.open reads only the header; the pixel data is NOT
    # decoded. Reject decompression bombs from the header BEFORE any full
    # decode/conversion (a 9000×9000 PNG would otherwise allocate ~1.35GB).
    src_img = Image.open(image_path)
    src_w, src_h = src_img.size
    if src_w * src_h > _MAX_SOURCE_PIXELS:
        raise ValueError("图片分辨率过大，请缩小图片（最大 2400 万像素）")
    img = src_img.convert("RGBA")
    # Resize to target grid
    img = img.resize((width, height), Image.Resampling.LANCZOS)
    rgba = np.asarray(img, dtype=np.uint8)  # (h, w, 4)

    alpha = rgba[:, :, 3]
    active_mask = alpha > alpha_threshold

    # For each grid cell, find dominant color
    # Since we resized directly to grid size, each cell = 1 pixel
    # But we need to handle the case where source is larger — we find the
    # dominant color from the source region mapped to each cell.
    # For simplicity and correctness, we resize the source to (width, height)
    # and use the resized pixel as the cell color (Lanczos interpolation).
    # For the dominant-color requirement, we instead process from original:
    src_rgba = np.asarray(src_img.convert("RGBA"), dtype=np.uint8)
    src_h, src_w = src_rgba.shape[:2]

    cell_h = src_h / height
    cell_w = src_w / width

    # Edge-aware mean thresholds scale with cell area: big cells (small grids)
    # have naturally larger per-channel ranges, so they get higher effective
    # thresholds and stay on the smooth-mean path; the golden 52×52 grid
    # (cell_area ≈ _MEAN_EDGE_REF_CELL_AREA) gets scale 1.0 → identical output.
    # The LOW/HIGH thresholds use DECOUPLED exponents: LOW rises faster than
    # HIGH so small grids send the vast majority of cells down the mean path,
    # while HIGH stays below the 255 clamp so real colour boundaries still hit
    # the dominant branch (no gray halo).
    cell_area = cell_h * cell_w
    scale_low = _edge_scale(cell_area, _MEAN_EDGE_SCALE_K_LOW)
    scale_high = _edge_scale(cell_area, _MEAN_EDGE_SCALE_K_HIGH)
    low_eff = min(ec.mean_edge_range_low * scale_low, _MEAN_EDGE_MAX)
    high_eff = min(ec.mean_edge_range_high * scale_high, _MEAN_EDGE_MAX)

    grid_rgb = np.zeros((height, width, 3), dtype=np.uint8)
    # Candidate line cells (mean mode only, boundary-flagged cells): (y, x,
    # dominant, second) in grid coordinates, collected for the stroke-tracking
    # post-pass below. BOTH colors are kept because a thin line can be either
    # the majority or the minority color of the cell it crosses.
    # Adaptive pre-gate: a cell must have a_range >= max(low_eff,
    # _STROKE_A_RANGE_MIN) — the same adaptive threshold the mean edge-
    # detector uses to decide "boundary vs smooth" (floored at 180 so
    # mid-range two-tone textures on fine grids stay rejected). Smooth-
    # interior cells (a_range <= low_eff) are NEVER candidates: on coarse
    # photo grids low_eff ≈ 235 far exceeds the old fixed 180 gate, which is
    # what let smooth photo gradient/noise cells in and spawned the runaway
    # repaint chains. All three range branches apply the SAME gate.
    stroke_gate = max(low_eff, _STROKE_A_RANGE_MIN)
    stroke_candidates: List[Tuple[int, int, np.ndarray, np.ndarray]] = []
    for y in range(height):
        for x in range(width):
            y0 = int(y * cell_h)
            x0 = int(x * cell_w)
            y1 = int((y + 1) * cell_h)
            x1 = int((x + 1) * cell_w)
            y1 = max(y1, y0 + 1)
            x1 = max(x1, x0 + 1)
            region = src_rgba[y0:y1, x0:x1]
            # Check alpha for this cell
            region_alpha = region[:, :, 3]
            if np.mean(region_alpha) <= alpha_threshold:
                active_mask[y, x] = False
                continue
            if cell_mode == "mean":
                # Mean cell color: gamma-corrected LINEAR-space mean over the
                # pixels that pass the alpha gate (only opaque-ish pixels
                # participate — transparent pixels would drag the mean toward
                # gray/black). Edge-aware sampling: a cell straddling a colour
                # boundary uses the dominant colour instead of a blend — this
                # eliminates the gray halo (灰边) that mean-averaging produces
                # at boundaries, while preserving smooth gradients inside
                # regions.
                region_rgb = region[:, :, :3].astype(np.float64)
                mask = region_alpha > alpha_threshold
                if not np.any(mask):
                    # Defensive fallback (unreachable in practice: the cell gate
                    # above guarantees at least one pixel has alpha > threshold).
                    # Use the dominant color so an odd edge case never yields a
                    # black/uninitialized cell.
                    grid_rgb[y, x] = _dominant_color_cell(region[:, :, :3])
                else:
                    masked_rgb = region_rgb[mask]
                    a_range = _channel_range(masked_rgb)
                    if a_range > high_eff:
                        # Unambiguous colour boundary: dominant colour (no
                        # averaging → no gray halo). A significant minority
                        # COLOUR CLUSTER perceptually far from the dominant
                        # cluster marks the cell as a candidate line cell
                        # (thin line straddling the cell) — traced across the
                        # grid after the loop. Clustering (not single-RGB
                        # counting) is what lets a thin line whose color is
                        # spread across JPEG/anti-aliasing shades reach the
                        # fraction gate: all near-identical shades sum into
                        # one cluster fraction. (a_range > high_eff implies
                        # a_range >= stroke_gate, but the gate is checked
                        # explicitly for consistency.)
                        dominant, second, _dom_fraction, second_fraction = _top_clusters(
                            masked_rgb.astype(np.uint8),
                            stroke_min_fraction=ec.stroke_min_fraction,
                        )
                        grid_rgb[y, x] = dominant
                        if (
                            a_range >= stroke_gate
                            and second_fraction >= ec.stroke_min_fraction
                            and _deltae00_between(dominant, second) >= ec.stroke_min_deltae
                        ):
                            stroke_candidates.append((y, x, dominant, second))
                    elif a_range > low_eff:
                        # Ambiguous zone: refine with CIEDE2000 among the
                        # extreme (per-channel max/min) pixels. A real boundary
                        # has ΔE00 ≫ threshold; a lightness-only gradient or
                        # sensor noise stays under it and keeps the smooth mean.
                        if _extreme_pixel_deltae00(masked_rgb) > ec.mean_edge_deltae_threshold:
                            grid_rgb[y, x] = _dominant_color_cell(masked_rgb)
                        else:
                            linear = srgb_to_linear(masked_rgb / 255.0)
                            mean_srgb = linear_to_srgb(linear.mean(axis=0))
                            grid_rgb[y, x] = (
                                np.rint(mean_srgb * 255.0).clip(0, 255).astype(np.uint8)
                            )
                        # A cell in the ambiguous zone can still hide a thin
                        # line (large a_range, refined test sees a boundary):
                        # record it as a stroke candidate too — but only if it
                        # clears the adaptive pre-gate (same as the dominant
                        # branch).
                        _record_stroke_candidate(
                            y, x, masked_rgb, a_range, low_eff, stroke_candidates,
                            edge_config=ec,
                        )
                    else:
                        # Smooth interior: gamma-corrected linear-space mean.
                        linear = srgb_to_linear(masked_rgb / 255.0)
                        mean_srgb = linear_to_srgb(linear.mean(axis=0))
                        grid_rgb[y, x] = (
                            np.rint(mean_srgb * 255.0).clip(0, 255).astype(np.uint8)
                        )
                        # NOT a stroke candidate: a cell the mean edge-detector
                        # classifies as smooth interior (a_range <= low_eff)
                        # never hides a "clear visual feature" — the stroke
                        # branch fires only for boundary-flagged cells. (The
                        # old fixed 180 pre-gate admitted smooth-branch photo
                        # cells on coarse grids, where low_eff ≈ 235, and that
                        # produced the runaway repaint chains.)
            else:
                grid_rgb[y, x] = _dominant_color_cell(region[:, :, :3])

    # Stroke-tracking post-pass (mean mode only): trace candidate line cells
    # into chains; repaint every cell of a chain long enough to be a real
    # stroke with the chain's line color, keeping thin lines continuous.
    if stroke_candidates and cell_mode == "mean":
        # The chain line-vs-background tie-break needs the global background
        # color (most-frequent opaque color of the source). Computed lazily
        # here — only when there is actually something to trace — so the
        # common no-candidate path pays nothing.
        background_rgb = _global_background_color(src_rgba, alpha_threshold)
        strokes = _trace_strokes(
            stroke_candidates, height, width, background_rgb,
            stroke_min_length=ec.stroke_min_length,
        )
        for (y, x), color in strokes.items():
            grid_rgb[y, x] = color

    return grid_rgb, active_mask


def _quantize_nearest(
    grid_rgb: np.ndarray,
    active_mask: np.ndarray,
    palette_rgb: np.ndarray,
    color_space: str,
    height: int,
    width: int,
) -> np.ndarray:
    """Map every active grid cell to its nearest palette colour index.

    Inactive cells stay at -1.
    """
    indices = np.full((height, width), -1, dtype=np.int32)
    flat_rgb = grid_rgb.reshape(-1, 3)
    flat_active = active_mask.reshape(-1)
    active_pixels = flat_rgb[flat_active]
    if len(active_pixels) > 0:
        mapped = nearest_indices(active_pixels, palette_rgb, color_space=color_space)
        indices_flat = indices.reshape(-1)
        active_indices = np.where(flat_active)[0]
        indices_flat[active_indices] = mapped
        indices = indices_flat.reshape(height, width)
    return indices


def _build_codes_grid(
    indices: np.ndarray,
    active_mask: np.ndarray,
    palette_codes: List[str],
    height: int,
    width: int,
) -> List[List[Optional[str]]]:
    """Build the 2D codes grid from palette indices and active mask.

    ``None`` for empty/inactive cells, palette colour-code string otherwise.
    """
    codes_grid: List[List[Optional[str]]] = []
    for y in range(height):
        row: List[Optional[str]] = []
        for x in range(width):
            idx = int(indices[y, x])
            if idx < 0 or not active_mask[y, x]:
                row.append(None)
            else:
                row.append(palette_codes[idx])
        codes_grid.append(row)
    return codes_grid


def _build_legend(
    indices: np.ndarray,
    active_mask: np.ndarray,
    palette_codes: List[str],
    palette_rgb: np.ndarray,
) -> List[Dict[str, Any]]:
    """Build colour-legend entries sorted by count desc, then by code."""
    used_indices = indices[(active_mask) & (indices >= 0)]
    if len(used_indices) > 0:
        unique_idx, counts = np.unique(used_indices, return_counts=True)
    else:
        unique_idx, counts = np.array([], dtype=np.int32), np.array([], dtype=np.int64)

    legend = [
        {
            "code": palette_codes[int(idx)],
            "rgb": tuple(int(v) for v in palette_rgb[int(idx)]),
            "count": int(cnt),
        }
        for idx, cnt in sorted(
            zip(unique_idx, counts),
            key=lambda item: (-item[1], palette_codes[int(item[0])]),
        )
    ]
    return legend


def convert(
    image_path: str,
    width: Optional[int] = None,
    height: Optional[int] = None,
    brand: str = "perler",
    color_space: str = "cie2000",
    dither: bool = False,
    cleanup: bool = True,
    min_region_size: int = 4,
    alpha_threshold: int = 128,
    max_colors: Optional[int] = None,
    cell_mode: str = "dominant",
    series_range: Optional[str] = None,
    edge_config: Optional[EdgeConfig] = None,
) -> Pattern:
    """
    Convert an image to a bead pattern grid.

    At least one of ``width``/``height`` must be given. When only one is
    provided, the other is derived from the source image's aspect ratio
    (``max(1, round(given * src_other / src_given))``), so the pattern is not
    distorted. When both are given they are used as-is.

    :param image_path: Path to source image (PNG, JPEG, etc.).
    :param width: Target grid width in beads. If ``None``, derived from
        ``height`` and the source aspect ratio.
    :param height: Target grid height in beads. If ``None``, derived from
        ``width`` and the source aspect ratio.
    :param brand: Bead brand palette key (e.g. ``"perler"``, ``"hama"``, ``"mard"``).
        Any brand with a palette JSON in ``data/palettes/`` is supported.
    :param color_space: Color distance space. ``"cie2000"`` (default, perceptual),
        ``"oklab"`` (fast Euclidean in OKLab), or ``"lab"`` (Euclidean in CIE L*a*b*).
    :param dither: Enable Floyd-Steinberg error diffusion.
    :param cleanup: Enable BFS small-region merging.
    :param min_region_size: Minimum region size in cells (regions smaller are merged).
        Only used when ``cleanup=True``. In ``cell_mode="mean"`` this is replaced
        by an adaptive value ``max(4, min(height, width) // 10)``.
    :param alpha_threshold: Alpha channel threshold (pixels with alpha <= this are
        treated as transparent/empty pegs).
    :param max_colors: Optional cap on the number of distinct bead colors in the
        final pattern. When set, the rarest used palette colors are merged into
        their nearest (in the target color space) kept color until ``<= max_colors``
        remain. ``None`` (default) keeps every matched palette color. For photos,
        mature bead tools typically cap at 20-30 colors for clean patterns.
    :param cell_mode: Per-cell color extraction mode: ``"dominant"`` (default;
        most-frequent color per cell) or ``"mean"`` (gamma-corrected linear-space
        mean over alpha-masked pixels per cell). In ``"mean"`` mode, dithering is
        auto-disabled and small-region cleanup uses tolerance-aware merging
        (``MEAN_MERGE_COLOR_TOLERANCE``) that preserves structural contours.
    :param series_range: Optional series-range spec (e.g. ``"M"`` = series A..M,
        ``"A-G"`` = series A to G) for series-structured brands (MARD/COCO/...).
        Only in-range palette colors can be matched. Flat brands (perler, hama,
        ...) have no series concept: the spec is a no-op (full palette) and
        ``max_colors`` still applies as usual. Invalid specs raise a ``ValueError``
        with a Chinese message. ``None`` (default) keeps the full palette.
    :param edge_config: User-tunable algorithm parameters (edge-aware mean
        sampling thresholds + stroke gates) for ``cell_mode="mean"``;
        ``None`` (default) uses ``EdgeConfig()`` defaults.
    :return: A typed :class:`~beadstudio.core.models.Pattern` with fields
        ``codes`` (grid of bead codes), ``indices`` (grid of palette
        indices, -1 for empty), ``width``, ``height``, ``empty_count``,
        ``colors_used``, ``legend``, ``grid_rgb``, ``active_mask``.
    :rtype: Pattern
    :raises ValueError: If parameters are invalid (neither dimension given,
        non-positive dimensions, unsupported color space, non-positive max_colors).
    :raises FileNotFoundError: If the image file is not found.
    """
    if width is None and height is None:
        raise ValueError("At least one of width or height must be provided.")
    if max_colors is not None and max_colors < 1:
        raise ValueError("max_colors must be positive.")
    if color_space not in ("cie2000", "oklab", "lab"):
        raise ValueError(f"Unsupported color_space: {color_space!r}.")

    path = Path(image_path)
    if not path.exists():
        # B2: keep the raised message path-free (the CLI echoes exception text
        # to stderr); the offending path goes to the logs instead.
        _log.error("图片不存在: %s", image_path)
        raise FileNotFoundError("找不到图片文件")

    # Derive the missing dimension from the source image's aspect ratio
    # (header-only read — PIL does not decode pixel data for `.size`).
    if width is None or height is None:
        with Image.open(path) as img:
            src_w, src_h = img.size
        if width is None:
            width = max(1, round(height * src_w / src_h))
        if height is None:
            height = max(1, round(width * src_h / src_w))
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive.")

    # Load palette
    palette_rgb = _get_palette_rgb(brand)
    palette_codes = _get_palette_codes(brand)
    if series_range is not None:
        # Restrict matching to the requested series range (applied BEFORE
        # quantization so only in-range palette colors can be matched).
        # Flat brands have no series concept: filter_by_series returns the
        # full palette → no-op. Invalid specs raise ValueError (Chinese msg).
        from beadstudio.core.palette import filter_by_series
        filtered = filter_by_series(brand, series_range)
        palette_rgb, palette_codes = _palette_arrays_from_colors(
            brand, filtered["colors"]
        )
    palette_space = _convert_colors(palette_rgb, color_space)

    # Load & prepare image → per-cell RGB + active mask
    grid_rgb, active_mask = _load_and_prepare(
        path, width, height, alpha_threshold, cell_mode=cell_mode,
        edge_config=edge_config,
    )

    # Mean mode auto-disables dithering: cells are already per-region averages,
    # so error diffusion would only add noise on top of the mean (HC8).
    if dither and cell_mode == "mean":
        _log.warning("mean 模式下抖动已自动禁用")
        dither = False

    # Quantization (dithering or nearest-neighbour)
    if dither:
        indices, _ = _apply_floyd_steinberg(
            grid_rgb, active_mask, palette_rgb, palette_space, color_space,
        )
    else:
        indices = _quantize_nearest(grid_rgb, active_mask, palette_rgb, color_space, height, width)

    # BFS small-region merging. Mean mode uses tolerance-aware merging:
    # subtle lighting/gradient variation (palette ΔE within
    # MEAN_MERGE_COLOR_TOLERANCE) is absorbed while structural contours are
    # preserved, with an adaptive minimum region size max(4, min(h, w) // 10).
    # Dominant mode keeps the exact legacy fixed-size merge (tolerance=0).
    if cleanup:
        if cell_mode == "mean":
            indices = _bfs_region_cleanup(
                indices, active_mask,
                color_tolerance=MEAN_MERGE_COLOR_TOLERANCE,
                palette_lab=srgb_to_lab(palette_rgb),
            )
        else:
            indices = _bfs_region_cleanup(indices, active_mask, min_region_size=min_region_size)

    # Color-count limiting: merge rarest colors after cleanup so the final
    # pattern uses at most max_colors distinct bead colors.
    if max_colors is not None:
        indices = _merge_rare_colors(indices, active_mask, palette_space, max_colors)

    # Build output structures
    codes_grid = _build_codes_grid(indices, active_mask, palette_codes, height, width)
    empty_count = sum(1 for row in codes_grid for c in row if c is None)
    legend = _build_legend(indices, active_mask, palette_codes, palette_rgb)

    return Pattern(
        codes=tuple(tuple(row) for row in codes_grid),
        indices=tuple(tuple(row) for row in indices.tolist()),
        width=width,
        height=height,
        empty_count=empty_count,
        colors_used=len(legend),
        legend=tuple(legend),
        grid_rgb=grid_rgb,          # from _load_and_prepare
        active_mask=active_mask,    # from _load_and_prepare
    )
