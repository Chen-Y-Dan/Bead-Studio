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

_log = logging.getLogger(__name__)

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
# Perler bead palette (103 colors, sourced from beadcolors-perler)
# Each entry: (code, (R, G, B))
# ---------------------------------------------------------------------------
PERLER_COLORS: List[Tuple[str, Tuple[int, int, int]]] = [
    ("80-15179", (48, 85, 69)),
    ("80-15181", (179, 186, 184)),
    ("80-15182", (175, 159, 206)),
    ("80-15199", (0, 143, 83)),
    ("80-15200", (0, 101, 177)),
    ("80-15201", (47, 60, 85)),
    ("80-15202", (169, 205, 213)),
    ("80-15203", (242, 175, 183)),
    ("80-15204", (225, 116, 122)),
    ("80-15205", (201, 163, 133)),
    ("80-15206", (148, 161, 157)),
    ("80-15207", (79, 89, 90)),
    ("80-15208", (222, 218, 206)),
    ("80-15210", (177, 98, 142)),
    ("80-15211", (209, 67, 55)),
    ("80-15212", (217, 89, 58)),
    ("80-15213", (245, 161, 104)),
    ("80-15214", (216, 228, 124)),
    ("80-15215", (147, 176, 189)),
    ("80-15216", (74, 192, 216)),
    ("80-15217", (0, 164, 172)),
    ("80-15218", (4, 127, 138)),
    ("80-15219", (127, 151, 26)),
    ("80-15220", (105, 110, 49)),
    ("80-15961", (157, 43, 58)),
    ("80-19001", (234, 239, 238)),
    ("80-19002", (225, 226, 187)),
    ("80-19003", (231, 206, 62)),
    ("80-19004", (235, 123, 49)),
    ("80-19005", (176, 53, 60)),
    ("80-19006", (216, 114, 154)),
    ("80-19007", (104, 75, 134)),
    ("80-19008", (14, 80, 146)),
    ("80-19009", (39, 140, 201)),
    ("80-19010", (0, 123, 78)),
    ("80-19011", (24, 199, 177)),
    ("80-19012", (103, 76, 68)),
    ("80-19017", (144, 148, 151)),
    ("80-19018", (50, 50, 52)),
    ("80-19020", (153, 80, 67)),
    ("80-19021", (147, 104, 72)),
    ("80-19033", (233, 191, 185)),
    ("80-19035", (197, 172, 144)),
    ("80-19038", (224, 66, 132)),
    ("80-19052", (74, 156, 207)),
    ("80-19053", (109, 204, 148)),
    ("80-19054", (147, 127, 191)),
    ("80-19056", (233, 226, 144)),
    ("80-19057", (251, 177, 70)),
    ("80-19058", (150, 209, 212)),
    ("80-19059", (221, 89, 91)),
    ("80-19060", (167, 93, 157)),
    ("80-19061", (105, 184, 69)),
    ("80-19062", (0, 152, 197)),
    ("80-19063", (249, 146, 151)),
    ("80-19070", (102, 131, 183)),
    ("80-19079", (225, 188, 206)),
    ("80-19080", (77, 171, 100)),
    ("80-19083", (212, 84, 150)),
    ("80-19088", (152, 56, 100)),
    ("80-19090", (218, 153, 100)),
    ("80-19091", (0, 145, 136)),
    ("80-19092", (88, 92, 97)),
    ("80-19093", (133, 168, 227)),
    ("80-19096", (132, 57, 71)),
    ("80-19097", (187, 201, 56)),
    ("80-19098", (229, 190, 158)),
    ("80-15240", (179, 238, 213)),
    ("80-15241", (163, 222, 111)),
    ("80-15242", (244, 121, 176)),
    ("80-15243", (80, 59, 156)),
    ("80-15244", (210, 93, 114)),
    ("80-15245", (78, 86, 163)),
    ("80-15246", (253, 89, 24)),
    ("80-15247", (0, 93, 87)),
    ("80-15248", (111, 50, 85)),
    ("80-15249", (218, 140, 44)),
    ("80-15250", (126, 84, 70)),
    ("80-15251", (140, 140, 167)),
    ("80-15252", (94, 109, 123)),
    ("80-15253", (76, 99, 136)),
    ("80-15254", (154, 169, 142)),
    ("80-15255", (239, 183, 155)),
    ("80-15256", (202, 59, 101)),
    ("80-15257", (203, 89, 185)),
    ("80-15258", (113, 72, 117)),
    ("80-15259", (200, 200, 92)),
    ("80-15260", (152, 140, 140)),
    ("80-15261", (20, 49, 59)),
    ("80-15262", (57, 41, 40)),
    ("80-15265", (198, 133, 177)),
    ("80-15266", (108, 200, 173)),
    ("80-15267", (205, 183, 195)),
    ("80-15273", (252, 149, 116)),
    ("80-15274", (246, 202, 105)),
    ("80-15275", (0, 144, 172)),
    ("80-15276", (248, 199, 201)),
    ("80-15089", (64, 106, 225)),
    ("80-15268", (222, 186, 11)),
    ("80-15269", (246, 217, 1)),
    ("80-15263", (190, 212, 166)),
    ("80-15239", (200, 182, 147)),
    ("80-15272", (255, 154, 139)),
]

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
# sRGB → Linear → XYZ → Lab conversion (gamma-correct, D65 illuminant)
#
# References:
#   - Gamma: IEC 61966-2-1:1999, sRGB transfer function
#   - Matrix: Lindbloom, "RGB/XYZ Matrices" (sRGB, D65)
#     http://www.brucelindbloom.com/index.html?Eqn_RGB_XYZ_Matrix.html
#   - Lab: CIE 15:2004, CIE 1931 2° observer
# ---------------------------------------------------------------------------

# Linear sRGB → XYZ (D65) matrix (Lindbloom, sRGB)
_SRGB_TO_XYZ = np.array([
    [0.4124564, 0.3575761, 0.1804375],
    [0.2126729, 0.7151522, 0.0721750],
    [0.0193339, 0.1191920, 0.9503041],
], dtype=np.float64)

# XYZ → Linear sRGB (inverse, for dithering error accumulation)
_XYZ_TO_SRGB = np.array([
    [ 3.2404542, -1.5371385, -0.4985314],
    [-0.9692660,  1.8760108,  0.0415560],
    [ 0.0556434, -0.2040259,  1.0572252],
], dtype=np.float64)


def srgb_to_linear(rgb: np.ndarray) -> np.ndarray:
    """
    Apply inverse sRGB gamma (linearize).

    IEC 61966-2-1:1999 transfer function:
      C_linear = C_srgb / 12.92                    if C_srgb <= 0.04045
      C_linear = ((C_srgb + 0.055) / 1.055) ^ 2.4  otherwise

    :param rgb: sRGB values in [0, 1] range, shape (..., 3).
    :rtype: numpy.ndarray
    """
    rgb = np.asarray(rgb, dtype=np.float64)
    mask = rgb <= 0.04045
    result = np.zeros_like(rgb)
    result[mask] = rgb[mask] / 12.92
    result[~mask] = ((rgb[~mask] + 0.055) / 1.055) ** 2.4
    return result


def linear_to_srgb(rgb_linear: np.ndarray) -> np.ndarray:
    """
    Apply sRGB gamma (encode).

    :param rgb_linear: Linear RGB values, shape (..., 3).
    :rtype: numpy.ndarray
    """
    rgb_linear = np.asarray(rgb_linear, dtype=np.float64)
    mask = rgb_linear <= 0.0031308
    result = np.zeros_like(rgb_linear)
    result[mask] = rgb_linear[mask] * 12.92
    result[~mask] = 1.055 * (rgb_linear[~mask] ** (1.0 / 2.4)) - 0.055
    return result


def linear_to_xyz(rgb_linear: np.ndarray) -> np.ndarray:
    """
    Convert linear sRGB to CIE XYZ (D65, 2° observer).

    Matrix from Lindbloom (sRGB).

    :param rgb_linear: Linear sRGB, shape (..., 3).
    :rtype: numpy.ndarray
    """
    shape = rgb_linear.shape
    flat = np.asarray(rgb_linear, dtype=np.float64).reshape(-1, 3)
    xyz = flat @ _SRGB_TO_XYZ.T
    return xyz.reshape(shape)


def xyz_to_linear(xyz: np.ndarray) -> np.ndarray:
    """Convert CIE XYZ → linear sRGB."""
    shape = xyz.shape
    flat = np.asarray(xyz, dtype=np.float64).reshape(-1, 3)
    rgb = flat @ _XYZ_TO_SRGB.T
    return rgb.reshape(shape)


# D65 reference white in XYZ
_D65_XYZ = np.array([0.95047, 1.0, 1.08883], dtype=np.float64)


def xyz_to_lab(xyz: np.ndarray) -> np.ndarray:
    """
    Convert CIE XYZ to CIE L*a*b* (D65, 2° observer).

    Standard CIE 15:2004 formulas with the modified f(t) function:
      f(t) = t^(1/3)              if t > (6/29)^3
      f(t) = t / (3*(6/29)^2) + 4/29  otherwise

    :param xyz: XYZ values, shape (..., 3).
    :rtype: numpy.ndarray
    """
    xyz = np.asarray(xyz, dtype=np.float64)
    shape = xyz.shape
    flat = xyz.reshape(-1, 3)

    xn, yn, zn = _D65_XYZ
    fx = _f(flat[:, 0] / xn)
    fy = _f(flat[:, 1] / yn)
    fz = _f(flat[:, 2] / zn)

    L = 116.0 * fy - 16.0
    a = 500.0 * (fx - fy)
    b = 200.0 * (fy - fz)

    lab = np.column_stack([L, a, b])
    return lab.reshape(shape)


def _f(t: np.ndarray) -> np.ndarray:
    """CIE Lab f(t) helper function."""
    delta = 6.0 / 29.0
    threshold = delta ** 3
    result = np.where(
        t > threshold,
        np.cbrt(t),
        t / (3.0 * delta * delta) + 4.0 / 29.0,
    )
    return result


def lab_to_xyz(lab: np.ndarray) -> np.ndarray:
    """Convert CIE L*a*b* → CIE XYZ."""
    lab = np.asarray(lab, dtype=np.float64)
    shape = lab.shape
    flat = lab.reshape(-1, 3)

    L, a, b = flat[:, 0], flat[:, 1], flat[:, 2]
    fy = (L + 16.0) / 116.0
    fx = a / 500.0 + fy
    fz = fy - b / 200.0

    delta = 6.0 / 29.0

    def _f_inv(val):
        return np.where(
            val > delta,
            val ** 3,
            3.0 * delta * delta * (val - 4.0 / 29.0),
        )

    xn, yn, zn = _D65_XYZ
    x = _f_inv(fx) * xn
    y = _f_inv(fy) * yn
    z = _f_inv(fz) * zn
    return np.column_stack([x, y, z]).reshape(shape)


def srgb_to_lab(rgb_255: np.ndarray) -> np.ndarray:
    """
    Convert sRGB (0-255) to CIE L*a*b* with gamma correction.

    Pipeline: sRGB/255 → linearize (inverse gamma) → XYZ (D65) → Lab.

    :param rgb_255: uint8 sRGB array, shape (..., 3).
    :rtype: numpy.ndarray
    """
    rgb_255 = np.asarray(rgb_255, dtype=np.float64)
    linear = srgb_to_linear(rgb_255 / 255.0)
    xyz = linear_to_xyz(linear)
    return xyz_to_lab(xyz)


# ---------------------------------------------------------------------------
# OKLab conversion (Björn Ottosson, 2020)
#
# References:
#   - https://bottosson.github.io/posts/oklab/
# ---------------------------------------------------------------------------

# Linear sRGB → LMS
_M1_OKLAB = np.array([
    [ 0.4122214708, 0.5363325363, 0.0514459929],
    [ 0.2119034982, 0.6806995451, 0.1073969566],
    [ 0.0883024619, 0.2817188376, 0.6299787005],
], dtype=np.float64)

# LMS' → OKLab
_M2_OKLAB = np.array([
    [ 0.2104542553,  0.7936177850, -0.0040720468],
    [ 1.9779984951, -2.4285922050,  0.4505937099],
    [ 0.0259040371,  0.7827717662, -0.8086757660],
], dtype=np.float64)


def srgb_to_oklab(rgb_255: np.ndarray) -> np.ndarray:
    """
    Convert sRGB (0-255) to OKLab.

    :param rgb_255: uint8 sRGB array, shape (..., 3).
    :rtype: numpy.ndarray
    """
    rgb_255 = np.asarray(rgb_255, dtype=np.float64)
    linear = srgb_to_linear(rgb_255 / 255.0)
    shape = linear.shape
    flat = linear.reshape(-1, 3)
    lms = flat @ _M1_OKLAB.T
    lms_cbrt = np.cbrt(lms)
    oklab = lms_cbrt @ _M2_OKLAB.T
    return oklab.reshape(shape)


def oklab_to_srgb(oklab: np.ndarray) -> np.ndarray:
    """Convert OKLab → sRGB (0-255)."""
    oklab = np.asarray(oklab, dtype=np.float64)
    shape = oklab.shape
    flat = oklab.reshape(-1, 3)

    _M2_INV = np.linalg.inv(_M2_OKLAB)
    _M1_INV = np.linalg.inv(_M1_OKLAB)

    lms_cbrt = flat @ _M2_INV.T
    lms = lms_cbrt ** 3
    linear = lms @ _M1_INV.T
    srgb_01 = linear_to_srgb(linear.reshape(shape))
    return np.clip(np.rint(srgb_01 * 255.0), 0, 255)


# ---------------------------------------------------------------------------
# Color space conversion dispatch
# ---------------------------------------------------------------------------

def _convert_colors(rgb_255: np.ndarray, color_space: str) -> np.ndarray:
    """
    Convert sRGB (0-255) array to the specified color space.

    :param rgb_255: uint8 sRGB, shape (n, 3).
    :param color_space: ``"cie2000"``, ``"oklab"``, ``"lab"``.
    :rtype: numpy.ndarray
    """
    if color_space == "cie2000":
        return srgb_to_lab(rgb_255)
    if color_space == "oklab":
        return srgb_to_oklab(rgb_255)
    if color_space == "lab":
        return srgb_to_lab(rgb_255)
    raise ValueError(f"Unknown color_space: {color_space!r}")


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
        cluster_deltae = _STROKE_CLUSTER_DELTAE
    if top_n is None:
        top_n = _STROKE_TOP_N
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
        #   1) The dominant cluster alone exceeds 1 - _STROKE_MIN_FRACTION →
        #      no other cluster can reach the gate's second-cluster fraction.
        #   2) The best non-dominant cluster is below the gate AND even ALL
        #      remaining colors in one cluster could not reach it.
        # JPEG photo boundary cells (hundreds of distinct shades, ~30 tiny
        # clusters) hit these early and never pay the full greedy cost.
        if dom_fraction > 1.0 - _STROKE_MIN_FRACTION:
            return top_rgb[0], top_rgb[0], dom_fraction, 0.0
        remaining = float(top_counts[still_far].sum()) / float(n)
        if best_fraction < _STROKE_MIN_FRACTION and remaining < _STROKE_MIN_FRACTION:
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


def _record_stroke_candidate(
    y: int,
    x: int,
    masked_rgb: np.ndarray,
    a_range: int,
    low_eff: float,
    stroke_candidates: List[Tuple[int, int, np.ndarray, np.ndarray]],
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
    second cluster (``>= _STROKE_MIN_FRACTION``) perceptually far from the
    dominant cluster (``>= _STROKE_MIN_DELTAE``) marks the cell as a candidate
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
        (``min(_MEAN_EDGE_RANGE_LOW * scale_low, _MEAN_EDGE_MAX)``), computed
        per-image in :func:`_load_and_prepare`.
    :param stroke_candidates: List of ``(y, x, dominant, second)`` candidates
        accumulated for the post-pass (mutated in place).
    """
    if a_range < max(low_eff, _STROKE_A_RANGE_MIN):
        return
    dominant, second, _dom_fraction, second_fraction = _top_clusters(
        masked_rgb.astype(np.uint8)
    )
    if (
        second_fraction >= _STROKE_MIN_FRACTION
        and _deltae00_between(dominant, second) >= _STROKE_MIN_DELTAE
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
    # the dominant and second are >= _STROKE_MIN_DELTAE (35) apart, so at
    # most one of them can match — the grouping below stays unambiguous.
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
    Chains spanning ``>= _STROKE_MIN_LENGTH`` cells are real strokes: every
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
    :return: ``{(y, x): line_color}`` for every cell that belongs to a chain
        of length ``>= _STROKE_MIN_LENGTH``.
    :rtype: dict
    """
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
        if len(chain) >= _STROKE_MIN_LENGTH:
            line_color = _chain_line_color(chain, by_pos, background_rgb)
            for key in chain:
                result[key] = line_color

    return result


# ---------------------------------------------------------------------------
# Floyd-Steinberg dithering
# ---------------------------------------------------------------------------

def _nearest_one(
    rgb: np.ndarray,
    palette_rgb: np.ndarray,
    palette_space: np.ndarray,
    color_space: str,
) -> int:
    """Find the nearest palette index for a single RGB color."""
    rgb = np.asarray(rgb, dtype=np.float64).reshape(1, 3)

    if color_space == "cie2000":
        from colour.difference import delta_E_CIE2000
        pixel_lab = srgb_to_lab(rgb)
        result = delta_E_CIE2000(
            pixel_lab[:, np.newaxis, :],  # (1, 1, 3)
            srgb_to_lab(palette_rgb)[np.newaxis, :, :],  # (1, m, 3)
        )
        return int(result.argmin())

    pixel_space = _convert_colors(rgb, color_space)
    dist = ((palette_space - pixel_space) ** 2).sum(axis=1)
    return int(dist.argmin())


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
#        A <= _MEAN_EDGE_RANGE_LOW   → smooth interior → linear-space mean.
#        A >  _MEAN_EDGE_RANGE_HIGH  → unambiguous boundary → dominant colour.
#        otherwise                   → ambiguous zone → refined Lab decision.
#   2. Pairwise CIEDE2000 ΔE00 among the extreme (per-channel max/min) pixels:
#        ΔE00 > _MEAN_EDGE_DELTAE_THRESHOLD → real chromatic boundary → dominant.
#        otherwise                           → lightness gradient / noise → mean.

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
_MEAN_EDGE_RANGE_LOW: int = 115

# No literature precedent found (librarian research): this is a conservative
# "unambiguous boundary" fast-path heuristic. Any cell whose per-channel range
# exceeds it is treated as a definite boundary without running the Lab test.
_MEAN_EDGE_RANGE_HIGH: int = 180

# ΔE00 (CIEDE2000, CIE 142-2001): BCGSC guidance treats ΔE >= 5 as "two
# different colors"; aggressive palette merge uses 5–10. 15 sits above the
# aggressive-merge band: real chromatic boundaries land far above it, while
# lightness-only gradients in the ambiguous zone (ΔE00 ~5-12) stay on the mean
# path — keeping smooth transitions smooth without reintroducing the halo.
_MEAN_EDGE_DELTAE_THRESHOLD: float = 15.0

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
#     LOW_eff  = min(_MEAN_EDGE_RANGE_LOW  * scale_low,  _MEAN_EDGE_MAX)
#     HIGH_eff = min(_MEAN_EDGE_RANGE_HIGH * scale_high, _MEAN_EDGE_MAX)
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
# >= _STROKE_MIN_LENGTH cells are real strokes, every cell in the chain is
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
_STROKE_MIN_FRACTION: float = 0.12   # 2nd color cluster must be >= 12% of the cell
_STROKE_MIN_DELTAE: float = 35.0     # dominant vs 2nd color ΔE00 must be large
_STROKE_MIN_LENGTH: int = 5          # chain must span >= 5 cells to be a stroke
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
    ``>= _STROKE_MIN_LENGTH`` candidates (8-neighbour, cells sharing any
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
    """
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
    low_eff = min(_MEAN_EDGE_RANGE_LOW * scale_low, _MEAN_EDGE_MAX)
    high_eff = min(_MEAN_EDGE_RANGE_HIGH * scale_high, _MEAN_EDGE_MAX)

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
                            masked_rgb.astype(np.uint8)
                        )
                        grid_rgb[y, x] = dominant
                        if (
                            a_range >= stroke_gate
                            and second_fraction >= _STROKE_MIN_FRACTION
                            and _deltae00_between(dominant, second) >= _STROKE_MIN_DELTAE
                        ):
                            stroke_candidates.append((y, x, dominant, second))
                    elif a_range > low_eff:
                        # Ambiguous zone: refine with CIEDE2000 among the
                        # extreme (per-channel max/min) pixels. A real boundary
                        # has ΔE00 ≫ threshold; a lightness-only gradient or
                        # sensor noise stays under it and keeps the smooth mean.
                        if _extreme_pixel_deltae00(masked_rgb) > _MEAN_EDGE_DELTAE_THRESHOLD:
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
                        _record_stroke_candidate(y, x, masked_rgb, a_range, low_eff, stroke_candidates)
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
        strokes = _trace_strokes(stroke_candidates, height, width, background_rgb)
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
) -> Dict[str, Any]:
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
    :return: Dictionary with keys ``codes`` (grid of bead codes), ``indices``
        (grid of palette indices, -1 for empty), ``width``, ``height``,
        ``empty_count``, ``colors_used``, ``legend``.
    :rtype: dict
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

    return {
        "width": width,
        "height": height,
        "codes": codes_grid,
        "indices": indices.tolist(),
        "empty_count": empty_count,
        "colors_used": len(legend),
        "legend": legend,
    }
