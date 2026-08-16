"""
Export module: render bead pattern grids to PNG charts, shopping list CSV,
shopping list PNG images, and multipage A4 PDF patterns.

Rendering uses Pillow for raster exports and reportlab for vector PDF output.

Public API
----------
    export_png(grid, palette=None, output_path=None, **opts) -> Image.Image
        Render the bead grid as a PNG chart with gridlines, color codes,
        and a legend.

    export_pdf(grid, output_path, palette=None, **opts) -> None
        Render the bead grid as a multipage A4 PDF with calibration marks,
        grid cells, color-code text, a legend, and a footer placeholder.

    shopping_list_csv(grid, palette=None, output_path=None) -> str | None
        Generate a CSV shopping list (brand,code,name,RGB,count), sorted by
        count descending, and optionally write to a file.

    shopping_list_png(grid, palette=None, output_path=None, **opts) -> Image.Image
        Render a shopping-list table image with color swatches and quantities.
"""

from __future__ import annotations

import csv
import io
import logging
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from PIL import Image, ImageDraw, ImageFont

from beadstudio.core.estimate import estimate_cost, estimate_time

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Perler hardcoded colour map (fallback when no palette JSON is supplied)
# Matches convert.PERLER_COLORS exactly.
# ---------------------------------------------------------------------------
_PERLER_RGB_MAP: Dict[str, Tuple[int, int, int]] = {
    "80-15179": (48, 85, 69),
    "80-15181": (179, 186, 184),
    "80-15182": (175, 159, 206),
    "80-15199": (0, 143, 83),
    "80-15200": (0, 101, 177),
    "80-15201": (47, 60, 85),
    "80-15202": (169, 205, 213),
    "80-15203": (242, 175, 183),
    "80-15204": (225, 116, 122),
    "80-15205": (201, 163, 133),
    "80-15206": (148, 161, 157),
    "80-15207": (79, 89, 90),
    "80-15208": (222, 218, 206),
    "80-15210": (177, 98, 142),
    "80-15211": (209, 67, 55),
    "80-15212": (217, 89, 58),
    "80-15213": (245, 161, 104),
    "80-15214": (216, 228, 124),
    "80-15215": (147, 176, 189),
    "80-15216": (74, 192, 216),
    "80-15217": (0, 164, 172),
    "80-15218": (4, 127, 138),
    "80-15219": (127, 151, 26),
    "80-15220": (105, 110, 49),
    "80-15961": (157, 43, 58),
    "80-19001": (234, 239, 238),
    "80-19002": (225, 226, 187),
    "80-19003": (231, 206, 62),
    "80-19004": (235, 123, 49),
    "80-19005": (176, 53, 60),
    "80-19006": (216, 114, 154),
    "80-19007": (104, 75, 134),
    "80-19008": (14, 80, 146),
    "80-19009": (39, 140, 201),
    "80-19010": (0, 123, 78),
    "80-19011": (24, 199, 177),
    "80-19012": (103, 76, 68),
    "80-19017": (144, 148, 151),
    "80-19018": (50, 50, 52),
    "80-19020": (153, 80, 67),
    "80-19021": (147, 104, 72),
    "80-19033": (233, 191, 185),
    "80-19035": (197, 172, 144),
    "80-19038": (224, 66, 132),
    "80-19052": (74, 156, 207),
    "80-19053": (109, 204, 148),
    "80-19054": (147, 127, 191),
    "80-19056": (233, 226, 144),
    "80-19057": (251, 177, 70),
    "80-19058": (150, 209, 212),
    "80-19059": (221, 89, 91),
    "80-19060": (167, 93, 157),
    "80-19061": (105, 184, 69),
    "80-19062": (0, 152, 197),
    "80-19063": (249, 146, 151),
    "80-19070": (102, 131, 183),
    "80-19079": (225, 188, 206),
    "80-19080": (77, 171, 100),
    "80-19083": (212, 84, 150),
    "80-19088": (152, 56, 100),
    "80-19090": (218, 153, 100),
    "80-19091": (0, 145, 136),
    "80-19092": (88, 92, 97),
    "80-19093": (133, 168, 227),
    "80-19096": (132, 57, 71),
    "80-19097": (187, 201, 56),
    "80-19098": (229, 190, 158),
    "80-15240": (179, 238, 213),
    "80-15241": (163, 222, 111),
    "80-15242": (244, 121, 176),
    "80-15243": (80, 59, 156),
    "80-15244": (210, 93, 114),
    "80-15245": (78, 86, 163),
    "80-15246": (253, 89, 24),
    "80-15247": (0, 93, 87),
    "80-15248": (111, 50, 85),
    "80-15249": (218, 140, 44),
    "80-15250": (126, 84, 70),
    "80-15251": (140, 140, 167),
    "80-15252": (94, 109, 123),
    "80-15253": (76, 99, 136),
    "80-15254": (154, 169, 142),
    "80-15255": (239, 183, 155),
    "80-15256": (202, 59, 101),
    "80-15257": (203, 89, 185),
    "80-15258": (113, 72, 117),
    "80-15259": (200, 200, 92),
    "80-15260": (152, 140, 140),
    "80-15261": (20, 49, 59),
    "80-15262": (57, 41, 40),
    "80-15265": (198, 133, 177),
    "80-15266": (108, 200, 173),
    "80-15267": (205, 183, 195),
    "80-15273": (252, 149, 116),
    "80-15274": (246, 202, 105),
    "80-15275": (0, 144, 172),
    "80-15276": (248, 199, 201),
    "80-15089": (64, 106, 225),
    "80-15268": (222, 186, 11),
    "80-15269": (246, 217, 1),
    "80-15263": (190, 212, 166),
    "80-15239": (200, 182, 147),
    "80-15272": (255, 154, 139),
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_font(size: int) -> ImageFont.FreeTypeFont:
    """Return the best available monospace/spaced font at *size* pt.

    Tries a set of common platform paths; falls back to PIL's tiny
    default bitmap font if nothing is found.
    """
    candidates: List[str] = []
    if sys.platform == "win32":
        candidates = [
            "C:\\Windows\\Fonts\\consola.ttf",
            "C:\\Windows\\Fonts\\arial.ttf",
            "C:\\Windows\\Fonts\\segoeui.ttf",
        ]
    elif sys.platform == "darwin":
        candidates = [
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/Menlo.ttc",
            "/Library/Fonts/Arial.ttf",
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
        ]

    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except (OSError, IOError):
                pass

    return ImageFont.load_default()


_CJK_FONT_CANDIDATES: List[str] = (
    [
        "C:\\Windows\\Fonts\\msyh.ttc",
        "C:\\Windows\\Fonts\\simhei.ttf",
        "C:\\Windows\\Fonts\\simsun.ttc",
    ]
    if sys.platform == "win32"
    else [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
)


def _get_cjk_font(size: int) -> ImageFont.FreeTypeFont:
    """Best-available CJK-capable TrueType font (for the Chinese info bar).

    Falls back to ``_get_font`` (which may render CJK as tofu) when no
    CJK font is installed on the system.
    """
    for path in _CJK_FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except (OSError, IOError):
                pass
    return _get_font(size)


def _build_palette_lookup(
    palette: Optional[Dict[str, Any]],
) -> Dict[str, Tuple[str, Tuple[int, int, int]]]:
    """Build ``code -> (name, rgb)`` lookup from a palette JSON dict.

    Falls back to ``_PERLER_RGB_MAP`` with the code itself as name when
    *palette* is ``None``.
    """
    lookup: Dict[str, Tuple[str, Tuple[int, int, int]]] = {}
    if palette and "colors" in palette and isinstance(palette["colors"], list):
        for c in palette["colors"]:
            if isinstance(c, dict) and "code" in c:
                code = c["code"]
                name = c.get("name", code)
                rgb = tuple(c.get("rgb", [128, 128, 128]))
                lookup[code] = (name, rgb)
    # Fill any missing codes from the hardcoded perler map
    for code, rgb in _PERLER_RGB_MAP.items():
        if code not in lookup:
            lookup[code] = (code, rgb)
    return lookup


def _resolve_grid(
    grid: Union[Dict[str, Any], List[List[Optional[str]]]],
) -> Tuple[int, int, List[List[Optional[str]]], List[Dict[str, Any]]]:
    """Accept either a ``convert()`` result (dict or ``Pattern``) or a raw
    ``codes`` 2D list.

    Returns ``(width, height, codes, legend)``, computing ``legend`` from
    scratch if the input was a raw list.
    """
    if isinstance(grid, dict) or hasattr(grid, "keys"):
        # dict, or Pattern via its TEMPORARY dict-compat layer.
        codes: List[List[Optional[str]]] = list(grid["codes"])
        w: int = grid["width"]
        h: int = grid["height"]
        legend: List[Dict[str, Any]] = list(grid.get("legend", []))
        return w, h, codes, legend

    # Raw 2D list of codes
    codes = list(grid)
    h = len(codes)
    w = len(codes[0]) if h > 0 else 0
    # Verify all rows have the same width
    for row in codes:
        if len(row) != w:
            raise ValueError("All rows in the grid must have the same width.")
    legend = _compute_legend(codes)
    return w, h, codes, legend


def _compute_legend(
    codes: List[List[Optional[str]]],
) -> List[Dict[str, Any]]:
    """Compute per-color counts, sorted by count descending, then by code."""
    counts: Counter[str] = Counter()
    for row in codes:
        for c in row:
            if c is not None:
                counts[c] += 1
    return [
        {"code": code, "count": cnt}
        for code, cnt in counts.most_common()
    ]


# ---------------------------------------------------------------------------
# Chart colours / layout constants
# ---------------------------------------------------------------------------

_BG_COLOR: Tuple[int, int, int] = (248, 248, 248)
_EMPTY_COLOR: Tuple[int, int, int] = (255, 255, 255)
_LINE_COLOR: Tuple[int, int, int] = (60, 60, 60)
_LEGEND_BG: Tuple[int, int, int] = (235, 235, 240)
_LEGEND_TEXT: Tuple[int, int, int] = (30, 30, 30)
_LEGEND_SWATCH_SIZE: int = 18
_LEGEND_ROW_H: int = 24
_LEGEND_PAD: int = 12
_LEGEND_GAP: int = 6
_LEGEND_MIN_WIDTH: int = 280

# Landscape (Mode H) layout constants — grids with max(width, height) > 90
_LANDSCAPE_TRIGGER: int = 90   # max dimension (beads) above which Mode H kicks in
_INFO_BAR_H: int = 36          # top info-bar height in px
_INDEX_MARGIN: int = 16        # top/left margin reserved for row/col index numbers
_MAJOR_STEP: int = 10          # heavy grid line + index number every N cells
_MAJOR_LINE_COLOR: Tuple[int, int, int] = (30, 30, 30)  # darker every-10th line
_BOARD_SIZE: int = 29          # fuse-bead pegboard standard (29×29 pins)
_BOARD_MIN_DIM: int = 116      # only draw 29-cell pegboard separators above this size
_LEGEND_ENTRY_W: int = 190     # horizontal-legend per-entry slot width (px)


def _text_rgb_for_fill(rgb: Tuple[int, int, int]) -> Tuple[int, int, int]:
    """Return black or white text colour for readability on *rgb* background."""
    # Perceived brightness (ITU-R BT.601 luma)
    y = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
    return (255, 255, 255) if y < 128 else (0, 0, 0)


def _rgb_str(rgb: Tuple[int, int, int]) -> str:
    return f"{rgb[0]},{rgb[1]},{rgb[2]}"


def _csv_safe(value: Any) -> Any:
    """Neutralize CSV formula-injection cells (CWE-1236).

    If *value* is a non-empty ``str`` beginning with a spreadsheet formula
    metacharacter (``=``, ``+``, ``-``, ``@``, or tab/CR variants), prefix it
    with a single quote so Excel/LibreOffice treat it as literal text.
    Non-strings (numbers, paths) and ordinary strings pass through unchanged.
    """
    if isinstance(value, str) and value and value[0] in "=+-@\t\r":
        return "'" + value
    return value


def _cell_label(code: Optional[str], cell_size: int) -> Optional[str]:
    """Return the text drawn inside a grid cell, or ``None`` when too small.

    * ``cell_size >= 14`` → full code (e.g. ``80-15201``)
    * ``cell_size`` 8-13 → condensed code, brand prefix stripped (``15201``)
    * ``cell_size < 8``  → no text (cell too small)
    """
    if code is None or cell_size < 8:
        return None
    if cell_size >= 14:
        return code
    return code.split("-")[-1] if "-" in code else code


def _format_tier_minutes(minutes: float) -> str:
    """Format estimated minutes as ``{h}h {m:02d}m`` (``{m}m`` under 1h)."""
    m = int(round(minutes))
    h, rem = divmod(m, 60)
    return f"{h}h {rem:02d}m" if h else f"{m}m"


def _build_info_bar_text(
    width: int,
    height: int,
    beads: int,
    colors: int,
    est: Dict[str, Any],
    shop_rate: float = 30,
) -> str:
    """Build the landscape info-bar summary line (Chinese).

    Shows chart size, total bead count, the three-tier assembly-time
    estimate, and the normal-tier shop cost.
    """
    cost = estimate_cost(est["minutes"]["normal"], shop_rate)
    return (
        f"图纸 {width}×{height} | 总豆数 {beads} | "
        f"估计拼装：新手 {_format_tier_minutes(est['minutes']['beginner_tier'])}"
        f"/普通 {_format_tier_minutes(est['minutes']['normal'])}"
        f"/熟练 {_format_tier_minutes(est['minutes']['expert'])}"
        f"（{shop_rate:.0f}元/时 ≈ ¥{cost:.0f}）"
    )


# ---------------------------------------------------------------------------
# Internal: PNG layout helpers
# ---------------------------------------------------------------------------

def _compute_png_layout(
    width: int,
    height: int,
    max_grid_dimension: int,
    legend_rows: int,
    legend_min_width: int = _LEGEND_MIN_WIDTH,
) -> dict:
    """Compute cell size, grid dimensions, and legend layout for a PNG chart.

    Returns a dict with keys: ``cell_size``, ``grid_w``, ``grid_h``,
    ``legend_w``, ``legend_h``, ``total_w``, ``total_h``.
    """
    max_dim = max(width, height)
    cell_size = max(10, max_grid_dimension // max_dim)
    grid_w = width * cell_size
    grid_h = height * cell_size
    legend_h = max(legend_rows * _LEGEND_ROW_H + 2 * _LEGEND_PAD, grid_h)
    legend_w = legend_min_width
    total_w = grid_w + legend_w + _LEGEND_PAD
    total_h = max(grid_h, legend_h) + _LEGEND_PAD * 2
    return {
        "cell_size": cell_size,
        "grid_w": grid_w,
        "grid_h": grid_h,
        "legend_w": legend_w,
        "legend_h": legend_h,
        "total_w": total_w,
        "total_h": total_h,
    }


def _compute_png_layout_landscape(
    width: int,
    height: int,
    max_grid_dimension: int,
    legend_count: int,
    info_bar_h: int = _INFO_BAR_H,
    index_margin: int = _INDEX_MARGIN,
) -> dict:
    """Compute Mode H (landscape) layout: info bar top, grid, legend below.

    Used when ``max(width, height) > _LANDSCAPE_TRIGGER``.  The legend is
    placed BELOW the grid (wrapping into horizontal rows), so the width is
    driven by the grid alone; the height stacks info bar + grid + legend.

    Returns a dict with keys: ``cell_size``, ``grid_w``, ``grid_h``,
    ``grid_x``, ``grid_y``, ``legend_h``, ``legend_per_row``, ``info_h``,
    ``index_margin``, ``total_w``, ``total_h``.
    """
    max_dim = max(width, height)
    cell_size = max(14, max_grid_dimension // max_dim)
    grid_w = width * cell_size
    grid_h = height * cell_size
    pad = _LEGEND_PAD

    # Legend below the grid: wrap into rows of N entries based on width
    per_row = max(1, grid_w // _LEGEND_ENTRY_W)
    rows = math.ceil(legend_count / per_row) if legend_count else 0
    legend_h = 24 + rows * _LEGEND_ROW_H + 2 * pad

    grid_x = pad + index_margin
    grid_y = info_bar_h + pad + index_margin
    total_w = grid_x + grid_w + pad
    total_h = grid_y + grid_h + pad + legend_h
    return {
        "cell_size": cell_size,
        "grid_w": grid_w,
        "grid_h": grid_h,
        "grid_x": grid_x,
        "grid_y": grid_y,
        "legend_h": legend_h,
        "legend_per_row": per_row,
        "info_h": info_bar_h,
        "index_margin": index_margin,
        "total_w": total_w,
        "total_h": total_h,
    }


def _draw_png_grid_cells(
    draw: ImageDraw.Draw,
    codes: List[List[Optional[str]]],
    lookup: Dict[str, Tuple[str, Tuple[int, int, int]]],
    width: int,
    height: int,
    cell_size: int,
    empty_color: Tuple[int, int, int],
    code_font: ImageFont.FreeTypeFont,
    x0: int = 0,
    y0: int = 0,
) -> None:
    """Draw filled grid cells with optional colour-code text.

    *x0*/*y0* offset the grid origin (landscape mode).  Every cell with a
    code keeps its normal code text.
    """
    for y in range(height):
        for x in range(width):
            code = codes[y][x]
            left, top = x0 + x * cell_size, y0 + y * cell_size
            right, bottom = left + cell_size, top + cell_size

            if code is not None and code in lookup:
                _, cell_rgb = lookup[code]
            else:
                cell_rgb = empty_color

            draw.rectangle([left, top, right - 1, bottom - 1], fill=cell_rgb)

            label = _cell_label(code, cell_size)
            if label is not None:
                text_color = _text_rgb_for_fill(cell_rgb)
                bbox = draw.textbbox((0, 0), label, font=code_font)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                tx = left + (cell_size - tw) // 2
                ty = top + (cell_size - th) // 2
                draw.text((tx, ty), label, fill=text_color, font=code_font)


def _draw_png_grid_lines(
    draw: ImageDraw.Draw,
    width: int,
    height: int,
    cell_size: int,
    grid_w: int,
    grid_h: int,
    line_color: Tuple[int, int, int],
    x0: int = 0,
    y0: int = 0,
    major_step: Optional[int] = None,
    major_color: Optional[Tuple[int, int, int]] = None,
) -> None:
    """Draw separator lines between grid cells.

    With *major_step* set (Mode H), every Nth boundary line is drawn 3px
    wide in *major_color* (defaults to *line_color*); all other lines stay
    1px.  With *major_step* = ``None`` (Mode V) every line is 1px —
    byte-identical to the legacy renderer.
    """
    for x in range(width + 1):
        px = x0 + x * cell_size
        if major_step is not None and x % major_step == 0:
            draw.line(
                [(px, y0), (px, y0 + grid_h - 1)],
                fill=major_color or line_color, width=3,
            )
        else:
            draw.line([(px, y0), (px, y0 + grid_h - 1)], fill=line_color, width=1)
    for y in range(height + 1):
        py = y0 + y * cell_size
        if major_step is not None and y % major_step == 0:
            draw.line(
                [(x0, py), (x0 + grid_w - 1, py)],
                fill=major_color or line_color, width=3,
            )
        else:
            draw.line([(x0, py), (x0 + grid_w - 1, py)], fill=line_color, width=1)


def _draw_png_grid_indices(
    draw: ImageDraw.Draw,
    width: int,
    height: int,
    cell_size: int,
    x0: int,
    y0: int,
    index_margin: int,
    index_color: Tuple[int, int, int],
    font: ImageFont.FreeTypeFont,
) -> None:
    """Draw small row/column index numbers every 10 cells in the margins."""
    for x in range(0, width, 10):
        label = str(x)
        tw = draw.textlength(label, font=font)
        tx = x0 + x * cell_size + (cell_size - tw) / 2
        draw.text((tx, y0 - index_margin + 2), label, fill=index_color, font=font)
    for y in range(0, height, 10):
        label = str(y)
        font_h = getattr(font, "size", 10)
        ty = y0 + y * cell_size + (cell_size - font_h) / 2
        draw.text((x0 - index_margin + 2, ty), label, fill=index_color, font=font)


def _draw_png_board_separators(
    draw: ImageDraw.Draw,
    width: int,
    height: int,
    cell_size: int,
    x0: int,
    y0: int,
    line_color: Tuple[int, int, int],
    board_size: int = _BOARD_SIZE,
) -> None:
    """Draw strong separator lines every *board_size* cells.

    Only meaningful for very wide grids (max_dim > _BOARD_MIN_DIM).  Each
    board covers ``(board_size × board_size)`` cells; a 3px line marks
    every board boundary.  No badges are drawn.
    """
    n_cols = math.ceil(width / board_size)
    n_rows = math.ceil(height / board_size)

    for bx in range(1, n_cols):
        px = x0 + bx * board_size * cell_size
        draw.line([(px, y0), (px, y0 + height * cell_size - 1)], fill=line_color, width=3)
    for by in range(1, n_rows):
        py = y0 + by * board_size * cell_size
        draw.line([(x0, py), (x0 + width * cell_size - 1, py)], fill=line_color, width=3)


def _draw_png_legend(
    draw: ImageDraw.Draw,
    legend: List[Dict[str, Any]],
    lookup: Dict[str, Tuple[str, Tuple[int, int, int]]],
    lx: int,
    ly: int,
    legend_w: int,
    legend_h: int,
) -> None:
    """Draw the legend panel (colour swatches, names, counts)."""
    legend_font = _get_font(12)
    legend_font_small = _get_font(10)
    swatch_size = _LEGEND_SWATCH_SIZE

    # Legend background
    draw.rectangle(
        [lx, ly, lx + legend_w - 1, ly + legend_h - 1],
        fill=_LEGEND_BG,
        outline=(180, 180, 180),
    )

    # Legend title
    title = f"Legend ({len(legend)} colours)"
    draw.text((lx + _LEGEND_PAD, ly + 4), title, fill=_LEGEND_TEXT, font=legend_font)
    row_y = ly + 28

    for entry in legend:
        code = entry["code"]
        cnt = entry["count"]
        name, rgb = lookup.get(code, (code, (128, 128, 128)))

        swatch_x = lx + _LEGEND_PAD
        draw.rectangle(
            [swatch_x, row_y, swatch_x + swatch_size - 1, row_y + swatch_size - 1],
            fill=rgb,
            outline=(120, 120, 120),
        )

        text_x = swatch_x + swatch_size + _LEGEND_GAP
        label = f"{code} — {name} ×{cnt}"
        draw.text((text_x, row_y - 1), label, fill=_LEGEND_TEXT, font=legend_font_small)

        row_y += _LEGEND_ROW_H


def _draw_png_info_bar(
    draw: ImageDraw.Draw,
    text: str,
    total_w: int,
    info_h: int,
    font: ImageFont.FreeTypeFont,
    bg: Tuple[int, int, int] = _LEGEND_BG,
    text_color: Tuple[int, int, int] = _LEGEND_TEXT,
) -> None:
    """Draw the top info bar (landscape mode)."""
    draw.rectangle([0, 0, total_w - 1, info_h - 1], fill=bg, outline=(180, 180, 180))
    font_h = getattr(font, "size", 12)
    draw.text((_LEGEND_PAD, (info_h - font_h) // 2), text, fill=text_color, font=font)


def _draw_png_legend_h(
    draw: ImageDraw.Draw,
    legend: List[Dict[str, Any]],
    lookup: Dict[str, Tuple[str, Tuple[int, int, int]]],
    lx: int,
    ly: int,
    area_w: int,
    legend_h: int,
    per_row: int,
) -> None:
    """Draw the legend below the grid (landscape mode): horizontal wrap.

    Swatches flow left-to-right with *per_row* entries per row, wrapping
    automatically into additional rows.
    """
    legend_font = _get_font(12)
    legend_font_small = _get_font(10)
    swatch_size = _LEGEND_SWATCH_SIZE

    # Legend background
    draw.rectangle(
        [lx, ly, lx + area_w - 1, ly + legend_h - 1],
        fill=_LEGEND_BG,
        outline=(180, 180, 180),
    )

    # Legend title
    title = f"Legend ({len(legend)} colours)"
    draw.text((lx + _LEGEND_PAD, ly + 4), title, fill=_LEGEND_TEXT, font=legend_font)

    row_y = ly + 26
    for i, entry in enumerate(legend):
        code = entry["code"]
        cnt = entry["count"]
        name, rgb = lookup.get(code, (code, (128, 128, 128)))

        col = i % per_row
        if i and col == 0:
            row_y += _LEGEND_ROW_H

        entry_x = lx + _LEGEND_PAD + col * _LEGEND_ENTRY_W
        draw.rectangle(
            [entry_x, row_y, entry_x + swatch_size - 1, row_y + swatch_size - 1],
            fill=rgb,
            outline=(120, 120, 120),
        )

        text_x = entry_x + swatch_size + _LEGEND_GAP
        name_short = name if len(name) <= 7 else name[:7] + "…"
        label = f"{code} {name_short} ×{cnt}"
        draw.text((text_x, row_y - 1), label, fill=_LEGEND_TEXT, font=legend_font_small)


# ---------------------------------------------------------------------------
# Public: export_png
# ---------------------------------------------------------------------------

def export_png(
    grid: Union[Dict[str, Any], List[List[Optional[str]]]],
    palette: Optional[Dict[str, Any]] = None,
    output_path: Optional[str] = None,
    *,
    max_grid_dimension: int = 900,
    legend_min_width: int = _LEGEND_MIN_WIDTH,
    bg_color: Tuple[int, int, int] = _BG_COLOR,
    empty_color: Tuple[int, int, int] = _EMPTY_COLOR,
    line_color: Tuple[int, int, int] = _LINE_COLOR,
    estimate_rate: float = 25,
    estimate_shop_rate: float = 30,
) -> Image.Image:
    """Render the bead grid as a PNG chart.

    Two layout modes are supported:

    * **Mode V (portrait, default)** — grids with ``max(width, height)
      <= 90`` keep the classic layout: grid on the left, legend panel on
      the right.
    * **Mode H (landscape)** — grids with ``max(width, height) > 90``
      switch to a landscape layout: a top info bar (chart size, total
      bead count, three-tier assembly-time estimate and shop cost),
      the full-width grid below it, and the legend wrapped in horizontal
      rows under the grid.  Every-10th grid line is drawn 3px/darker and
      row/column index numbers are printed in the margins; very wide
      grids (> 116) additionally get 29-cell pegboard separator lines.

    Parameters
    ----------
    grid : dict | list[list[str|None]]
        Either the full ``convert()`` result dict or a 2D list of bead
        colour codes (``None`` = empty / no bead).
    palette : dict | None
        Palette dict from ``palette.load_palette(brand)``.  Used for
        colour-name lookup.  Falls back to the built-in Perler map
        when ``None``.
    output_path : str | None
        If given, the image is saved to this path (PNG format).
    max_grid_dimension : int
        The maximum pixel dimension (width or height) of the grid
        drawing area.  Cell size is ``max(10, max_grid_dimension //
        max(width, height))`` (Mode V) or ``max(14, ...)`` (Mode H).
    legend_min_width : int
        Minimum pixel width reserved for the legend area (Mode V only).
    bg_color : tuple[int,int,int]
        Overall background colour.
    empty_color : tuple[int,int,int]
        Fill colour for empty/transparent cells.
    line_color : tuple[int,int,int]
        Grid-line colour.
    estimate_rate : float
        Normal-tier placement speed (beads/min) for the Mode H info bar.
    estimate_shop_rate : float
        Shop hourly rate in yuan for the Mode H info-bar cost.

    Returns
    -------
    PIL.Image.Image
        The rendered chart.  Also saved to *output_path* when provided.
    """
    width, height, codes, legend = _resolve_grid(grid)
    lookup = _build_palette_lookup(palette)
    max_dim = max(width, height)

    if max_dim > _LANDSCAPE_TRIGGER:
        # ------------------------------------------------------------------
        # Mode H: landscape — info bar top, grid full-width, legend below
        # ------------------------------------------------------------------
        lay = _compute_png_layout_landscape(
            width, height, max_grid_dimension, len(legend),
        )
        cell_size = lay["cell_size"]
        x0, y0 = lay["grid_x"], lay["grid_y"]
        code_font = _get_font(max(8, min(cell_size // 3, 14)))

        img = Image.new("RGB", (lay["total_w"], lay["total_h"]), bg_color)
        draw = ImageDraw.Draw(img)

        _draw_png_grid_cells(
            draw, codes, lookup, width, height, cell_size, empty_color,
            code_font, x0=x0, y0=y0,
        )
        _draw_png_grid_lines(
            draw, width, height, cell_size, lay["grid_w"], lay["grid_h"],
            line_color, x0=x0, y0=y0,
            major_step=_MAJOR_STEP, major_color=_MAJOR_LINE_COLOR,
        )

        # Row/column index numbers every 10 cells (in the margins)
        _draw_png_grid_indices(
            draw, width, height, cell_size, x0, y0, lay["index_margin"],
            (100, 100, 100), _get_font(8),
        )

        # 29-cell pegboard separators for very wide grids
        if max_dim > _BOARD_MIN_DIM:
            _draw_png_board_separators(
                draw, width, height, cell_size, x0, y0,
                _MAJOR_LINE_COLOR,
            )

        # Top info bar with size / bead count / time & cost estimate
        if hasattr(grid, "keys") and "empty_count" in grid:
            beads = width * height - int(grid["empty_count"])
        else:
            beads = sum(1 for row in codes for c in row if c is not None)
        colors_used = len(legend)
        est = estimate_time(beads=beads, rate=estimate_rate, colors=colors_used)
        info_text = _build_info_bar_text(
            width, height, beads, colors_used, est, estimate_shop_rate,
        )
        info_font = _get_cjk_font(14)
        while (
            info_font.size > 9
            and draw.textlength(info_text, font=info_font) > lay["total_w"] - 2 * _LEGEND_PAD
        ):
            info_font = _get_cjk_font(info_font.size - 1)
        _draw_png_info_bar(draw, info_text, lay["total_w"], lay["info_h"], info_font)

        # Legend below the grid (horizontal wrap)
        _draw_png_legend_h(
            draw, legend, lookup,
            x0, y0 + lay["grid_h"] + _LEGEND_PAD,
            lay["grid_w"], lay["legend_h"], lay["legend_per_row"],
        )
    else:
        # ------------------------------------------------------------------
        # Mode V: legacy portrait layout — grid left, legend right
        # (byte-identical to previous behaviour)
        # ------------------------------------------------------------------
        lay = _compute_png_layout(width, height, max_grid_dimension, len(legend), legend_min_width)
        cell_size, grid_w, grid_h = lay["cell_size"], lay["grid_w"], lay["grid_h"]
        lx = grid_w + _LEGEND_PAD
        ly = _LEGEND_PAD

        # Fonts
        code_font = _get_font(max(8, min(cell_size // 3, 14)))

        # Create canvas
        img = Image.new("RGB", (lay["total_w"], lay["total_h"]), bg_color)
        draw = ImageDraw.Draw(img)

        # Draw grid cells, grid lines, and legend panel
        _draw_png_grid_cells(draw, codes, lookup, width, height, cell_size, empty_color, code_font)
        _draw_png_grid_lines(draw, width, height, cell_size, grid_w, grid_h, line_color)
        _draw_png_legend(draw, legend, lookup, lx, ly, lay["legend_w"], lay["legend_h"])

    if output_path is not None:
        img.save(output_path, format="PNG")

    return img


# ---------------------------------------------------------------------------
# Public: shopping_list_csv
# ---------------------------------------------------------------------------

def shopping_list_csv(
    grid: Union[Dict[str, Any], List[List[Optional[str]]]],
    palette: Optional[Dict[str, Any]] = None,
    output_path: Optional[str] = None,
    *,
    rate: Optional[float] = None,
    shop_rate: Optional[float] = None,
    beginner: bool = False,
) -> Optional[str]:
    """Produce a CSV shopping list of beads needed for the pattern.

    Rows are sorted by count descending, then by code.  The sum of the
    **count** column always equals the number of non-empty cells in
    the grid.  When *rate* and/or *shop_rate* are provided, a summary
    block with estimated assembly time and shop cost is appended.

    Parameters
    ----------
    grid : dict | list[list[str|None]]
        Either the full ``convert()`` result dict or a 2D list of bead
        colour codes.
    palette : dict | None
        Palette dict from ``palette.load_palette(brand)`` for
        colour-name and RGB lookup.
    output_path : str | None
        If given, the CSV is written to this path (as UTF-8 text).
    rate : float | None
        Base placement speed for normal tier (beads/min).  Default 25
        when computing estimates.
    shop_rate : float | None
        Shop hourly rate in yuan.  Default 30 when computing estimates.
    beginner : bool
        When True, apply 1.5× penalty to normal-tier estimate.

    Returns
    -------
    str | None
        The CSV content as a string (only when *output_path* is ``None``).
    """
    _, _, codes, legend = _resolve_grid(grid)
    lookup = _build_palette_lookup(palette)

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["brand", "code", "name", "RGB", "count"])

    brand = palette.get("brand", "") if palette else ""

    for entry in legend:
        code = entry["code"]
        cnt = entry["count"]
        name, rgb = lookup.get(code, (code, (128, 128, 128)))
        writer.writerow([
            _csv_safe(brand),
            _csv_safe(code),
            _csv_safe(name),
            _rgb_str(rgb),
            cnt,
        ])

    # --- estimate summary block (when rate or shop_rate provided) ---
    if rate is not None or shop_rate is not None:
        total_beads = sum(1 for row in codes for c in row if c is not None)
        colors_used = len(legend)
        est_rate = rate if rate is not None else 25.0
        est_shop = shop_rate if shop_rate is not None else 30.0
        est = estimate_time(
            beads=total_beads,
            rate=est_rate,
            colors=colors_used,
            shop_rate=est_shop,
            beginner=beginner,
        )
        writer.writerow([])  # blank separator
        writer.writerow(["--- 工时与成本预估 ---"])
        writer.writerow([
            "预估时长(分)",
            f"新手级: {est['minutes']['beginner_tier']:.1f}",
            f"普通: {est['minutes']['normal']:.1f}",
            f"专家级: {est['minutes']['expert']:.1f}",
        ])
        writer.writerow([
            "预估费用(元)",
            f"新手: {est['cost']['beginner']:.1f}",
            f"普通: {est['cost']['normal']:.1f}",
            f"专家: {est['cost']['expert']:.1f}",
        ])

    result = buf.getvalue()

    if output_path is not None:
        Path(output_path).write_text(result, encoding="utf-8")
        return None

    return result


# ---------------------------------------------------------------------------
# Internal: shopping-list PNG helpers
# ---------------------------------------------------------------------------

def _compute_shopping_estimate_lines(
    codes: List[List[Optional[str]]],
    legend: List[Dict[str, Any]],
    rate: Optional[float],
    shop_rate: Optional[float],
    beginner: bool,
) -> List[str]:
    """Compute estimate summary lines for the shopping-list table."""
    if rate is None and shop_rate is None:
        return []
    total_beads = sum(1 for row in codes for c in row if c is not None)
    colors_used = len(legend)
    est_rate = rate if rate is not None else 25.0
    est_shop = shop_rate if shop_rate is not None else 30.0
    est = estimate_time(
        beads=total_beads,
        rate=est_rate,
        colors=colors_used,
        shop_rate=est_shop,
        beginner=beginner,
    )
    return [
        f"预估时长(分): 新手级 {est['minutes']['beginner_tier']:.0f}  |  普通 {est['minutes']['normal']:.0f}  |  专家级 {est['minutes']['expert']:.0f}",
        f"预估费用(元): 新手 {est['cost']['beginner']:.0f}  |  普通 {est['cost']['normal']:.0f}  |  专家 {est['cost']['expert']:.0f}  (@{est_shop:.0f}元/小时)",
    ]


def _draw_shopping_header(
    draw: ImageDraw.Draw,
    cols: List[Tuple[str, int]],
    col_x: List[int],
    header_h: int,
    table_w: int,
    header_fill: Tuple[int, int, int],
    header_font: ImageFont.FreeTypeFont,
    line_color: Tuple[int, int, int],
) -> None:
    """Draw the table header row with column titles and bottom line."""
    draw.rectangle([0, 0, table_w - 1, header_h - 1], fill=header_fill)
    for i, (label, _) in enumerate(cols):
        draw.text((col_x[i] + 4, 10), label, fill=(30, 30, 30), font=header_font)
    draw.line([(0, header_h - 1), (table_w - 1, header_h - 1)], fill=line_color)


def _draw_shopping_data_rows(
    draw: ImageDraw.Draw,
    legend: List[Dict[str, Any]],
    lookup: Dict[str, Tuple[str, Tuple[int, int, int]]],
    col_x: List[int],
    header_h: int,
    row_h: int,
    table_w: int,
    row_alt: Tuple[int, int, int],
    body_font: ImageFont.FreeTypeFont,
    line_color: Tuple[int, int, int],
) -> None:
    """Draw data rows with swatches, codes, names, and counts."""
    for row_idx, entry in enumerate(legend):
        code = entry["code"]
        cnt = entry["count"]
        name, rgb = lookup.get(code, (code, (128, 128, 128)))

        row_y = header_h + row_idx * row_h
        if row_idx % 2 == 1:
            draw.rectangle(
                [0, row_y, table_w - 1, row_y + row_h - 1], fill=row_alt,
            )
        draw.line(
            [(0, row_y + row_h - 1), (table_w - 1, row_y + row_h - 1)], fill=line_color,
        )

        swatch_size = min(row_h - 6, 20)
        swatch_y = row_y + (row_h - swatch_size) // 2
        draw.rectangle(
            [col_x[0] + 4, swatch_y, col_x[0] + 4 + swatch_size - 1, swatch_y + swatch_size - 1],
            fill=rgb, outline=(100, 100, 100),
        )
        draw.text((col_x[1] + 4, row_y + 6), code, fill=(30, 30, 30), font=body_font)
        name_short = name if len(name) <= 30 else name[:27] + "..."
        draw.text((col_x[2] + 4, row_y + 6), name_short, fill=(30, 30, 30), font=body_font)
        draw.text((col_x[3] + 4, row_y + 6), str(cnt), fill=(30, 30, 30), font=body_font)


# ---------------------------------------------------------------------------
# Public: shopping_list_png
# ---------------------------------------------------------------------------

def shopping_list_png(
    grid: Union[Dict[str, Any], List[List[Optional[str]]]],
    palette: Optional[Dict[str, Any]] = None,
    output_path: Optional[str] = None,
    *,
    bg_color: Tuple[int, int, int] = _BG_COLOR,
    rate: Optional[float] = None,
    shop_rate: Optional[float] = None,
    beginner: bool = False,
) -> Image.Image:
    """Render a shopping-list table as a PNG image.

    The table has four columns: a colour swatch, bead code, colour name,
    and quantity.  Rows are sorted by count descending.  When *rate*
    and/or *shop_rate* are provided, an estimate summary with assembly
    time and shop cost is rendered below the table.

    Parameters
    ----------
    grid : dict | list[list[str|None]]
        Either the full ``convert()`` result dict or a 2D list of bead
        colour codes.
    palette : dict | None
        Palette dict from ``palette.load_palette(brand)``.
    output_path : str | None
        If given, the image is saved to this path (PNG format).
    bg_color : tuple[int,int,int]
        Overall background colour.
    rate : float | None
        Base placement speed for normal tier (beads/min).  Default 25
        when computing estimates.
    shop_rate : float | None
        Shop hourly rate in yuan.  Default 30 when computing estimates.
    beginner : bool
        When True, apply 1.5× penalty to normal-tier estimate.

    Returns
    -------
    PIL.Image.Image
        The rendered shopping-list image.
    """
    _, _, codes, legend = _resolve_grid(grid)
    lookup = _build_palette_lookup(palette)

    # --- column layout ---
    col_swatch, col_code, col_name, col_count = 30, 120, 200, 80
    col_pad = 8
    cols = [
        ("Swatch", col_swatch), ("Code", col_code),
        ("Name", col_name), ("Count", col_count),
    ]
    col_x: List[int] = []
    x = col_pad
    for _label, w in cols:
        col_x.append(x)
        x += w + col_pad
    table_w = x
    row_h, header_h = 28, 36

    # --- estimate lines ---
    est_lines = _compute_shopping_estimate_lines(codes, legend, rate, shop_rate, beginner)
    est_section_h = len(est_lines) * 22 + 16 if est_lines else 0
    table_h = header_h + len(legend) * row_h + col_pad
    total_h = table_h + est_section_h

    header_font = _get_font(13)
    body_font = _get_font(11)
    est_font = _get_font(11)
    line_color = (180, 180, 180)
    header_fill = (220, 220, 225)
    row_alt = (245, 245, 248)

    img = Image.new("RGB", (table_w, total_h), bg_color)
    draw = ImageDraw.Draw(img)

    # Header
    _draw_shopping_header(draw, cols, col_x, header_h, table_w, header_fill, header_font, line_color)

    # Column dividers
    for i in range(len(cols)):
        px = col_x[i] - col_pad // 2
        if px > 0:
            draw.line([(px, 0), (px, table_h - 1)], fill=line_color, width=1)

    # Data rows
    _draw_shopping_data_rows(
        draw, legend, lookup, col_x, header_h, row_h, table_w,
        row_alt, body_font, line_color,
    )

    # Estimate summary below table
    if est_lines:
        sep_y = table_h + 4
        draw.line([(col_pad, sep_y), (table_w - col_pad, sep_y)], fill=(100, 100, 100), width=1)
        est_y = sep_y + 8
        for line in est_lines:
            draw.text((col_pad, est_y), line, fill=(80, 80, 80), font=est_font)
            est_y += 22

    if output_path is not None:
        img.save(output_path, format="PNG")

    return img


# ---------------------------------------------------------------------------
# PDF export (reportlab)
# ---------------------------------------------------------------------------

# reportlab imports
from reportlab.pdfgen import canvas as _rl_canvas  # noqa: E402
from reportlab.pdfbase import pdfmetrics as _pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402


# ---------------------------------------------------------------------------
# CJK font registration (for Chinese brand names in legend / footer)
# ---------------------------------------------------------------------------

_CJK_FONT_NAME: Optional[str] = None
_CJK_FONT_REGISTERED: bool = False
_FALLBACK_FONT: str = "Helvetica"


def _find_cjk_font_path() -> Tuple[Optional[str], str]:
    """Scan the system for an available CJK TrueType/OpenType font.

    Returns ``(path, display_name)`` or ``(None, "")``.
    """
    candidates: List[Tuple[str, str]] = []
    if sys.platform == "win32":
        windir = "C:\\Windows\\Fonts"
        candidates = [
            (f"{windir}\\simhei.ttf", "SimHei"),
            (f"{windir}\\msyh.ttc", "MicrosoftYaHei"),
            (f"{windir}\\msyhbd.ttc", "MicrosoftYaHeiBold"),
            (f"{windir}\\simsun.ttc", "SimSun"),
        ]
    elif sys.platform == "darwin":
        candidates = [
            ("/System/Library/Fonts/PingFang.ttc", "PingFang"),
            ("/System/Library/Fonts/STHeiti Light.ttc", "STHeiti"),
            ("/Library/Fonts/Arial Unicode.ttf", "ArialUnicodeMS"),
        ]
    else:
        candidates = [
            ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", "NotoSansCJK"),
            ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "NotoSansCJK"),
            (
                "/usr/share/fonts/truetype/droid/"
                "DroidSansFallbackFull.ttf",
                "DroidSansFallback",
            ),
        ]

    for path, name in candidates:
        if Path(path).exists():
            return path, name
    return None, ""


def _register_cjk_font() -> str:
    """Register the best-available CJK font with reportlab.

    Returns the registered font name (or ``_FALLBACK_FONT``).
    Scans once; subsequent calls return the cached name immediately.
    """
    global _CJK_FONT_NAME, _CJK_FONT_REGISTERED  # noqa: PLW0603

    if _CJK_FONT_REGISTERED:
        return _CJK_FONT_NAME or _FALLBACK_FONT

    _CJK_FONT_REGISTERED = True

    path, _display_name = _find_cjk_font_path()
    if path is not None:
        try:
            _pdfmetrics.registerFont(TTFont("CJKFont", path))
            _CJK_FONT_NAME = "CJKFont"
            return "CJKFont"
        except Exception:
            pass

    # Fallback
    _log.warning(
        "No CJK font found on the system — Chinese text in PDF "
        "will use Helvetica (may render as tofu/boxes)."
    )
    _CJK_FONT_NAME = _FALLBACK_FONT
    return _FALLBACK_FONT


# ---------------------------------------------------------------------------
# PDF layout constants (A4 = 595 × 842 points)
# ---------------------------------------------------------------------------

_A4 = (595.0, 842.0)
_PAGE_W, _PAGE_H = _A4
_MARGIN = 20.0
_CALIB_LEN = 10.0   # calibration-crosshair arm length (points)
_MIN_CELL = 10.0    # minimum cell size (points)
_TARGET_CELL = 18.0  # preferred cell size
_FOOTER_H = 35.0     # reserved vertical space at page bottom
_HEADER_TOP = 5.0    # tiny gap below top margin before grid starts

# Legend layout
_LEGEND_SWATCH_COL = 22.0
_LEGEND_CODE_COL = 90.0
_LEGEND_NAME_COL = 230.0
_LEGEND_COUNT_COL = 60.0
_LEGEND_COL_GAP = 6.0
_PDF_LEGEND_ROW_H = 18.0  # PDF-only (must not clobber PNG _LEGEND_ROW_H)
_LEGEND_FONT_SIZE = 7


# ---------------------------------------------------------------------------
# Internal PDF drawing helpers
# ---------------------------------------------------------------------------

def _draw_calibration_marks(c: _rl_canvas.Canvas) -> None:
    """Draw ±10 pt crosshair calibration marks at the four page corners."""
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.5)
    corners = [
        (_MARGIN, _MARGIN),                      # bottom-left
        (_PAGE_W - _MARGIN, _MARGIN),            # bottom-right
        (_PAGE_W - _MARGIN, _PAGE_H - _MARGIN),   # top-right
        (_MARGIN, _PAGE_H - _MARGIN),             # top-left
    ]
    path = c.beginPath()
    for cx, cy in corners:
        path.moveTo(cx - _CALIB_LEN, cy)
        path.lineTo(cx + _CALIB_LEN, cy)
        path.moveTo(cx, cy - _CALIB_LEN)
        path.lineTo(cx, cy + _CALIB_LEN)
    c.drawPath(path, stroke=1, fill=0)


def _draw_footer(
    c: _rl_canvas.Canvas,
    page_num: int,
    total_pages: int,
    estimate_text: str = "预估时长/费用: (待 T8 填入)",
) -> None:
    """Draw the bottom-of-page footer with estimate text + page nr."""
    cjk = _register_cjk_font()
    y = _MARGIN - 6.0

    # Estimate — left
    estimate_font = cjk if cjk != _FALLBACK_FONT else "Helvetica"
    c.setFont(estimate_font, 8)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    c.drawString(_MARGIN, y, estimate_text)

    # Page number — right
    page_text = f"{page_num} / {total_pages}"
    c.setFont("Helvetica", 8)
    c.drawRightString(_PAGE_W - _MARGIN, y, page_text)


def _draw_grid_page(
    c: _rl_canvas.Canvas,
    codes: List[List[Optional[str]]],
    lookup: Dict[str, Tuple[str, Tuple[int, int, int]]],
    cell_size: float,
    start_col: int,
    start_row: int,
    cols_this_page: int,
    rows_this_page: int,
    page_num: int,
    total_pages: int,
    estimate_text: str = "预估时长/费用: (待 T8 填入)",
) -> None:
    """Render one page of the bead grid with calibration marks and footer."""
    _draw_calibration_marks(c)

    grid_left = _MARGIN
    # reportlab y=0 is page bottom; we draw from top down
    grid_top_y = _PAGE_H - _MARGIN - _HEADER_TOP

    code_font_size = max(5.0, min(cell_size / 3.0, 10.0))

    for local_y in range(rows_this_page):
        global_y = start_row + local_y
        if global_y >= len(codes):
            break
        row = codes[global_y]
        for local_x in range(cols_this_page):
            global_x = start_col + local_x
            if global_x >= len(row):
                break

            code = row[global_x]
            x = grid_left + local_x * cell_size
            y = grid_top_y - (local_y + 1) * cell_size

            # Cell fill
            if code is not None and code in lookup:
                _, cell_rgb = lookup[code]
                fr, fg, fb = (
                    cell_rgb[0] / 255.0,
                    cell_rgb[1] / 255.0,
                    cell_rgb[2] / 255.0,
                )
            else:
                fr = fg = fb = 1.0  # white for empty/unknown

            c.setFillColorRGB(fr, fg, fb)
            c.setStrokeColorRGB(0.6, 0.6, 0.6)
            c.setLineWidth(0.3)
            c.rect(x, y, cell_size, cell_size, fill=1, stroke=1)

            # Code text (centred)
            if code is not None and cell_size >= 12.0:
                # Perceived brightness → black or white text
                lum = 0.299 * fr + 0.587 * fg + 0.114 * fb
                if lum > 0.5:
                    c.setFillColorRGB(0, 0, 0)
                else:
                    c.setFillColorRGB(1, 1, 1)
                c.setFont("Helvetica", code_font_size)
                text_y = y + cell_size * 0.5 - code_font_size * 0.35
                c.drawCentredString(x + cell_size / 2.0, text_y, code)

    _draw_footer(c, page_num, total_pages, estimate_text=estimate_text)
    c.showPage()


def _draw_legend_page(
    c: _rl_canvas.Canvas,
    legend: List[Dict[str, Any]],
    lookup: Dict[str, Tuple[str, Tuple[int, int, int]]],
    page_num: int,
    total_pages: int,
    estimate_text: str = "预估时长/费用: (待 T8 填入)",
) -> None:
    """Draw the colour-legend page(s).  Automatically paginates if needed."""
    cjk = _register_cjk_font()

    x0 = _MARGIN + 10.0
    # Column positions
    cx_swatch = x0
    cx_code = cx_swatch + _LEGEND_SWATCH_COL + _LEGEND_COL_GAP
    cx_name = cx_code + _LEGEND_CODE_COL + _LEGEND_COL_GAP
    cx_count = cx_name + _LEGEND_NAME_COL + _LEGEND_COL_GAP
    table_right = cx_count + _LEGEND_COUNT_COL

    # --- title ---
    title_y = _PAGE_H - _MARGIN - _HEADER_TOP - 15.0
    c.setFont(cjk if cjk != _FALLBACK_FONT else "Helvetica", 12)
    c.setFillColorRGB(0, 0, 0)
    c.drawString(x0, title_y, f"颜色图例 / Color Legend ({len(legend)} colours)")

    # --- header row ---
    header_y = title_y - 20.0
    c.setFont("Helvetica-Bold", 8)
    c.setFillColorRGB(0.3, 0.3, 0.3)
    c.drawString(cx_code, header_y, "Code")
    c.drawString(cx_name, header_y, "Name")
    c.drawString(cx_count, header_y, "Count")
    c.setStrokeColorRGB(0.7, 0.7, 0.7)
    c.setLineWidth(0.5)
    c.line(x0, header_y - 4.0, table_right, header_y - 4.0)

    # --- body ---
    body_top = header_y - 10.0
    body_bottom = _MARGIN + _FOOTER_H
    usable_body_h = body_top - body_bottom
    rows_per_legend_page = max(1, int(usable_body_h / _PDF_LEGEND_ROW_H))

    total_legend_items = len(legend)
    legend_page_count = max(
        1,
        (total_legend_items + rows_per_legend_page - 1) // rows_per_legend_page,
    )

    for lp in range(legend_page_count):
        if lp > 0:
            _draw_calibration_marks(c)
            body_top = _PAGE_H - _MARGIN - _HEADER_TOP - 15.0
            body_bottom = _MARGIN + _FOOTER_H
            usable_body_h = body_top - body_bottom
            rows_per_legend_page = max(1, int(usable_body_h / _PDF_LEGEND_ROW_H))

        start_idx = lp * rows_per_legend_page
        end_idx = min(start_idx + rows_per_legend_page, total_legend_items)

        row_y = body_top
        for idx in range(start_idx, end_idx):
            entry = legend[idx]
            code = entry["code"]
            cnt = entry["count"]
            name, rgb = lookup.get(code, (code, (128, 128, 128)))

            # --- swatch ---
            fr, fg, fb = rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0
            c.setFillColorRGB(fr, fg, fb)
            c.setStrokeColorRGB(0.5, 0.5, 0.5)
            swatch_dim = min(_LEGEND_ROW_H - 4.0, 14.0)
            swatch_y = row_y - swatch_dim
            c.rect(cx_swatch, swatch_y, swatch_dim, swatch_dim, fill=1, stroke=1)

            text_base = row_y - 10.0

            # --- code ---
            c.setFillColorRGB(0, 0, 0)
            c.setFont("Helvetica", _LEGEND_FONT_SIZE)
            c.drawString(cx_code, text_base, code)

            # --- name (CJK) ---
            font_for_name = cjk if cjk != _FALLBACK_FONT else "Helvetica"
            c.setFont(font_for_name, _LEGEND_FONT_SIZE)
            name_display = name if len(name) <= 38 else name[:35] + "..."
            c.drawString(cx_name, text_base, name_display)

            # --- count ---
            c.setFont("Helvetica", _LEGEND_FONT_SIZE)
            c.drawString(cx_count, text_base, str(cnt))

            row_y -= _LEGEND_ROW_H

        _draw_footer(c, page_num + lp, total_pages, estimate_text=estimate_text)
        c.showPage()


# ---------------------------------------------------------------------------
# Internal: PDF layout helpers
# ---------------------------------------------------------------------------

def _compute_pdf_estimate_text(
    codes: List[List[Optional[str]]],
    legend: List[Dict[str, Any]],
    estimate_rate: Optional[float],
    estimate_shop_rate: Optional[float],
    estimate_beginner: bool,
) -> str:
    """Build the footer estimate string for the PDF."""
    total_beads = sum(1 for row in codes for c in row if c is not None)
    colors_used = len(legend)
    est_rate = estimate_rate if estimate_rate is not None else 25.0
    est_shop = estimate_shop_rate if estimate_shop_rate is not None else 30.0
    est = estimate_time(
        beads=total_beads,
        rate=est_rate,
        colors=colors_used,
        shop_rate=est_shop,
        beginner=estimate_beginner,
    )
    return (
        f"预估时长: {est['minutes']['beginner_tier']:.0f}/"
        f"{est['minutes']['normal']:.0f}/"
        f"{est['minutes']['expert']:.0f} 分钟 | "
        f"预估费用: {est['cost']['beginner']:.0f}/"
        f"{est['cost']['normal']:.0f}/"
        f"{est['cost']['expert']:.0f} 元 "
        f"(@{est_shop:.0f}元/小时)"
    )


def _compute_pdf_cell_size(
    width: int,
    height: int,
    cell_size: Optional[float],
    usable_w: float,
    usable_h: float,
) -> float:
    """Determine the cell size for PDF grid rendering."""
    if cell_size is not None:
        return cell_size
    return max(_MIN_CELL, min(_TARGET_CELL, usable_w / width, usable_h / height))


# ---------------------------------------------------------------------------
# Public: export_pdf
# ---------------------------------------------------------------------------

def export_pdf(
    grid: Union[Dict[str, Any], List[List[Optional[str]]]],
    output_path: str,
    palette: Optional[Dict[str, Any]] = None,
    *,
    cell_size: Optional[float] = None,
    estimate_rate: Optional[float] = None,
    estimate_shop_rate: Optional[float] = None,
    estimate_beginner: bool = False,
) -> None:
    """Export a bead-pattern grid to a multipage A4 PDF.

    Each page includes calibration crosshairs at the corners, the grid
    cells (filled with colour + code text), a footer with the estimated
    assembly time and shop cost, and page numbers.  A legend page listing
    every colour (swatch, code, name, count) is appended at the end.

    When the grid is too large for a single page the cells are
    paginated both horizontally and vertically.

    Parameters
    ----------
    grid : dict | list[list[str|None]]
        Either the full ``convert()`` result dict or a 2D list of bead
        colour codes.
    output_path : str
        File path for the output PDF.
    palette : dict | None
        Palette dict from ``palette.load_palette(brand)``.  Used for
        colour-name lookup in the legend.
    cell_size : float | None
        Override cell size in PostScript points.  Auto-calculated when
        ``None`` (default).
    estimate_rate : float | None
        Base placement speed for normal tier (beads/min).  Default 25.
    estimate_shop_rate : float | None
        Shop hourly rate in yuan.  Default 30.
    estimate_beginner : bool
        When True, apply 1.5× penalty to normal-tier estimate.
    """
    width, height, codes, legend = _resolve_grid(grid)
    lookup = _build_palette_lookup(palette)

    # Estimate text for footer
    est_text = _compute_pdf_estimate_text(codes, legend, estimate_rate, estimate_shop_rate, estimate_beginner)

    # Handle empty grid
    if width == 0 or height == 0:
        _draw_empty_grid_pdf(output_path, est_text)
        return

    # Pagination layout
    usable_w = _PAGE_W - 2.0 * _MARGIN
    usable_h = _PAGE_H - 2.0 * _MARGIN - _FOOTER_H
    cell = _compute_pdf_cell_size(width, height, cell_size, usable_w, usable_h)

    cols_per_page = max(1, min(width, int(usable_w // cell)))
    rows_per_page = max(1, min(height, int(usable_h // cell)))
    pages_horiz = (width + cols_per_page - 1) // cols_per_page
    pages_vert = (height + rows_per_page - 1) // rows_per_page
    total_grid_pages = pages_horiz * pages_vert

    # Legend page count
    legend_body_h = usable_h - 40.0
    legend_rows_per_page = max(1, int(legend_body_h / _LEGEND_ROW_H))
    legend_page_count = max(1, (len(legend) + legend_rows_per_page - 1) // legend_rows_per_page)
    total_pages = total_grid_pages + legend_page_count

    c = _rl_canvas.Canvas(str(output_path), pagesize=_A4)
    c.setTitle("Bead Pattern")

    # Grid pages
    page_num = 0
    for py in range(pages_vert):
        for px in range(pages_horiz):
            page_num += 1
            start_col = px * cols_per_page
            start_row = py * rows_per_page
            cols_this = min(cols_per_page, width - start_col)
            rows_this = min(rows_per_page, height - start_row)
            _draw_grid_page(
                c, codes, lookup, cell,
                start_col, start_row, cols_this, rows_this,
                page_num, total_pages, estimate_text=est_text,
            )

    # Legend pages
    _draw_legend_page(c, legend, lookup, total_grid_pages + 1, total_pages, estimate_text=est_text)

    c.save()


def _draw_empty_grid_pdf(output_path: str, est_text: str) -> None:
    """Render a single-page PDF with an '(empty grid)' notice."""
    c = _rl_canvas.Canvas(str(output_path), pagesize=_A4)
    c.setTitle("Bead Pattern (empty grid)")
    _draw_calibration_marks(c)
    c.setFont("Helvetica", 14)
    c.drawCentredString(_PAGE_W / 2.0, _PAGE_H / 2.0, "(empty grid)")
    _draw_footer(c, 1, 1, estimate_text=est_text)
    c.showPage()
    c.save()
