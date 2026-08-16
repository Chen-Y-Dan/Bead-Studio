"""
Nearest-neighbour palette matching (CIEDE2000 / OKLab / Lab).
"""
from __future__ import annotations

import numpy as np

from .color import _convert_colors, srgb_to_lab, srgb_to_oklab

# ---------------------------------------------------------------------------
# Nearest-neighbor color matching
# ---------------------------------------------------------------------------

def nearest_indices(
    pixels: np.ndarray,
    palette_rgb: np.ndarray,
    *,
    color_space: str = "cie2000",
    chunk_size: int = 4096,
) -> np.ndarray:
    """
    Map ``(n, 3)`` sRGB pixels to nearest palette indices.

    When ``color_space="cie2000"``, uses ``colour.difference.delta_E_CIE2000()``
    with chunked vectorization to avoid OOM on large grids. ``"oklab"`` uses
    Euclidean distance in OKLab. ``"lab"`` uses Euclidean in CIE Lab.

    :param pixels: sRGB pixels (0-255), shape ``(n, 3)``.
    :param palette_rgb: Palette sRGB array, shape ``(m, 3)``.
    :param color_space: ``"cie2000"`` (default), ``"oklab"``, or ``"lab"``.
    :param chunk_size: Pixels per CIEDE2000 chunk (default 4096).
    :return: Palette indices array, shape ``(n,)``.
    :rtype: numpy.ndarray
    """
    pixels = np.asarray(pixels, dtype=np.float64).reshape(-1, 3)
    n_pixels = pixels.shape[0]

    if color_space == "cie2000":
        from colour.difference import delta_E_CIE2000
        pixel_lab = srgb_to_lab(pixels)
        palette_lab = srgb_to_lab(palette_rgb)

        indices = np.zeros(n_pixels, dtype=np.int32)
        for start in range(0, n_pixels, chunk_size):
            end = min(start + chunk_size, n_pixels)
            chunk_pixels = pixel_lab[start:end]  # (chunk, 3)

            # Vectorized: for each pixel in chunk, compute CIEDE2000 to all palette colors
            # Result shape: (chunk, m_colors)
            result = delta_E_CIE2000(
                chunk_pixels[:, np.newaxis, :],  # (chunk, 1, 3)
                palette_lab[np.newaxis, :, :],   # (1, m_colors, 3)
            )
            indices[start:end] = result.argmin(axis=1)
        return indices

    # OKLab or Lab (Euclidean distance)
    if color_space == "oklab":
        pixel_space = srgb_to_oklab(pixels)
        palette_space = srgb_to_oklab(palette_rgb)
    else:  # lab
        pixel_space = srgb_to_lab(pixels)
        palette_space = srgb_to_lab(palette_rgb)

    # Vectorized Euclidean: (n, 1, 3) - (1, m, 3) → (n, m, 3) → sum → (n, m)
    distances = ((pixel_space[:, np.newaxis, :] - palette_space[np.newaxis, :, :]) ** 2).sum(axis=2)
    return distances.argmin(axis=1).astype(np.int32)


def _nearest_one(
    rgb: np.ndarray,
    palette_rgb: np.ndarray,
    palette_space: np.ndarray,
    color_space: str,
) -> int:
    """Find the nearest palette index for a single RGB color.

    For ``cie2000`` the passed ``palette_space`` is the CIE Lab palette
    (see ``_convert_colors``), so it is used directly — the palette is
    converted once by the caller instead of being re-derived from
    ``palette_rgb`` on every pixel.
    """
    rgb = np.asarray(rgb, dtype=np.float64).reshape(1, 3)

    if color_space == "cie2000":
        from colour.difference import delta_E_CIE2000
        pixel_lab = srgb_to_lab(rgb)
        result = delta_E_CIE2000(
            pixel_lab[:, np.newaxis, :],  # (1, 1, 3)
            palette_space[np.newaxis, :, :],  # (1, m, 3) pre-converted
        )
        return int(result.argmin())

    pixel_space = _convert_colors(rgb, color_space)
    dist = ((palette_space - pixel_space) ** 2).sum(axis=1)
    return int(dist.argmin())
