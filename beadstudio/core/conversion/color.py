"""
sRGB color science: gamma transfer, XYZ, CIELAB and OKLab conversions.

Moved verbatim from ``beadstudio.core.convert`` (W3 split) — no logic changes.
"""
from __future__ import annotations

import numpy as np

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
