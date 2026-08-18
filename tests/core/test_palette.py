"""Unit tests for palette module.

Coverage: load/validate/dedup/RGB range/brand filter/missing brand error.
"""
import json
import re
from pathlib import Path

import pytest

from beadstudio.core import palette

PALETTES_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "beadstudio" / "core" / "data" / "palettes"
)


# ── list_brands ────────────────────────────────────────────────────────────

def test_list_brands_returns_at_least_8():
    """list_brands() must return >= 8 brands."""
    brands = palette.list_brands()
    assert len(brands) >= 8, f"Expected >= 8 brands, got {len(brands)}: {brands}"
    assert "hama" in brands
    assert "perler" in brands
    assert "coco" in brands


def test_list_brands_all_lowercase():
    """All brand keys should be lowercase."""
    for brand in palette.list_brands():
        assert brand == brand.lower(), f"Brand key not lowercase: {brand}"
        assert " " not in brand, f"Brand key contains space: {brand}"


# ── load_palette ───────────────────────────────────────────────────────────

def test_load_palette_has_required_fields():
    """Each palette JSON must have brand, source, license, colors."""
    for brand in palette.list_brands():
        data = palette.load_palette(brand)
        assert "brand" in data, f"{brand}: missing 'brand'"
        assert "source" in data, f"{brand}: missing 'source'"
        assert "license" in data, f"{brand}: missing 'license'"
        assert "colors" in data, f"{brand}: missing 'colors'"
        assert isinstance(data["colors"], list), f"{brand}: colors not a list"
        assert len(data["colors"]) > 0, f"{brand}: empty colors"


def test_load_palette_source_is_url():
    """Source field should be a URL."""
    for brand in palette.list_brands():
        data = palette.load_palette(brand)
        src = data["source"]
        assert src.startswith("https://"), f"{brand}: source not HTTPS URL: {src}"


def test_load_palette_license_valid_spdx():
    """License field should be a known SPDX identifier."""
    valid = {"MIT", "Apache-2.0", "GPL-3.0", "BSD-2-Clause", "BSD-3-Clause"}
    for brand in palette.list_brands():
        data = palette.load_palette(brand)
        lic = data["license"]
        assert lic in valid or lic.startswith("Apache"), (
            f"{brand}: unexpected license: {lic}"
        )


def test_load_palette_missing_brand_raises():
    """Loading a nonexistent brand raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="nonexistent"):
        palette.load_palette("nonexistent_brand_key")


# ── color validation ───────────────────────────────────────────────────────

def test_colors_have_required_fields():
    """Each color entry must have code, name, rgb."""
    for brand in palette.list_brands():
        data = palette.load_palette(brand)
        for i, c in enumerate(data["colors"]):
            assert "code" in c, f"{brand}[{i}]: missing 'code'"
            assert "name" in c, f"{brand}[{i}]: missing 'name'"
            assert "rgb" in c, f"{brand}[{i}]: missing 'rgb'"
            assert isinstance(c["code"], str), f"{brand}[{i}]: code not str"
            assert isinstance(c["name"], str), f"{brand}[{i}]: name not str"
            assert isinstance(c["rgb"], list), f"{brand}[{i}]: rgb not list"


def test_colors_rgb_in_range():
    """All RGB values must be in [0, 255]."""
    for brand in palette.list_brands():
        data = palette.load_palette(brand)
        for c in data["colors"]:
            r, g, b = c["rgb"]
            assert 0 <= r <= 255, f"{brand} {c['code']}: R={r} out of range"
            assert 0 <= g <= 255, f"{brand} {c['code']}: G={g} out of range"
            assert 0 <= b <= 255, f"{brand} {c['code']}: B={b} out of range"


def test_colors_rgb_is_3_ints():
    """RGB must be a list of exactly 3 integers."""
    for brand in palette.list_brands():
        data = palette.load_palette(brand)
        for c in data["colors"]:
            rgb = c["rgb"]
            assert len(rgb) == 3, f"{brand} {c['code']}: rgb length={len(rgb)}"
            assert all(isinstance(v, int) for v in rgb), (
                f"{brand} {c['code']}: non-int in rgb"
            )


def test_colors_no_duplicate_codes():
    """No brand should have duplicate color codes."""
    for brand in palette.list_brands():
        data = palette.load_palette(brand)
        codes = [c["code"] for c in data["colors"]]
        dupes = [c for c in set(codes) if codes.count(c) > 1]
        assert not dupes, f"{brand}: duplicate codes: {dupes}"


# ── total color count ─────────────────────────────────────────────────────

def test_total_colors_at_least_1392():
    """Sum of all colors across all brands must be >= 1392."""
    total = 0
    for brand in palette.list_brands():
        data = palette.load_palette(brand)
        total += len(data["colors"])
    assert total >= 1392, f"Total colors {total} < 1392"


# ── load_palette_subset ───────────────────────────────────────────────────

def test_load_palette_subset_by_codes():
    """Filter by code set returns only matching colors."""
    data = palette.load_palette_subset("hama", codes={"H01", "H02", "H03"})
    codes = {c["code"] for c in data["colors"]}
    assert codes == {"H01", "H02", "H03"}
    assert data["brand"] == "Hama"
    assert data["license"] == "MIT"


def test_load_palette_subset_empty_codes():
    """Filter with empty codes set returns no colors."""
    data = palette.load_palette_subset("hama", codes=set())
    assert data["colors"] == []
    assert data["brand"] == "Hama"


def test_load_palette_subset_none_is_all():
    """No filter returns all colors."""
    full = palette.load_palette("perler")
    subset = palette.load_palette_subset("perler")
    assert len(subset["colors"]) == len(full["colors"])


# ── JSON file integrity ────────────────────────────────────────────────────

def test_all_palette_files_valid_json():
    """Every .json file in palettes/ must be valid JSON."""
    for json_file in PALETTES_DIR.glob("*.json"):
        with open(json_file, encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, dict), f"{json_file.name}: not a JSON object"
        assert "brand" in data, f"{json_file.name}: missing 'brand'"


def test_palette_file_count_at_least_8():
    """There must be >= 8 palette JSON files."""
    json_files = list(PALETTES_DIR.glob("*.json"))
    assert len(json_files) >= 8, f"Only {len(json_files)} palette files found"


# ── get_series ─────────────────────────────────────────────────────────────

def test_get_series_mard():
    """mard must expose its 15 letter prefixes in sorted order."""
    assert palette.get_series("mard") == [
        "A", "B", "C", "D", "E", "F", "G", "H",
        "M", "P", "Q", "R", "T", "Y", "ZG",
    ]


def test_get_series_flat_perler():
    """Flat brands (no series concept) return an empty list."""
    assert palette.get_series("perler") == []


def test_get_series_excluded_artkal_c():
    """artkal_c is explicitly excluded from the series feature."""
    assert palette.get_series("artkal_c") == []


# ── filter_by_series ───────────────────────────────────────────────────────

def _color_prefixes(data):
    """Leading alphabetic prefix of every color code in a palette dict."""
    return {re.match(r"[A-Za-z]+", c["code"]).group() for c in data["colors"]}


def test_filter_by_series_mard_max_M():
    """Spec 'M' keeps only prefixes alphabetically <= 'M' (A..M, no P+)."""
    data = palette.filter_by_series("mard", "M")
    got = _color_prefixes(data)
    assert got <= {"A", "B", "C", "D", "E", "F", "G", "H", "M"}
    assert not got & {"P", "Q", "R", "T", "Y", "ZG"}
    assert len(data["colors"]) == 221
    assert data["brand"] == palette.load_palette("mard")["brand"]


def test_filter_by_series_range():
    """'A-G' and 'A..G' both keep only prefixes A..G."""
    for spec in ("A-G", "A..G"):
        data = palette.filter_by_series("mard", spec)
        assert _color_prefixes(data) == {"A", "B", "C", "D", "E", "F", "G"}
        assert len(data["colors"]) == 183


def test_filter_by_series_all():
    """'全部' returns the full palette unchanged."""
    full = palette.load_palette("mard")
    data = palette.filter_by_series("mard", "全部")
    assert data["colors"] == full["colors"]
    assert len(data["colors"]) == len(full["colors"])


def test_filter_by_series_artkal_s_main_only():
    """artkal_s spec 'S' keeps only the main S series, not SE/SG/SL/..."""
    data = palette.filter_by_series("artkal_s", "S")
    assert _color_prefixes(data) == {"S"}
    assert len(data["colors"]) == 159


def test_filter_by_series_flat_unchanged():
    """Flat brands ignore the spec and return the full palette."""
    full = palette.load_palette("perler")
    data = palette.filter_by_series("perler", "M")
    assert data["colors"] == full["colors"]
    assert len(data["colors"]) == len(full["colors"])


def test_filter_by_series_invalid():
    """Unknown prefix or non-letter spec raises a ValueError."""
    with pytest.raises(ValueError, match="series"):
        palette.filter_by_series("mard", "ZZ")
    with pytest.raises(ValueError, match="series"):
        palette.filter_by_series("mard", "1")
