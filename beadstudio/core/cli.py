"""
Typer CLI entry point for pindou (拼豆) bead pattern conversion tool.

Commands
--------
    pindou convert <image> --brand <brand> --width <beads> [options]
        Convert an image to a bead pattern.
    pindou list-brands
        List all available bead brands.
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
from pathlib import Path
from typing import Optional

import typer

from beadstudio.core import palette as palette_mod
from beadstudio.core.convert import convert as convert_image, parse_cell_mode
from beadstudio.core.models import EdgeConfig, Pattern

# ---------------------------------------------------------------------------
# Export module: PNG preview / PDF / shopping-list CSV exports
# ---------------------------------------------------------------------------
from beadstudio.core.export import export_pdf, export_png, shopping_list_csv

# ---------------------------------------------------------------------------
# Background removal: import guard — optional dependency
# ---------------------------------------------------------------------------
try:
    from rembg import remove as _rembg_remove
    _HAS_REMBG = True
except ImportError:
    _HAS_REMBG = False

# ---------------------------------------------------------------------------
# Logging / encoding
# ---------------------------------------------------------------------------
_log = logging.getLogger("pindou")

# Ensure stdout supports Unicode on Windows (avoid GBK encoding errors)
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Supported image extensions for batch processing
# ---------------------------------------------------------------------------
_SUPPORTED_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tiff", ".tif"}

# ---------------------------------------------------------------------------
# Typer app
# ---------------------------------------------------------------------------
app = typer.Typer(
    name="pindou",
    help="拼豆图案转换工具 — 将图片转换为拼豆图案",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

# bead-gui adaptation: upstream reads `bead-pattern-cli` via
# importlib.metadata, but the frozen exe ships no dist-info metadata so that
# lookup fails inside the packaged app. The module-level `__version__`
# constant is the reliable single source of truth here.
def _version_callback(value: bool) -> None:
    """Print the beadstudio version and exit when --version is passed."""
    if value:
        try:
            from beadstudio import __version__
        except Exception:  # pragma: no cover — defensive
            __version__ = "unknown"
        print(__version__)
        raise typer.Exit()


@app.callback()
def _root_callback(
    version: bool = typer.Option(
        None,
        "--version",
        help="显示版本号并退出",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """Root CLI options."""
    pass


def _brand_callback(value: Optional[str]) -> str:
    """Validate --brand is provided with Chinese error message."""
    if value is None:
        # Typer/Click will call this even before full parsing — exit with code 2 + Chinese msg
        print("缺少必填参数 --brand，可用 pindou list-brands 查看品牌", file=sys.stderr)
        sys.exit(2)
    return value


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_brand(brand: str) -> None:
    """Validate brand exists. Exits with Chinese message on failure."""
    brands = palette_mod.list_brands()
    if brand not in brands:
        print(f"未知品牌：{brand}", file=sys.stderr)
        print(f"可用品牌：{', '.join(brands)}", file=sys.stderr)
        sys.exit(1)


def _validate_match(match: str) -> str:
    """Validate and normalize the --match value."""
    match_lower = match.lower()
    if match_lower in ("cie2000", "ciede2000"):
        return "cie2000"
    if match_lower == "oklab":
        return "oklab"
    print(f"无效的颜色匹配算法：{match}，可选：cie2000, oklab", file=sys.stderr)
    sys.exit(2)


def _validate_cell_mode(mode: str) -> str:
    """Validate and normalize the --cell-color value."""
    parsed = parse_cell_mode(mode)
    if parsed is None:
        print(f"无效的取色模式：{mode}，可选：dominant（众数）, mean（均值）", file=sys.stderr)
        sys.exit(2)
    return parsed


def _validate_rate(rate: Optional[float], shop_rate: Optional[float]) -> None:
    """Validate rate and shop_rate are positive when provided."""
    if rate is not None and rate <= 0:
        print(f"rate 必须大于 0，当前值：{rate}", file=sys.stderr)
        sys.exit(1)
    if shop_rate is not None and shop_rate <= 0:
        print(f"shop_rate 必须大于 0，当前值：{shop_rate}", file=sys.stderr)
        sys.exit(1)


def _validate_output_dir(out: str) -> Path:
    """Validate --out path: reject ``..`` components (path traversal escape).

    ``--out`` is operator-chosen on the CLI, but ``..`` parts let a relative
    path write outside the intended base directory (e.g. ``--out ..\\escape``).
    """
    p = Path(out)
    if ".." in p.parts:
        print(f"输出路径不能包含 .. 越界：{out}", file=sys.stderr)
        sys.exit(2)
    return p


# Defaults mirror EdgeConfig field defaults (models.py).
_EDGE_DEFAULTS = {
    "low": 115,
    "high": 180,
    "deltae": 15.0,
    "stroke_frac": 0.12,
    "stroke_len": 5,
    "stroke_deltae": 35.0,
}


def _build_edge_config(
    edge_low: Optional[int],
    edge_high: Optional[int],
    edge_deltae: Optional[float],
    stroke_frac: Optional[float],
    stroke_len: Optional[int],
    stroke_deltae: Optional[float],
) -> Optional[EdgeConfig]:
    """Build an EdgeConfig when any advanced flag is set, else ``None``.

    ``None`` preserves the legacy (no-edge-flags) behavior byte-for-byte —
    the engine falls back to ``EdgeConfig()``. When any flag is set, unset
    fields fall back to the EdgeConfig defaults, and the LOW < HIGH pair is
    re-clamped (``high = low + 1``) so the core's ``__post_init__``
    validation always passes, mirroring ``settings_panel._edge_config``.
    """
    if all(
        v is None
        for v in (edge_low, edge_high, edge_deltae, stroke_frac, stroke_len, stroke_deltae)
    ):
        return None
    low = edge_low if edge_low is not None else _EDGE_DEFAULTS["low"]
    high = edge_high if edge_high is not None else _EDGE_DEFAULTS["high"]
    if low >= high:
        high = low + 1
    return EdgeConfig(
        mean_edge_range_low=low,
        mean_edge_range_high=high,
        mean_edge_deltae_threshold=(
            edge_deltae if edge_deltae is not None else _EDGE_DEFAULTS["deltae"]
        ),
        stroke_min_fraction=(
            stroke_frac if stroke_frac is not None else _EDGE_DEFAULTS["stroke_frac"]
        ),
        stroke_min_length=(
            stroke_len if stroke_len is not None else _EDGE_DEFAULTS["stroke_len"]
        ),
        stroke_min_deltae=(
            stroke_deltae if stroke_deltae is not None else _EDGE_DEFAULTS["stroke_deltae"]
        ),
    )


def _save_result_json(result: Pattern, out: Path, stem: str) -> None:
    """Save conversion result as JSON and log the path."""
    json_result = {
        "width": result.width,
        "height": result.height,
        "codes": result.codes,
        "empty_count": result.empty_count,
        "colors_used": result.colors_used,
        "legend": result.legend,
    }
    json_path = out / f"{stem}_result.json"
    json_path.write_text(
        json.dumps(json_result, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    _log.info(f"结果已保存：{json_path}")


def _try_export_png(
    result: dict,
    brand: str,
    out: Path,
    stem: str,
    debug: bool,
    max_grid_dimension: int = 1800,
) -> None:
    """Export PNG preview with non-fatal error handling."""
    try:
        palette = None
        try:
            palette = palette_mod.load_palette(brand)
        except Exception as exc:
            print(
                f"警告：无法加载品牌 {brand} 的色板，PNG 将使用内置色板（可能显示黑白）：{exc}",
                file=sys.stderr,
            )
        png_path = out / f"{stem}_pattern.png"
        export_png(
            result,
            output_path=str(png_path),
            palette=palette,
            max_grid_dimension=max_grid_dimension,
        )
        _log.info(f"PNG预览已保存：{png_path}")
    except Exception as exc:
        if debug:
            traceback.print_exc()
        print(f"PNG导出失败：{exc}", file=sys.stderr)


def _try_export_pdf(
    result: dict,
    brand: str,
    out: Path,
    stem: str,
    rate: Optional[float],
    shop_rate: Optional[float],
    beginner: bool,
    debug: bool,
) -> None:
    """Export PDF pattern with non-fatal error handling."""
    try:
        palette = palette_mod.load_palette(brand)
        pdf_path = out / f"{stem}_pattern.pdf"
        export_pdf(
            result,
            str(pdf_path),
            palette=palette,
            estimate_rate=rate,
            estimate_shop_rate=shop_rate,
            estimate_beginner=beginner,
        )
        _log.info(f"PDF已保存：{pdf_path}")
    except Exception as exc:
        if debug:
            traceback.print_exc()
        print(f"PDF导出失败：{exc}", file=sys.stderr)


def _try_export_shopping_csv(
    result: dict,
    brand: str,
    out: Path,
    stem: str,
    rate: Optional[float],
    shop_rate: Optional[float],
    beginner: bool,
    debug: bool,
) -> None:
    """Export shopping-list CSV with non-fatal error handling."""
    try:
        palette = palette_mod.load_palette(brand)
        shop_path = out / f"{stem}_shopping.csv"
        shopping_list_csv(
            result,
            palette=palette,
            output_path=str(shop_path),
            rate=rate,
            shop_rate=shop_rate,
            beginner=beginner,
        )
        _log.info(f"购物清单已保存：{shop_path}")
    except Exception as exc:
        if debug:
            traceback.print_exc()
        print(f"购物清单导出失败：{exc}", file=sys.stderr)


def _preprocess_bg_remove(image_path: Path, debug: bool = False) -> Path:
    """Remove background using rembg. Returns path to processed image."""
    if not _HAS_REMBG:
        print("错误：需要安装 rembg 才能使用 --bg-remove 功能", file=sys.stderr)
        print("请运行：pip install rembg onnxruntime", file=sys.stderr)
        sys.exit(1)
    try:
        from PIL import Image
        img = Image.open(image_path).convert("RGBA")
        img_data = _rembg_remove(img)
        out_path = image_path.parent / f"{image_path.stem}_nobg.png"
        img_data.save(out_path)
        _log.info(f"背景已移除，输出：{out_path}")
        return out_path
    except Exception as exc:
        if debug:
            traceback.print_exc()
        print(f"背景移除失败：{exc}", file=sys.stderr)
        sys.exit(1)


def _process_single(
    image_path: Path,
    width: int,
    height: Optional[int],
    brand: str,
    match: str,
    dither: bool,
    bg_remove: bool,
    out: Path,
    pdf: bool,
    shopping_list: bool,
    rate: Optional[float],
    shop_rate: Optional[float],
    beginner: bool,
    debug: bool,
    max_colors: Optional[int] = None,
    cell_color: str = "dominant",
    max_grid_dimension: int = 1800,
    series: Optional[str] = None,
    edge_config: Optional[EdgeConfig] = None,
) -> None:
    """Process a single image through the convert pipeline."""
    _validate_brand(brand)
    color_space = _validate_match(match)
    cell_mode = _validate_cell_mode(cell_color)

    # Defense-in-depth: per-image output dir must not traverse outside
    # (e.g. an image file named ``...png`` has stem ``..``).
    if ".." in out.parts:
        print(f"输出路径不能包含 .. 越界：{out}", file=sys.stderr)
        sys.exit(2)

    if series is not None and not palette_mod.get_series(brand):
        print("该品牌无系列概念，忽略 --series", file=sys.stderr)
        series = None

    working_path = image_path
    temp_file: Optional[Path] = None

    try:
        # Background removal preprocessing
        if bg_remove:
            temp_file = _preprocess_bg_remove(image_path, debug=debug)
            working_path = temp_file

        # Core conversion
        result = convert_image(
            image_path=str(working_path),
            width=width,
            height=height,
            brand=brand,
            color_space=color_space,
            dither=dither,
            max_colors=max_colors,
            cell_mode=cell_mode,
            series_range=series,
            edge_config=edge_config,
        )

        out.mkdir(parents=True, exist_ok=True)
        stem = image_path.stem

        # Save JSON result (always)
        _save_result_json(result, out, stem)

        # PNG preview (always; non-fatal)
        _try_export_png(result, brand, out, stem, debug, max_grid_dimension)

        # Optional PDF export (non-fatal)
        if pdf:
            _try_export_pdf(result, brand, out, stem, rate, shop_rate, beginner, debug)

        # Optional shopping list CSV (non-fatal)
        if shopping_list:
            _try_export_shopping_csv(result, brand, out, stem, rate, shop_rate, beginner, debug)

        # Success summary
        print(f"[OK] 转换完成！输出目录：{out.resolve()}")
        print(f"  网格尺寸：{result.width}×{result.height}")
        print(f"  使用颜色：{result.colors_used} 种")
        print(f"  空位数量：{result.empty_count}")

    except FileNotFoundError:
        if debug:
            traceback.print_exc()
        print(f"文件不存在：{image_path}", file=sys.stderr)
        sys.exit(1)
    except ValueError as exc:
        if debug:
            traceback.print_exc()
        msg = str(exc)
        if "brand" in msg.lower() or "unknown brand" in msg.lower():
            print(f"不支持的品牌：{brand}，可用 `pindou list-brands` 查看所有品牌", file=sys.stderr)
        else:
            print(f"参数错误：{exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        if debug:
            traceback.print_exc()
        print(f"处理失败：{exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        # Cleanup temp file
        if temp_file is not None and temp_file.exists():
            try:
                temp_file.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _setup_logging(debug: bool) -> None:
    """Configure logging: DEBUG level with --debug, WARNING otherwise."""
    if debug:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING)


def _run_batch(
    image_path: Path,
    width: int,
    height: Optional[int],
    brand: str,
    match: str,
    dither: bool,
    bg_remove: bool,
    output_dir: Path,
    pdf: bool,
    shopping_list: bool,
    rate: Optional[float],
    shop_rate: Optional[float],
    beginner: bool,
    debug: bool,
    max_colors: Optional[int] = None,
    cell_color: str = "dominant",
    max_grid_dimension: int = 1800,
    series: Optional[str] = None,
    edge_config: Optional[EdgeConfig] = None,
) -> None:
    """Process all supported images in a directory (--dir batch mode)."""
    if not image_path.is_dir():
        print(f"目录不存在：{image_path}", file=sys.stderr)
        sys.exit(1)

    images = sorted([
        p for p in image_path.iterdir()
        if p.is_file() and p.suffix.lower() in _SUPPORTED_EXTS
    ])
    if not images:
        print(f"目录中没有支持的图片文件：{image_path}", file=sys.stderr)
        sys.exit(1)

    print(f"批量模式：发现 {len(images)} 张图片")
    for idx, img_p in enumerate(images, 1):
        stem = img_p.stem
        if stem == ".." or "/" in stem or "\\" in stem:
            print(
                f"跳过 {img_p.name}：文件名不能用作子目录（包含 .. 或路径分隔符）",
                file=sys.stderr,
            )
            continue
        print(f"\n[{idx}/{len(images)}] 处理：{img_p.name}")
        _process_single(
            image_path=img_p,
            width=width,
            height=height,
            brand=brand,
            match=match,
            dither=dither,
            bg_remove=bg_remove,
            out=output_dir / stem,
            pdf=pdf,
            shopping_list=shopping_list,
            rate=rate,
            shop_rate=shop_rate,
            beginner=beginner,
            debug=debug,
            max_colors=max_colors,
            cell_color=cell_color,
            max_grid_dimension=max_grid_dimension,
            series=series,
            edge_config=edge_config,
        )
    print(f"\n[OK] 批量处理完成！共 {len(images)} 张图片")


@app.command()
def convert(
    image: str = typer.Argument(
        ...,
        help="输入图片路径（或 --dir 批量模式下的目录）",
        show_default=False,
    ),
    brand: str = typer.Option(
        None,
        "--brand", "-b",
        help="拼豆品牌名称（必填）",
        callback=_brand_callback,
    ),
    width: int = typer.Option(
        ...,
        "--width", "-w",
        help="目标宽度（珠子数），必填",
        min=1,
    ),
    height: Optional[int] = typer.Option(
        None,
        "--height", "-h",
        help="目标高度（珠子数），默认按图片宽高比自动计算",
        min=1,
    ),
    max_colors: Optional[int] = typer.Option(
        None,
        "--max-colors",
        help="限制最终使用的拼豆颜色数量（最多 N 种），默认不限制（照片建议 20-30）",
        min=1,
    ),
    cell_color: str = typer.Option(
        "dominant",
        "--cell-color",
        help="取色模式：dominant（众数，默认）或 mean（均值）",
    ),
    dither: bool = typer.Option(
        False,
        "--dither",
        help="启用 Floyd-Steinberg 误差扩散抖动",
    ),
    bg_remove: bool = typer.Option(
        False,
        "--bg-remove",
        help="自动移除图片背景（需要安装 rembg）",
    ),
    match: str = typer.Option(
        "cie2000",
        "--match", "-m",
        help="颜色匹配算法：cie2000（感知准确）或 oklab（快速）",
    ),
    out: str = typer.Option(
        "./output",
        "--out", "-o",
        help="输出目录",
    ),
    pdf: bool = typer.Option(
        False,
        "--pdf",
        help="导出 PDF 图案",
    ),
    shopping_list: bool = typer.Option(
        False,
        "--shopping-list",
        help="导出购物清单 CSV",
    ),
    rate: Optional[float] = typer.Option(
        None,
        "--rate",
        help="制作速度（珠/分钟），用于工时预估",
    ),
    shop_rate: Optional[float] = typer.Option(
        None,
        "--shop-rate",
        help="购物时薪（元/小时），用于成本预估",
    ),
    beginner: bool = typer.Option(
        False,
        "--beginner",
        help="新手模式，降低预估制作速度",
    ),
    max_grid_dimension: int = typer.Option(
        1800,
        "--max-grid-dimension",
        help="PNG图表网格最大像素尺寸（默认1800，大图时格子≥14px以显示色号）",
        min=100,
    ),
    dir_mode: bool = typer.Option(
        False,
        "--dir",
        help="批量模式：处理目录下所有支持的图片",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="显示完整错误堆栈（调试用）",
    ),
    series: Optional[str] = typer.Option(
        None,
        "--series",
        help="色号系列范围（仅 MARD/COCO 等字母系列品牌，如 \"M\" 表示 A~M、\"A-G\" 表示 A 到 G）",
    ),
    edge_low: Optional[int] = typer.Option(
        None,
        "--edge-low",
        help="Edge range low (base, scales with cell area). Default 115.",
    ),
    edge_high: Optional[int] = typer.Option(
        None,
        "--edge-high",
        help="Edge range high (base). Default 180.",
    ),
    edge_deltae: Optional[float] = typer.Option(
        None,
        "--edge-deltae",
        help="Edge ΔE00 threshold. Default 15.0.",
    ),
    stroke_frac: Optional[float] = typer.Option(
        None,
        "--stroke-frac",
        help="Stroke min fraction (0-1). Default 0.12.",
    ),
    stroke_len: Optional[int] = typer.Option(
        None,
        "--stroke-len",
        help="Stroke min length. Default 5.",
    ),
    stroke_deltae: Optional[float] = typer.Option(
        None,
        "--stroke-deltae",
        help="Stroke min ΔE00. Default 35.0.",
    ),
) -> None:
    """将图片转换为拼豆图案。

    示例：
        pindou convert photo.png --brand perler --width 52
        pindou convert photo.png --brand perler --width 52 --max-colors 24
        pindou convert photo.png -b hama -w 80 --dither --match oklab
        pindou convert ./images/ --dir --brand perler --width 52
    """
    _setup_logging(debug)

    # Validate brand early
    if brand is None:
        print("缺少必填参数 --brand，可用 pindou list-brands 查看品牌", file=sys.stderr)
        sys.exit(2)

    # Validate match and rate/shop_rate early (before any processing)
    _validate_match(match)
    _validate_cell_mode(cell_color)
    _validate_rate(rate, shop_rate)

    # EdgeConfig: None when no advanced flag is set (legacy behavior).
    edge_config = _build_edge_config(
        edge_low, edge_high, edge_deltae, stroke_frac, stroke_len, stroke_deltae
    )

    image_path = Path(image)
    output_dir = _validate_output_dir(out)

    # Batch mode: process directory
    if dir_mode:
        _run_batch(
            image_path=image_path,
            width=width,
            height=height,
            brand=brand,
            match=match,
            dither=dither,
            bg_remove=bg_remove,
            output_dir=output_dir,
            pdf=pdf,
            shopping_list=shopping_list,
            rate=rate,
            shop_rate=shop_rate,
            beginner=beginner,
            debug=debug,
            max_colors=max_colors,
            cell_color=cell_color,
            max_grid_dimension=max_grid_dimension,
            series=series,
            edge_config=edge_config,
        )
        return

    # Single file mode
    if not image_path.exists():
        if debug:
            try:
                raise FileNotFoundError(f"File not found: {image_path}")
            except FileNotFoundError:
                traceback.print_exc()
        print(f"文件不存在：{image_path}", file=sys.stderr)
        sys.exit(1)

    if not image_path.is_file():
        if debug:
            try:
                raise IsADirectoryError(f"Not a valid file: {image_path}")
            except IsADirectoryError:
                traceback.print_exc()
        print(f"不是有效的文件：{image_path}", file=sys.stderr)
        sys.exit(1)

    _process_single(
        image_path=image_path,
        width=width,
        height=height,
        brand=brand,
        match=match,
        dither=dither,
        bg_remove=bg_remove,
        out=output_dir / image_path.stem,
        pdf=pdf,
        shopping_list=shopping_list,
        rate=rate,
        shop_rate=shop_rate,
        beginner=beginner,
        debug=debug,
        max_colors=max_colors,
        cell_color=cell_color,
        max_grid_dimension=max_grid_dimension,
        series=series,
        edge_config=edge_config,
    )


@app.command(name="list-brands")
def list_brands_cmd() -> None:
    """列出所有可用的拼豆品牌。"""
    brands = palette_mod.list_brands()
    if not brands:
        print("没有找到品牌数据", file=sys.stderr)
        sys.exit(1)

    print(f"可用品牌（共 {len(brands)} 个）：\n")
    for b in brands:
        try:
            p = palette_mod.load_palette(b)
            n_colors = len(p.get("colors", []))
            source = p.get("source", "unknown")
            print(f"  {b:<20s} {n_colors:>4d} 色   来源：{source}")
        except Exception:
            print(f"  {b:<20s} （无法加载）")

    print("\n用法：pindou convert <图片> --brand <品牌> --width <珠数>")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI entry point (for testing)."""
    app()


if __name__ == "__main__":
    main()
