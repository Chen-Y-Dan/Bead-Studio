"""Typed domain models for the bead engine.

Transition note: ``Pattern`` is introduced as the typed return of
``convert()`` replacing ``Dict[str, Any]``. It carries a thin dict-compat
layer (``__getitem__``/``keys``) so existing callers using ``result["x"]``
keep working during the migration; this layer is TEMPORARY and will be
removed in a future version.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple
import numpy as np


@dataclass(frozen=True)
class EdgeConfig:
    """Edge-aware mean sampling & stroke-tracking tunables (GUI-adjustable).

    NOTE: ``mean_edge_range_low``/``mean_edge_range_high`` are BASE values —
    the effective thresholds are scaled by the cell area (power law, see
    ``_edge_scale`` in convert.py), so the GUI hint must say thresholds
    adapt to image size.
    """
    mean_edge_range_low: int = 115
    mean_edge_range_high: int = 180
    mean_edge_deltae_threshold: float = 15.0
    stroke_min_fraction: float = 0.12
    stroke_min_length: int = 5
    stroke_min_deltae: float = 35.0

    def __post_init__(self) -> None:
        # English messages on purpose: core stays consumer-agnostic; GUI localizes.
        if not (0 < self.mean_edge_range_low <= 255):
            raise ValueError("mean_edge_range_low must be in (0, 255]")
        if not (0 < self.mean_edge_range_high <= 255):
            raise ValueError("mean_edge_range_high must be in (0, 255]")
        if self.mean_edge_range_low >= self.mean_edge_range_high:
            raise ValueError("mean_edge_range_low must be less than mean_edge_range_high")
        if not (0 < self.mean_edge_deltae_threshold <= 50):
            raise ValueError("mean_edge_deltae_threshold must be in (0, 50]")
        if not (0 < self.stroke_min_fraction <= 1):
            raise ValueError("stroke_min_fraction must be in (0, 1]")
        if self.stroke_min_length < 3:
            raise ValueError("stroke_min_length must be >= 3")
        if not (0 < self.stroke_min_deltae <= 50):
            raise ValueError("stroke_min_deltae must be in (0, 50]")

    def as_dict(self) -> Dict[str, Any]:
        """Expose fields as a plain dict (for CLI/JSON/legacy code)."""
        return {
            "mean_edge_range_low": self.mean_edge_range_low,
            "mean_edge_range_high": self.mean_edge_range_high,
            "mean_edge_deltae_threshold": self.mean_edge_deltae_threshold,
            "stroke_min_fraction": self.stroke_min_fraction,
            "stroke_min_length": self.stroke_min_length,
            "stroke_min_deltae": self.stroke_min_deltae,
        }


@dataclass(frozen=True)
class BeadColor:
    """One palette bead color."""
    code: str
    name: str
    rgb: Tuple[int, int, int]


@dataclass(frozen=True)
class Palette:
    """A loaded brand palette."""
    brand: str
    source: str
    license: str
    colors: Tuple[BeadColor, ...]


@dataclass(frozen=True, eq=False)
class Pattern:
    """Typed result of ``convert()``.

    ``frozen=True`` prevents field re-binding (``pattern.width = x`` fails),
    but ``grid_rgb``/``active_mask`` are numpy arrays and remain mutable
    in place — this is NOT deep immutability.

    The ``__getitem__``/``keys``/``get``/``__contains__`` layer is a
    TEMPORARY dict-compat shim for the migration off ``Dict[str, Any]``;
    it will be removed.
    """
    codes: Tuple[Tuple[Optional[str], ...], ...]
    indices: Tuple[Tuple[int, ...], ...]
    width: int
    height: int
    empty_count: int
    colors_used: int
    legend: Tuple[Dict[str, Any], ...]
    grid_rgb: np.ndarray
    active_mask: np.ndarray

    # -- TEMPORARY dict-compat layer (migration only) ---------------------
    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def keys(self) -> Sequence[str]:
        return ("codes", "indices", "width", "height", "empty_count",
                "colors_used", "legend", "grid_rgb", "active_mask")

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __contains__(self, key: object) -> bool:
        return key in self.keys()

    def __eq__(self, other: object) -> bool:
        """Field-wise equality with numpy-array-aware comparison.

        The dataclass-generated ``__eq__`` compares numpy fields with ``==``,
        which raises on elementwise arrays — so equality is implemented here
        via ``np.array_equal`` for ``grid_rgb``/``active_mask``. As a side
        effect ``Pattern`` is unhashable (its numpy fields were never hashable
        under the generated ``__hash__`` either).
        """
        if not isinstance(other, Pattern):
            return NotImplemented
        for name in self.keys():
            left = getattr(self, name)
            right = getattr(other, name)
            if isinstance(left, np.ndarray):
                if not np.array_equal(left, right):
                    return False
            elif left != right:
                return False
        return True
