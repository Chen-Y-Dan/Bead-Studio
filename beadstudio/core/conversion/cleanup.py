"""
Region cleanup (BFS small-region merge) and color-count limiting.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

# ---------------------------------------------------------------------------
# BFS region cleanup (merge small regions)
# ---------------------------------------------------------------------------

def _bfs_region_cleanup(
    indices: np.ndarray,
    active_mask: np.ndarray,
    min_region_size: int = 4,
    connectivity: int = 4,
    color_tolerance: float = 0.0,
    palette_lab: Optional[np.ndarray] = None,
) -> np.ndarray:
    """
    Merge regions smaller than ``min_region_size`` into a neighbouring color
    using BFS.

    Ported from pypindou's ``merge_small_regions()``. With the default
    ``color_tolerance=0.0`` the merge target is the most frequent neighbouring
    color and the behaviour is byte-identical to the legacy pipeline.

    When ``color_tolerance > 0`` (tolerance-aware merging):
      * the effective minimum region size becomes adaptive —
        ``max(4, min(h, w) // 10)`` — regardless of the caller's
        ``min_region_size``;
      * the merge target is the neighbour with the smallest palette colour
        distance (Euclidean in CIE L*a*b*) instead of the most frequent one;
      * a small region whose nearest neighbour is farther than
        ``color_tolerance`` is treated as a structural boundary (e.g. a contour)
        and is **preserved**, not merged. This absorbs subtle lighting/gradient
        variation within a surface while keeping true contours intact.

    :param indices: Palette index grid, ``-1`` for empty.
    :param active_mask: Boolean active mask.
    :param min_region_size: Minimum region size in cells (ignored when
        ``color_tolerance > 0``).
    :param connectivity: 4 or 8.
    :param color_tolerance: Lab distance threshold; ``0.0`` (default) = legacy
        most-frequent merge.
    :param palette_lab: Palette colours in CIE L*a*b*, shape ``(m, 3)`` (e.g.
        ``srgb_to_lab`` on the palette RGB). Required when
        ``color_tolerance > 0``.
    :return: Cleaned indices.
    """
    current = np.asarray(indices, dtype=np.int32).copy()
    active = np.asarray(active_mask, dtype=bool)
    h, w = current.shape

    if color_tolerance > 0:
        if palette_lab is None:
            raise ValueError("color_tolerance > 0 requires palette_lab.")
        palette_lab = np.asarray(palette_lab, dtype=np.float64)
        min_region_size = max(4, min(h, w) // 10)

    if min_region_size <= 1:
        return np.asarray(indices, dtype=np.int32).copy()

    if connectivity == 4:
        offsets = ((1, 0), (-1, 0), (0, 1), (0, -1))
    else:
        offsets = ((1, 0), (-1, 0), (0, 1), (0, -1),
                   (1, 1), (1, -1), (-1, 1), (-1, -1))

    visited = np.zeros((h, w), dtype=bool)
    for y in range(h):
        for x in range(w):
            if visited[y, x] or not active[y, x] or current[y, x] < 0:
                continue

            color = int(current[y, x])
            stack = [(y, x)]
            visited[y, x] = True
            component = []
            neighbor_colors = []

            while stack:
                cy, cx = stack.pop()
                component.append((cy, cx))
                for dx, dy in offsets:
                    ny, nx = cy + dy, cx + dx
                    if not (0 <= ny < h and 0 <= nx < w):
                        continue
                    if not active[ny, nx] or current[ny, nx] < 0:
                        continue
                    other = int(current[ny, nx])
                    if other == color:
                        if not visited[ny, nx]:
                            visited[ny, nx] = True
                            stack.append((ny, nx))
                    else:
                        neighbor_colors.append(other)

            if len(component) >= min_region_size or not neighbor_colors:
                continue
            if color_tolerance > 0:
                # Closest neighbour in Lab space, but only merge if that
                # distance is within tolerance. Otherwise the region is a
                # structural boundary (contour) → preserve it.
                this_lab = palette_lab[color]
                neighbors = np.unique(np.asarray(neighbor_colors, dtype=np.int32))
                dist2 = ((palette_lab[neighbors] - this_lab) ** 2).sum(axis=1)
                best = int(dist2.argmin())
                if dist2[best] > color_tolerance * color_tolerance:
                    continue
                replacement = int(neighbors[best])
            else:
                counts = np.bincount(np.asarray(neighbor_colors, dtype=np.int32))
                replacement = int(counts.argmax())
            for cy, cx in component:
                current[cy, cx] = replacement
    return current


# ---------------------------------------------------------------------------
# Color-count limiting (merge rarest colors until ≤ max_colors remain)
# ---------------------------------------------------------------------------

def _merge_rare_colors(
    indices: np.ndarray,
    active_mask: np.ndarray,
    palette_space: np.ndarray,
    max_colors: int,
) -> np.ndarray:
    """
    Reduce the number of distinct used palette colors to ``<= max_colors``.

    Post-palette-match merge: repeatedly take the used color with the fewest
    active cells and remap every one of its cells to the nearest *other* used
    color (Euclidean distance in ``palette_space``, i.e. the target color
    space — CIE Lab / OKLab — for perceptual similarity). Ties are broken by
    lowest palette index, keeping the result fully deterministic.

    Inactive cells stay at ``-1``; only ``max_colors >= 1`` makes sense here
    (the caller validates).

    :param indices: Palette index grid, ``-1`` for empty cells.
    :param active_mask: Boolean active mask.
    :param palette_space: Palette coordinates in the target color space,
        shape ``(m, 3)`` (e.g. ``srgb_to_lab`` output for ``cie2000``).
    :param max_colors: Maximum number of distinct used colors to keep.
    :return: New index grid with ``<= max_colors`` distinct used colors.
    :rtype: numpy.ndarray
    """
    current = np.asarray(indices, dtype=np.int32).copy()
    valid = (current >= 0) & np.asarray(active_mask, dtype=bool)
    flat = current[valid]
    if flat.size == 0:
        return current

    m = palette_space.shape[0]
    # Pairwise squared distances between palette colors, in the target space.
    dist2 = ((palette_space[:, None, :] - palette_space[None, :, :]) ** 2).sum(axis=2)

    while True:
        used = np.unique(flat)
        if used.size <= max_colors:
            break
        counts = np.bincount(flat, minlength=m)
        # Rarest color: lowest count; ties → lowest palette index (argmin).
        rarest = used[np.argmin(counts[used])]
        others = used[used != rarest]
        target = others[np.argmin(dist2[rarest, others])]
        flat[flat == rarest] = target

    current[valid] = flat
    return current
