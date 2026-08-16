"""
Stroke tracking: candidate line cells, chain tracing, line-color voting.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np

from beadstudio.core.models import EdgeConfig

from .color import srgb_to_lab
from .edge import _deltae00_between, _top_clusters

def _record_stroke_candidate(
    y: int,
    x: int,
    masked_rgb: np.ndarray,
    a_range: int,
    low_eff: float,
    stroke_candidates: List[Tuple[int, int, np.ndarray, np.ndarray]],
    edge_config: Optional[EdgeConfig] = None,
) -> None:
    """
    Record a stroke candidate for a cell that may hide a thin line.

    Used by the ambiguous range branch of mean-mode sampling (the smooth-
    interior branch no longer records: a cell the mean edge-detector classifies
    as smooth is NOT a stroke candidate). A thin line crossing a cell keeps its
    channel range LARGE in at least one channel even when the cell looks
    "smooth" enough to be routed to a mean branch — e.g. a white line on a red
    background spans G/B by ~225 while the R channel only moves 200→255. The
    adaptive pre-gate requires ``a_range >= max(low_eff, _STROKE_A_RANGE_MIN)``
    — the SAME adaptive threshold the mean edge-detector uses to decide
    "boundary vs smooth" (``low_eff``), floored at ``_STROKE_A_RANGE_MIN`` to
    keep rejecting mid-range two-tone textures on fine grids. A cell below
    ``low_eff`` is smooth interior by definition and is skipped, and the
    color-cluster gate is identical to the dominant branch's: a significant
    second cluster (``>= stroke_min_fraction``) perceptually far from the
    dominant cluster (``>= stroke_min_deltae``) marks the cell as a candidate
    line cell.

    The cell's OUTPUT color is left untouched here — this only feeds the
    stroke-tracing post-pass, which repaints chain cells with the chain's line
    color (see :func:`_trace_strokes`).

    :param y: Grid row of the cell.
    :param x: Grid column of the cell.
    :param masked_rgb: Opaque (alpha-gated) RGB pixels of the cell region.
    :param a_range: ``_channel_range(masked_rgb)`` — already computed by the
        caller for the branch logic, so no extra pass is needed.
    :param low_eff: The cell's effective smooth-interior threshold
        (``min(mean_edge_range_low * scale_low, _MEAN_EDGE_MAX)``), computed
        per-image in :func:`_load_and_prepare`.
    :param stroke_candidates: List of ``(y, x, dominant, second)`` candidates
        accumulated for the post-pass (mutated in place).
    :param edge_config: Tunables for the candidate gates; ``None`` (default)
        resolves to ``EdgeConfig()``.
    """
    from beadstudio.core.convert import _STROKE_A_RANGE_MIN  # noqa: PLC0415
    ec = edge_config or EdgeConfig()
    if a_range < max(low_eff, _STROKE_A_RANGE_MIN):
        return
    dominant, second, _dom_fraction, second_fraction = _top_clusters(
        masked_rgb.astype(np.uint8),
        stroke_min_fraction=ec.stroke_min_fraction,
    )
    if (
        second_fraction >= ec.stroke_min_fraction
        and _deltae00_between(dominant, second) >= ec.stroke_min_deltae
    ):
        stroke_candidates.append((y, x, dominant, second))


def _chain_line_color(
    chain: List[Tuple[int, int]],
    by_pos: Dict[Tuple[int, int], Tuple[np.ndarray, np.ndarray]],
    background_rgb: np.ndarray,
) -> np.ndarray:
    """
    Pick the color that runs through a stroke chain.

    Every candidate cell on a stroke contains BOTH the line color and the
    background color (as its dominant/second pair — a thin line is the
    minority color of its cells, a thick one the majority). The chain's line
    color is the candidate color supported by the MOST cells: the number of
    chain cells that contain a color within ``_STROKE_LINE_DELTAE`` (ΔE00)
    of it. Support alone cannot tell the line from the background (they
    usually tie at ~100%), so the tie is broken by distance from the global
    background color — the line is the color FARTHEST from the background,
    since the background is the most-frequent color of the whole image.

    The line-vote is restricted to colors that are NOT near the global
    background (within ``_STROKE_LINE_DELTAE`` of it): a stroke's line color
    by definition stands out against the background. This keeps a chain from
    being "painted" with the background when a JPEG-noise cell joins it —
    such a cell contributes the background as its dominant color (boosting
    the background's raw support) but its second color is unrelated noise, so
    without the restriction the background can outvote the real line. When
    every candidate color is background-near (a pathological image with no
    clearly distinct line) the restriction is dropped and the original
    max-support + farthest-from-background rule applies unchanged.

    A SECOND restriction excludes DARK candidate colors (max(R,G,B) below
    ``_STROKE_DARK_MAX``): a near-black color is far from a light background,
    so it routinely wins the farthest-from-background tie-break even when it
    is only a JPEG shadow/dark spot next to the real line — repainting the
    chain with it turns white/light cells black (BLACK-EDGE artifacts, 黑边).
    Dark colors are shadow/background, not clear visual features, so they are
    barred from the vote. Like the background-near restriction, it is dropped
    when it would leave no candidates at all: a genuinely black-on-light image
    (all candidates dark) still recovers its black lines.

    :param chain: ``(y, x)`` cell keys of a fully grown chain.
    :param by_pos: ``{(y, x): (dominant, second)}`` for every candidate cell.
    :param background_rgb: Global background color, uint8 ``(3,)``.
    :return: The chain's line color, uint8 ``(3,)``.
    :rtype: numpy.ndarray
    """
    from colour.difference import delta_E_CIE2000
    from beadstudio.core.convert import _STROKE_DARK_MAX, _STROKE_LINE_DELTAE  # noqa: PLC0415

    # Distinct candidate colors across the chain (dominant & second of every
    # cell), deduplicated via the uint8 packing trick.
    color_list: List[np.ndarray] = []
    seen = set()
    for key in chain:
        for color in by_pos[key]:
            packed = (int(color[0]) << 16) | (int(color[1]) << 8) | int(color[2])
            if packed not in seen:
                seen.add(packed)
                color_list.append(np.asarray(color, dtype=np.uint8))
    if not color_list:
        return np.zeros(3, dtype=np.uint8)

    # Cell-support: how many chain cells contain a color within
    # _STROKE_LINE_DELTAE (ΔE00) of each distinct candidate color. Per cell
    # the dominant and second are >= stroke_min_deltae (35, EdgeConfig
    # default) apart, so at most one of them can match — the grouping below
    # stays unambiguous.
    cell_colors = np.stack([
        color for key in chain for color in by_pos[key]
    ])  # (2n, 3)
    dists = delta_E_CIE2000(
        srgb_to_lab(np.stack(color_list))[:, np.newaxis, :],   # (k, 1, 3)
        srgb_to_lab(cell_colors)[np.newaxis, :, :],            # (1, 2n, 3)
    )  # (k, 2n)
    support = (
        (dists <= _STROKE_LINE_DELTAE)
        .reshape(len(color_list), len(chain), 2)
        .any(axis=2)
        .sum(axis=1)
    )  # (k,)
    # The line color stands out against the image background — drop colors
    # that ARE the background (the shared filler of every cell). Without this,
    # a noise cell that joins the chain (sharing only the background color)
    # would hand the background the top support and erase the real line.
    vote_indices = [
        i for i in range(len(color_list))
        if _deltae00_between(color_list[i], background_rgb) > _STROKE_LINE_DELTAE
    ]
    if not vote_indices:
        vote_indices = list(range(len(color_list)))
    # Dark exclusion: colors with max(R,G,B) < _STROKE_DARK_MAX are
    # shadow/background noise, not clear visual features — painting a chain
    # with them turns light cells black (BLACK-EDGE artifacts, 黑边). They are
    # excluded even though they are far from a light background and would
    # otherwise win the vote (a dark spot ties/outranks the real line by being
    # farthest from the light background). If excluding them leaves NO
    # candidates, the exclusion is dropped (fallback) so genuinely
    # black-on-light images still recover their black lines.
    vote_indices = [
        i for i in vote_indices
        if int(color_list[i].max()) >= _STROKE_DARK_MAX
    ]
    if not vote_indices:
        vote_indices = list(range(len(color_list)))
    best = int(support[vote_indices].max())
    best_indices = [i for i in vote_indices if int(support[i]) == best]

    # Tie-break: among the max-support colors, the one FARTHEST from the
    # global background (largest ΔE00) is the line — the background is the
    # shared filler color, the line is what stands out against it.
    line = color_list[best_indices[0]]
    line_dist = _deltae00_between(line, background_rgb)
    for i in best_indices[1:]:
        dist = _deltae00_between(color_list[i], background_rgb)
        if dist > line_dist:
            line_dist = dist
            line = color_list[i]
    return line


def _global_background_color(
    src_rgba: np.ndarray,
    alpha_threshold: int = 128,
) -> np.ndarray:
    """
    Most-frequent color among the opaque pixels of the whole source image.

    Used by stroke tracing to separate a chain's line color from its
    background: both appear in (almost) every candidate cell, so the global
    background breaks the tie — the line is the color farthest from it.
    One ``np.unique`` pass over the full source (~1M px), computed only in
    mean mode when a stroke candidate was actually found.

    :param src_rgba: Source image RGBA, shape ``(h, w, 4)``.
    :param alpha_threshold: Opaque = alpha strictly greater than this.
    :return: Most-frequent opaque color, uint8 ``(3,)``.
    :rtype: numpy.ndarray
    """
    alpha = src_rgba[:, :, 3]
    opaque = src_rgba[alpha > alpha_threshold, :3]
    if opaque.shape[0] == 0:
        return np.zeros(3, dtype=np.uint8)
    flat = np.ascontiguousarray(opaque)
    packed = (flat[:, 0].astype(np.uint32) << 16) | \
             (flat[:, 1].astype(np.uint32) << 8) | \
             flat[:, 2].astype(np.uint32)
    values, counts = np.unique(packed, return_counts=True)
    winner = values[int(np.argmax(counts))]
    return np.array([
        (winner >> 16) & 0xFF,
        (winner >> 8) & 0xFF,
        winner & 0xFF,
    ], dtype=np.uint8)


def _trace_strokes(
    candidates: List[Tuple[int, int, np.ndarray, np.ndarray]],
    height: int,
    width: int,
    background_rgb: np.ndarray,
    stroke_min_length: Optional[int] = None,
) -> Dict[Tuple[int, int], np.ndarray]:
    """
    Trace chains of candidate line cells across the grid (8-neighbour).

    Each candidate cell carries TWO possible line colors — its dominant and
    its second (runner-up) color — because a thin line can be either the
    majority or the minority color of the cell it crosses. A neighbour joins
    a chain when ANY of its two candidate colors is within
    ``_STROKE_LINE_DELTAE`` (ΔE00) of ANY color the chain has accumulated so
    far; this lets the chain follow a line whose dominant/second sides
    alternate between cells (thick line → dominant, thin line → second).

    After a chain is fully grown, its line color is the candidate color
    supported by the most chain cells (present within ``_STROKE_LINE_DELTAE``
    of a cell's dominant or second color), tie-broken by the candidate
    FARTHEST from the global background (see :func:`_chain_line_color`).
    Chains spanning ``>= stroke_min_length`` cells are real strokes: every
    cell in the chain maps to that line color. Shorter chains (scattered
    noise) are left untouched but still marked visited so they are never
    re-expanded from another seed.

    :param candidates: List of ``(y, x, dominant, second)`` candidate cells
        (grid coordinates; both colors are uint8 ``(3,)`` arrays).
    :param height: Grid height in cells.
    :param width: Grid width in cells.
    :param background_rgb: Most-frequent color of the whole source image
        (uint8 ``(3,)``) — used only to break support ties between the line
        color and the background.
    :param stroke_min_length: Minimum chain length for a real stroke (default
        ``EdgeConfig().stroke_min_length``).
    :return: ``{(y, x): line_color}`` for every cell that belongs to a chain
        of length ``>= stroke_min_length``.
    :rtype: dict
    """
    from beadstudio.core.convert import _STROKE_LINE_DELTAE  # noqa: PLC0415
    if stroke_min_length is None:
        stroke_min_length = EdgeConfig().stroke_min_length
    by_pos: Dict[Tuple[int, int], Tuple[np.ndarray, np.ndarray]] = {
        (y, x): (dominant, second) for y, x, dominant, second in candidates
    }
    visited = set()
    result: Dict[Tuple[int, int], np.ndarray] = {}

    def _chain_key(color: np.ndarray) -> Tuple[int, int, int]:
        return (int(color[0]), int(color[1]), int(color[2]))

    for y0, x0, d0, s0 in candidates:
        if (y0, x0) in visited:
            continue
        chain = [(y0, x0)]
        visited.add((y0, x0))
        # Colors seen along the chain so far (seed = this cell's pair).
        chain_colors = {_chain_key(d0), _chain_key(s0)}
        stack = [(y0, x0)]
        while stack:
            cy, cx = stack.pop()
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dy == 0 and dx == 0:
                        continue
                    ny, nx = cy + dy, cx + dx
                    if not (0 <= ny < height and 0 <= nx < width):
                        continue
                    key = (ny, nx)
                    if key in visited or key not in by_pos:
                        continue
                    nd, ns = by_pos[key]
                    joins = any(
                        _deltae00_between(cc, nd) <= _STROKE_LINE_DELTAE
                        or _deltae00_between(cc, ns) <= _STROKE_LINE_DELTAE
                        for cc in chain_colors
                    )
                    if joins:
                        visited.add(key)
                        chain.append(key)
                        chain_colors.add(_chain_key(nd))
                        chain_colors.add(_chain_key(ns))
                        stack.append(key)
        if len(chain) >= stroke_min_length:
            line_color = _chain_line_color(chain, by_pos, background_rgb)
            for key in chain:
                result[key] = line_color

    return result
