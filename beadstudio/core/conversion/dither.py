"""
Floyd-Steinberg error diffusion.
"""
from __future__ import annotations

from typing import Tuple

import numpy as np

from .matching import _nearest_one

# ---------------------------------------------------------------------------
# Floyd-Steinberg dithering
# ---------------------------------------------------------------------------


def _apply_floyd_steinberg(
    pixels: np.ndarray,
    active_mask: np.ndarray,
    palette_rgb: np.ndarray,
    palette_space: np.ndarray,
    color_space: str,
    dither_strength: float = 1.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Apply Floyd-Steinberg error diffusion.

    :param pixels: sRGB image, shape ``(h, w, 3)``.
    :param active_mask: Boolean mask of active pixels, shape ``(h, w)``.
    :param palette_rgb: Palette RGB values, shape ``(m, 3)``.
    :param palette_space: Pre-converted palette in target color space.
    :param color_space: Color space for distance.
    :param dither_strength: Diffusion strength in [0, 1].
    :return: ``(indices, output_rgb)``.
    """
    h, w = active_mask.shape
    work = pixels.astype(np.float64).copy()
    indices = np.full((h, w), -1, dtype=np.int32)
    output = np.zeros((h, w, 3), dtype=np.uint8)

    for y in range(h):
        for x in range(w):
            if not active_mask[y, x]:
                continue
            old = np.clip(work[y, x], 0, 255)
            idx = _nearest_one(old, palette_rgb, palette_space, color_space)
            new = palette_rgb[idx]
            indices[y, x] = idx
            output[y, x] = np.rint(new).clip(0, 255).astype(np.uint8)
            diff = (old - new) * dither_strength
            for dx, dy, weight in ((1, 0, 7 / 16), (-1, 1, 3 / 16), (0, 1, 5 / 16), (1, 1, 1 / 16)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and active_mask[ny, nx]:
                    work[ny, nx] += diff * weight

    return indices, output
