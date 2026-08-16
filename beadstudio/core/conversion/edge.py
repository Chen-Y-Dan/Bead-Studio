"""
Per-cell dominant-color extraction, colour clustering, and edge detection.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np

from beadstudio.core.models import EdgeConfig

from .color import srgb_to_lab

# ---------------------------------------------------------------------------
# Dominant color per cell (most frequent, not mean — avoids gray halos)
# ---------------------------------------------------------------------------

def _top2_colors(
    region_rgb: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, float]:
    """
    Find the two most frequent colors in an image region.

    Uses the same uint8-packing trick as :func:`_dominant_color_cell` (pack
    RGB into a 24-bit int, ``np.unique(return_counts=True)``), so a single
    histogram pass yields both the dominant and the runner-up color.

    :param region_rgb: Image region array, shape ``(h, w, 3)`` (uint8 or
        float64 in 0-255).
    :return: ``(dominant, second, second_fraction)`` — ``dominant`` and
        ``second`` are uint8 ``(3,)`` arrays and ``second_fraction`` =
        ``count(second) / count(all)`` in ``[0, 1]``. When the region has a
        single distinct color (or is empty), ``second`` equals ``dominant``
        and ``second_fraction`` is ``0.0``.
    :rtype: tuple
    """
    region_rgb = np.asarray(region_rgb, dtype=np.uint8)
    flat = region_rgb.reshape(-1, 3)
    if flat.shape[0] == 0:
        empty = np.zeros(3, dtype=np.uint8)
        return empty, empty, 0.0
    # Pack RGB into single 24-bit int for fast unique counting
    packed = (flat[:, 0].astype(np.uint32) << 16) | \
             (flat[:, 1].astype(np.uint32) << 8) | \
             flat[:, 2].astype(np.uint32)
    values, counts = np.unique(packed, return_counts=True)
    # Stable sort by count desc: ties keep ascending packed order (the same
    # winner as the old ``counts.argmax()`` first-maximum rule).
    order = np.argsort(-counts, kind="stable")
    dominant = values[order[0]]
    dominant_rgb = np.array([
        (dominant >> 16) & 0xFF,
        (dominant >> 8) & 0xFF,
        dominant & 0xFF,
    ], dtype=np.uint8)
    if values.shape[0] > 1:
        second = values[order[1]]
        second_rgb = np.array([
            (second >> 16) & 0xFF,
            (second >> 8) & 0xFF,
            second & 0xFF,
        ], dtype=np.uint8)
        second_fraction = float(counts[order[1]]) / float(flat.shape[0])
    else:
        second_rgb = dominant_rgb
        second_fraction = 0.0
    return dominant_rgb, second_rgb, second_fraction


def _top_clusters(
    region_rgb: np.ndarray,
    cluster_deltae: Optional[float] = None,
    top_n: Optional[int] = None,
    stroke_min_fraction: Optional[float] = None,
) -> Tuple[np.ndarray, np.ndarray, float, float]:
    """
    Find the dominant and second COLOR CLUSTERS in an image region.

    A "cluster" groups all distinct colors within ``cluster_deltae`` (ΔE00)
    of a representative color. This is the stroke-detection fix for real
    photos: JPEG/anti-aliasing spreads a thin line's color across many
    near-identical shades, so no SINGLE shade reaches the fraction gate even
    though the line's TOTAL coverage does. Clustering sums those shades so a
    12.5% line spread across dozens of near-white shades becomes a 12.5%
    second cluster.

    Clusters are built GREEDILY over every examined distinct color (not just
    a small top-N): colors are processed most-frequent first and each color
    joins the first existing cluster whose representative is within
    ``cluster_deltae`` of it, otherwise it seeds a new cluster. Because a
    color within ``cluster_deltae`` of an existing representative always
    joins instead of seeding, every cluster representative is ``>
    cluster_deltae`` from every earlier representative — so the second
    cluster (the largest non-dominant one) is automatically far from the
    dominant cluster. The cost is O(k·c) ΔE00 evaluations (k distinct
    colors, c clusters) computed in batched vectorized calls — far cheaper
    than the O(k²) full pairwise matrix when clusters are few.

    ``top_n`` is now only a SAFETY CAP (applied AFTER the histogram) for
    pathological images whose cells contain thousands of distinct colors
    (e.g. photo gradients). The default is large enough that it never
    truncates the white population of a thin line: the real-image failing
    cells held 337-643 distinct near-white shades, so a small cap (12)
    captured just 0-6.7% of the white pixels and lost the line.

    :param region_rgb: Image region array, shape ``(h, w, 3)`` (uint8 or
        float64 in 0-255).
    :param cluster_deltae: ΔE00 radius that groups distinct colors into one
        cluster (default ``_STROKE_CLUSTER_DELTAE``).
    :param top_n: Safety cap on the number of most-frequent distinct colors
        examined (default ``_STROKE_TOP_N``).
    :param stroke_min_fraction: The stroke candidate fraction gate (default
        ``EdgeConfig().stroke_min_fraction``) — used only for the greedy
        clustering's sound early-exit bounds (a cluster cannot reach the
        gate if the dominant cluster already exceeds ``1 - fraction``).
    :return: ``(dominant_rep, second_rep, dominant_fraction,
        second_fraction)`` — the representatives are uint8 ``(3,)`` arrays
        and the fractions are cluster totals in ``[0, 1]``. ``dominant_rep``
        is the single most frequent exact color (identical to
        :func:`_top2_colors`'s dominant pick). ``second_rep`` is the
        representative of the largest non-dominant cluster; when no second
        cluster exists (or it is below 1% support) ``second_rep`` equals
        ``dominant_rep`` and ``second_fraction`` is ``0.0``.
    :rtype: tuple
    """
    # Defaults resolve at call time: the _STROKE_* constants are defined
    # later in the module, so they cannot be evaluated at def time.
    if cluster_deltae is None:
        from beadstudio.core.convert import _STROKE_CLUSTER_DELTAE  # noqa: PLC0415
        cluster_deltae = _STROKE_CLUSTER_DELTAE
    if top_n is None:
        from beadstudio.core.convert import _STROKE_TOP_N  # noqa: PLC0415
        top_n = _STROKE_TOP_N
    if stroke_min_fraction is None:
        stroke_min_fraction = EdgeConfig().stroke_min_fraction
    region_rgb = np.asarray(region_rgb, dtype=np.uint8)
    flat = region_rgb.reshape(-1, 3)
    n = flat.shape[0]
    if n == 0:
        empty = np.zeros(3, dtype=np.uint8)
        return empty, empty, 0.0, 0.0
    # Per-distinct-color histogram (uint8 packing, as _top2_colors does).
    packed = (flat[:, 0].astype(np.uint32) << 16) | \
             (flat[:, 1].astype(np.uint32) << 8) | \
             flat[:, 2].astype(np.uint32)
    values, counts = np.unique(packed, return_counts=True)
    order = np.argsort(-counts, kind="stable")
    k = min(top_n, values.shape[0])
    top_values = values[order[:k]]
    top_counts = counts[order[:k]]
    top_rgb = np.array([
        [(int(v) >> 16) & 0xFF, (int(v) >> 8) & 0xFF, int(v) & 0xFF]
        for v in top_values
    ], dtype=np.uint8)  # (k, 3), most frequent first

    # Greedy clustering over ALL examined colors. Colors are processed in
    # frequency order; each joins the first cluster whose representative is
    # within cluster_deltae (ΔE00) of it, otherwise it seeds a new cluster.
    # ΔE00 is evaluated in batched vectorized calls (all pending colors vs
    # all current representatives at once), so the whole clustering costs
    # only O(c) calls — c being the (small) number of clusters.
    from colour.difference import delta_E_CIE2000
    lab = srgb_to_lab(top_rgb)  # (k, 3), one vectorized call
    clusters: List[List[int]] = [[0]]
    reps_lab = [lab[0]]
    pending = list(range(1, k))
    while pending:
        pending_arr = np.array(pending)
        # (B, 1, 3) vs (1, c, 3) → (B, c): every pending color vs every rep.
        d = delta_E_CIE2000(
            lab[pending_arr][:, np.newaxis, :],
            np.asarray(reps_lab)[np.newaxis, :, :],
        )
        near = d.min(axis=1) <= cluster_deltae
        still_far: List[int] = []
        for is_near, color, row in zip(near, pending, d):
            if is_near:
                clusters[int(row.argmin())].append(color)
            else:
                still_far.append(color)
        if not still_far:
            break
        # Recompute the current dominant-cluster fraction and the largest
        # non-dominant cluster total — clusters just absorbed pending colors
        # this iteration, so these are the true final totals of the clusters
        # built so far (a still-unassigned color is by definition far from
        # every current representative and can never join them later).
        dom_fraction = float(top_counts[clusters[0]].sum()) / float(n)
        best_fraction = 0.0
        for cl in clusters[1:]:
            fraction = float(top_counts[cl].sum()) / float(n)
            if fraction > best_fraction:
                best_fraction = fraction
        # Early-exit bounds (both sound: any not-yet-built cluster can hold
        # at most the total support of the still-unassigned colors):
        #   1) The dominant cluster alone exceeds 1 - stroke_min_fraction →
        #      no other cluster can reach the gate's second-cluster fraction.
        #   2) The best non-dominant cluster is below the gate AND even ALL
        #      remaining colors in one cluster could not reach it.
        # JPEG photo boundary cells (hundreds of distinct shades, ~30 tiny
        # clusters) hit these early and never pay the full greedy cost.
        if dom_fraction > 1.0 - stroke_min_fraction:
            return top_rgb[0], top_rgb[0], dom_fraction, 0.0
        remaining = float(top_counts[still_far].sum()) / float(n)
        if best_fraction < stroke_min_fraction and remaining < stroke_min_fraction:
            return top_rgb[0], top_rgb[0], dom_fraction, 0.0
        # The first far color seeds a new cluster; the rest are re-checked
        # against it on the next iteration (they may lie within
        # cluster_deltae of it even though they are far from every earlier
        # representative).
        new_rep = still_far[0]
        clusters.append([new_rep])
        reps_lab.append(lab[new_rep])
        pending = still_far[1:]

    # Dominant cluster: the cluster of the most frequent exact color (index
    # 0, which is processed first and therefore seeds the first cluster).
    dom_rgb = top_rgb[0]
    dom_fraction = float(top_counts[clusters[0]].sum()) / float(n)

    # Second cluster: the largest non-dominant cluster. Its representative is
    # automatically > cluster_deltae from the dominant representative (see
    # the greedy rule above), so it satisfies the perceptual-distance
    # requirement; plain summed support is what the stroke gate needs.
    best_fraction = 0.0
    best_rgb = dom_rgb
    for cl in clusters[1:]:
        fraction = float(top_counts[cl].sum()) / float(n)
        if fraction > best_fraction:
            best_fraction = fraction
            best_rgb = top_rgb[cl[0]]
    # Require the second cluster to have meaningful support to exist.
    if best_fraction < 0.01:
        best_rgb = dom_rgb
        best_fraction = 0.0
    return dom_rgb, best_rgb, dom_fraction, best_fraction


def _dominant_color_cell(
    region: np.ndarray,
) -> np.ndarray:
    """
    Find the most frequent color in an image region.

    Delegates to :func:`_top2_colors` (uint8 packing for fast frequency
    counting via ``np.unique(return_counts=True)``) and returns the most
    frequent color.

    :param region: Image region array, shape ``(h, w, 3)``.
    :return: Most frequent RGB color, shape ``(3,)``.
    :rtype: numpy.ndarray
    """
    return _top2_colors(region)[0]


def _channel_range(region_rgb: np.ndarray) -> int:
    """
    Maximum per-channel range ``max(Rmax-Rmin, Gmax-Gmin, Bmax-Bmin)``.

    A cheap sRGB-space "is this cell uniform?" measure used as the first stage
    of edge-aware mean sampling. Smooth interior cells of a gradient have small
    per-channel ranges; a cell straddling a colour boundary has at least one
    channel spanning a large part of 0-255.

    :param region_rgb: RGB values in 0-255, shape ``(n, 3)`` (masked pixels).
    :return: Integer range in ``[0, 255]`` (``0`` for an empty region).
    """
    region_rgb = np.asarray(region_rgb, dtype=np.uint8)
    if region_rgb.size == 0:
        return 0
    return int((region_rgb.max(axis=0) - region_rgb.min(axis=0)).max())


def _extreme_pixel_deltae00(region_rgb: np.ndarray) -> float:
    """
    Max pairwise CIEDE2000 ``ΔE00`` among the extreme pixels of a region.

    The "extreme" pixels are the ≤6 pixels achieving each channel's maximum or
    minimum value (``argmax``/``argmin`` per channel). A hard chromatic
    boundary contains pixels whose hues are far apart in CIELAB (large
    ``ΔE00``), while a lightness-only gradient or sensor noise has near-
    identical chroma (small ``ΔE00`` even when the sRGB range is sizeable).

    :param region_rgb: RGB values in 0-255, shape ``(n, 3)`` (masked pixels).
    :return: Maximum pairwise ``ΔE00``, or ``0.0`` if fewer than 2 pixels.
    """
    region_rgb = np.asarray(region_rgb, dtype=np.uint8)
    n = region_rgb.shape[0]
    if n < 2:
        return 0.0
    extreme_indices = set()
    for ch in range(3):
        extreme_indices.add(int(np.argmin(region_rgb[:, ch])))
        extreme_indices.add(int(np.argmax(region_rgb[:, ch])))
    extreme = region_rgb[sorted(extreme_indices)]
    if extreme.shape[0] < 2:
        return 0.0
    from colour.difference import delta_E_CIE2000
    lab = srgb_to_lab(extreme)
    # Pairwise ΔE00: (k, 1, 3) vs (1, k, 3) → (k, k); the diagonal is the
    # self-distance (0), so the matrix max is the max pairwise distance.
    d = delta_E_CIE2000(lab[:, np.newaxis, :], lab[np.newaxis, :, :])
    return float(np.max(d))


# ---------------------------------------------------------------------------
# Stroke-tracking: candidate line cells + chain tracing
# ---------------------------------------------------------------------------

def _deltae00_between(rgb_a: np.ndarray, rgb_b: np.ndarray) -> float:
    """
    CIEDE2000 ``ΔE00`` between two single sRGB colors (0-255).

    :param rgb_a: sRGB color, shape ``(3,)``.
    :param rgb_b: sRGB color, shape ``(3,)``.
    :return: ``ΔE00`` distance (``>= 0``).
    """
    from colour.difference import delta_E_CIE2000
    lab_a = srgb_to_lab(np.asarray(rgb_a, dtype=np.uint8).reshape(1, 3))
    lab_b = srgb_to_lab(np.asarray(rgb_b, dtype=np.uint8).reshape(1, 3))
    d = delta_E_CIE2000(
        lab_a[np.newaxis, np.newaxis, :],  # (1, 1, 3)
        lab_b[np.newaxis, np.newaxis, :],  # (1, 1, 3)
    )
    return float(np.max(d))
