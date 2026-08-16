"""
Image-to-bead-pattern conversion pipeline (re-export shell).

All implementation lives in :mod:`beadstudio.core.conversion` (W3 split);
this module re-exports every name so existing imports (``from
beadstudio.core.convert import convert``, ``_load_and_prepare``,
``_trace_strokes``, …) keep working unchanged.
"""
from .conversion.pipeline import *
from .conversion.pipeline import (
    _CACHED_PALETTES, _CELL_MODE_ALIASES, _MAX_SOURCE_PIXELS, _MEAN_EDGE_MAX,
    _MEAN_EDGE_REF_CELL_AREA, _MEAN_EDGE_SCALE_K_HIGH, _MEAN_EDGE_SCALE_K_LOW,
    _STROKE_A_RANGE_MIN, _STROKE_CLUSTER_DELTAE, _STROKE_DARK_MAX, _STROKE_LINE_DELTAE,
    _STROKE_TOP_N, _build_codes_grid, _build_legend, _edge_scale,
    _get_palette_codes, _get_palette_rgb, _load_and_prepare, _palette_arrays_from_colors,
    _quantize_nearest,
)
from .conversion.color import (
    _D65_XYZ, _M1_OKLAB, _M2_OKLAB, _SRGB_TO_XYZ, _XYZ_TO_SRGB, _convert_colors,
    _f, lab_to_xyz, linear_to_srgb, linear_to_xyz, oklab_to_srgb, srgb_to_lab,
    srgb_to_linear, srgb_to_oklab, xyz_to_lab, xyz_to_linear,
)
from .conversion.matching import _nearest_one, nearest_indices
from .conversion.dither import _apply_floyd_steinberg
from .conversion.edge import (
    _channel_range, _deltae00_between, _dominant_color_cell, _extreme_pixel_deltae00,
    _top2_colors, _top_clusters,
)
from .conversion.stroke import (
    _chain_line_color, _global_background_color, _record_stroke_candidate,
    _trace_strokes,
)
from .conversion.cleanup import _bfs_region_cleanup, _merge_rare_colors
