"""Palette module: load and query bead color palettes.

Data sourced from:
  - beadcolors (MIT): https://github.com/maxcleme/beadcolors
  - pindou-color-data (Apache-2.0): https://github.com/HansBug/pindou-color-data

Public API
----------
    load_palette(brand: str) -> dict
        Load a single brand's full palette dict (brand, source, license, colors).

    list_brands() -> list[str]
        Return all available brand keys.

    load_palette_subset(brand: str, codes: set[str] | None = None,
                        groups: set[str] | None = None) -> dict
        Load a palette filtered to a subset of color codes and/or groups.

    get_series(brand: str) -> list[str]
        Return the sorted distinct letter prefixes of a series brand's
        color codes (empty list for flat brands).

    filter_by_series(brand: str, series_spec: str) -> dict
        Load a palette restricted to a range of letter series
        (e.g. "M" = A..M, "A-G" / "A..G" = A..G, "全部" = all).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, List, Tuple

_PALETTES_DIR = Path(__file__).resolve().parent / "data" / "palettes"

# ---------------------------------------------------------------------------
# Perler bead palette (103 colors) — single source of truth.
# Loaded ONCE from data/palettes/perler.json at import time; the JSON order
# is the canonical order and is preserved exactly. pipeline.py and export.py
# derive their perler data from this constant.
# ---------------------------------------------------------------------------


def _load_perler_colors() -> List[Tuple[str, Tuple[int, int, int]]]:
    """Load ``(code, (r, g, b))`` tuples from perler.json, in JSON order."""
    path = _PALETTES_DIR / "perler.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return [(c["code"], tuple(c["rgb"])) for c in data["colors"]]


PERLER_COLORS: List[Tuple[str, Tuple[int, int, int]]] = _load_perler_colors()


def _palette_path(brand: str) -> Path:
    """Resolve a brand key to its JSON file path."""
    path = _PALETTES_DIR / f"{brand}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Palette not found: '{brand}'. Available: {list_brands()}"
        )
    return path


def list_brands() -> list[str]:
    """Return all available brand keys, sorted alphabetically.

    Returns
    -------
    list[str]
        Brand keys matching the JSON filenames (without .json extension).
    """
    if not _PALETTES_DIR.exists():
        return []
    return sorted([
        f.stem for f in _PALETTES_DIR.glob("*.json") if f.is_file()
    ])


def load_palette(brand: str) -> dict[str, Any]:
    """Load a full palette dict for a single brand.

    Parameters
    ----------
    brand : str
        Brand key (e.g. "hama", "perler", "coco").

    Returns
    -------
    dict
        Palette dict with keys: ``brand``, ``source``, ``license``, ``colors``.
        ``colors`` is a list of ``{"code": str, "name": str, "rgb": [R,G,B]}``.

    Raises
    ------
    FileNotFoundError
        If the brand key does not match any palette file.
    """
    path = _palette_path(brand)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_palette_subset(
    brand: str,
    codes: set[str] | None = None,
    groups: set[str] | None = None,
) -> dict[str, Any]:
    """Load a palette filtered to a subset of colors.

    Parameters
    ----------
    brand : str
        Brand key.
    codes : set[str] | None
        If provided, only return colors whose ``code`` is in this set.
    groups : set[str] | None
        If provided, only return colors whose ``group`` is in this set
        (only for pindou-derived palettes that have a ``group`` field).

    Returns
    -------
    dict
        Same shape as :func:`load_palette` but ``colors`` is filtered.
    """
    palette = load_palette(brand)
    filtered = palette["colors"]

    if codes is not None:
        filtered = [c for c in filtered if c["code"] in codes]

    if groups is not None:
        filtered = [
            c for c in filtered
            if c.get("group") is not None and c["group"] in groups
        ]

    return {
        "brand": palette["brand"],
        "source": palette["source"],
        "license": palette["license"],
        "colors": filtered,
    }


# ── series ranges ───────────────────────────────────────────────────────────

# Brands whose color codes are structured as letter series (e.g. MARD "A1").
# All other brands are treated as flat and have no series concept.
_SERIES_BRANDS = frozenset({
    "mard", "mard_291", "coco", "manman", "artkal_m", "artkal_s",
})

# Specs that mean "no restriction" (full palette).
_ALL_SPEC_VALUES = {"全部", "all"}

# Leading alphabetic prefix of a color code: "A1" -> "A", "ZG1" -> "ZG",
# "H01" -> "H", "80-15201" -> no match (flat/numeric codes).
_PREFIX_RE = re.compile(r"[A-Za-z]+")

_RANGE_RE = re.compile(r"([A-Z]+)(?:\.\.|-)([A-Z]+)")


def _palette_with_colors(
    palette: dict[str, Any], colors: list[Any]
) -> dict[str, Any]:
    """Build a palette dict with the same shape as :func:`load_palette`."""
    return {
        "brand": palette["brand"],
        "source": palette["source"],
        "license": palette["license"],
        "colors": colors,
    }


@lru_cache(maxsize=None)
def get_series(brand: str) -> list[str]:
    """Return the sorted distinct letter prefixes of a brand's color codes.

    Parameters
    ----------
    brand : str
        Brand key (e.g. "mard", "coco").

    Returns
    -------
    list[str]
        Distinct leading-alphabetic prefixes, sorted, e.g. for ``mard``:
        ``["A", ..., "Y", "ZG"]``. Empty list for flat brands (perler,
        hama, ...) and for series-excluded brands (artkal_c, youken).

    Notes
    -----
    Results are cached per brand. Prefix extraction matches leading
    alphabetic characters only ("A1" -> "A", "H01" -> "H"); codes with no
    alphabetic prefix (e.g. "80-15201") contribute no series.
    """
    if brand not in _SERIES_BRANDS:
        return []
    palette = load_palette(brand)
    prefixes: set[str] = set()
    for color in palette["colors"]:
        match = _PREFIX_RE.match(color["code"])
        if match:
            prefixes.add(match.group())
    return sorted(prefixes)


def filter_by_series(brand: str, series_spec: str) -> dict[str, Any]:
    """Load a palette restricted to a range of letter series.

    Parameters
    ----------
    brand : str
        Brand key.
    series_spec : str
        One of:
        - a single prefix, e.g. ``"M"``: keep every series whose prefix is
          alphabetically <= ``"M"`` (A..M for mard; sub-series such as
          "SE" are excluded because "SE" > "S");
        - a range, e.g. ``"A-G"`` or ``"A..G"``: keep prefixes in [A, G];
        - ``"全部"`` / ``"all"`` / ``""``: full palette (no restriction).

    Returns
    -------
    dict
        Same shape as :func:`load_palette` but ``colors`` is filtered to the
        series range. For flat brands the full palette is returned unchanged.

    Raises
    ------
    ValueError
        If the spec is not alphabetic, or a single-prefix spec does not
        match any series of the brand (message in Chinese, listing valid
        series).
    """
    palette = load_palette(brand)

    if brand not in _SERIES_BRANDS:
        return _palette_with_colors(palette, palette["colors"])

    raw = series_spec.strip()
    spec = raw.upper()
    if not raw or raw in _ALL_SPEC_VALUES or spec == "ALL":
        return _palette_with_colors(palette, palette["colors"])

    series = get_series(brand)

    range_match = _RANGE_RE.fullmatch(spec)
    if range_match:
        low, high = range_match.group(1), range_match.group(2)
        keep = [p for p in series if low <= p <= high]
    else:
        if not spec.isalpha():
            raise ValueError(
                f"无效的系列参数：'{series_spec}'，应为字母系列或范围"
                "（如 'M'、'A-G'、'A..G'、'全部'）"
            )
        if spec not in series:
            raise ValueError(
                f"品牌 '{brand}' 不存在系列 '{series_spec}'，"
                f"可用系列：{'、'.join(series)}"
            )
        keep = [p for p in series if p <= spec]

    keep_set = set(keep)
    filtered = [
        c for c in palette["colors"]
        if (m := _PREFIX_RE.match(c["code"])) and m.group() in keep_set
    ]
    return _palette_with_colors(palette, filtered)
