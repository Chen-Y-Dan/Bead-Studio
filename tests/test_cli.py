"""Tests for beadstudio.core.cli — the typer CLI surface (convert/version).

Covers the EdgeConfig exposure via 6 flags (--edge-low/high/deltae,
--stroke-frac/len/deltae): default (no flags) must preserve legacy
byte-identical behavior, a set flag must actually reach the engine, an
out-of-bounds value must fail through EdgeConfig validation, and the
LOW >= HIGH pair must be clamped instead of raising.
"""

import json
from pathlib import Path

from PIL import Image
from typer.testing import CliRunner

import beadstudio
from beadstudio.core.cli import app

runner = CliRunner()

# A 2px vertical mid-gray line on near-white: each straddled cell has a
# per-channel range of ~135, which sits in the edge-ambiguous band at
# cell_area 16 px² — so --edge-low 120 vs the default 115 changes the
# cell's sampling branch (mean mode), proving the flags reach the engine.
_BG_WHITE = (245, 245, 245)
_LINE_GRAY = (110, 110, 110)


def _make_image(path: Path, size: int = 64) -> Path:
    """Deterministic image: near-white background + 2px gray vertical line."""
    img = Image.new("RGB", (size, size), _BG_WHITE)
    px = img.load()
    for y in range(size):
        for x in range(30, 32):
            px[x, y] = _LINE_GRAY
    img.save(path)
    return path


def _convert_args(image: Path, out: Path, *extra: str) -> list:
    return [
        "convert",
        str(image),
        "--brand",
        "perler",
        "--width",
        "16",
        "--out",
        str(out),
        *extra,
    ]


def _result_json(out: Path, stem: str = "testimg") -> Path:
    return out / stem / f"{stem}_result.json"


# ---------------------------------------------------------------------------
# --version
# ---------------------------------------------------------------------------

def test_version_flag():
    """--version exits 0 and prints the current beadstudio version."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert beadstudio.__version__ in result.output


# ---------------------------------------------------------------------------
# EdgeConfig plumbing
# ---------------------------------------------------------------------------

def test_convert_defaults_edge_config_none(tmp_path):
    """No edge flags -> legacy behavior: two identical runs, byte-identical JSON."""
    img = _make_image(tmp_path / "testimg.png")
    out1 = tmp_path / "out1"
    out2 = tmp_path / "out2"
    r1 = runner.invoke(app, _convert_args(img, out1))
    assert r1.exit_code == 0, r1.output
    r2 = runner.invoke(app, _convert_args(img, out2))
    assert r2.exit_code == 0, r2.output
    j1 = _result_json(out1)
    j2 = _result_json(out2)
    assert j1.exists(), "result.json must be written"
    assert j2.exists(), "result.json must be written"
    # No edge params in effect -> deterministic identical output
    assert j1.read_bytes() == j2.read_bytes()
    data = json.loads(j1.read_text(encoding="utf-8"))
    assert data["width"] == 16
    assert data["height"] == 16


def test_convert_with_edge_low(tmp_path):
    """--edge-low 120 changes the result vs the default run (mean mode)."""
    img = _make_image(tmp_path / "testimg.png")
    out_default = tmp_path / "out_default"
    out_edge = tmp_path / "out_edge"
    base = ("--cell-color", "mean")
    r0 = runner.invoke(app, _convert_args(img, out_default, *base))
    assert r0.exit_code == 0, r0.output
    r1 = runner.invoke(app, _convert_args(img, out_edge, *base, "--edge-low", "120"))
    assert r1.exit_code == 0, r1.output
    assert _result_json(out_edge).exists()
    assert _result_json(out_edge).read_bytes() != _result_json(out_default).read_bytes()


def test_convert_invalid_edge_low(tmp_path):
    """--edge-low 300 -> EdgeConfig __post_init__ ValueError -> non-zero exit."""
    img = _make_image(tmp_path / "testimg.png")
    result = runner.invoke(
        app, _convert_args(img, tmp_path / "out", "--edge-low", "300")
    )
    assert result.exit_code != 0


def test_convert_low_high_clamp(tmp_path):
    """--edge-low 200 --edge-high 100 -> clamped (high=201), no raise."""
    img = _make_image(tmp_path / "testimg.png")
    out = tmp_path / "out"
    result = runner.invoke(
        app, _convert_args(img, out, "--edge-low", "200", "--edge-high", "100")
    )
    assert result.exit_code == 0, result.output
    assert _result_json(out).exists()


def test_convert_edge_low_255_clamps(tmp_path):
    """--edge-low 255 (valid, at the upper bound) clamps instead of raising."""
    # Unit level: low=255 with default high -> high capped at 255, low stepped
    # back to 254 so the core's low < high <= 255 invariant holds.
    from beadstudio.core.cli import _build_edge_config

    ec = _build_edge_config(255, None, None, None, None, None)
    assert ec.mean_edge_range_high == 255
    assert ec.mean_edge_range_low == 254
    assert ec.mean_edge_range_low < ec.mean_edge_range_high

    # CLI level: --edge-low 255 (default high 180) -> exit 0, no ValueError.
    img = _make_image(tmp_path / "testimg.png")
    out = tmp_path / "out"
    result = runner.invoke(app, _convert_args(img, out, "--edge-low", "255"))
    assert result.exit_code == 0, result.output
    assert _result_json(out).exists()
    # low == high == 255 both given -> still clamped within bounds, exit 0.
    out2 = tmp_path / "out2"
    result2 = runner.invoke(
        app, _convert_args(img, out2, "--edge-low", "255", "--edge-high", "255")
    )
    assert result2.exit_code == 0, result2.output
    assert _result_json(out2).exists()
