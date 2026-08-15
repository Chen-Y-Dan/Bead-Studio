"""Bilingual (en/zh) user-facing strings for the BeadStudio UI.

Every user-visible string in the UI goes through :func:`tr`. The default
language follows the system locale (``zh*`` → Chinese, anything else →
English) and can be overridden at runtime with :func:`set_language`.

W2 scope: settings panel + preview. W3 (batch, export dialogs) adds keys.
"""

from __future__ import annotations

import locale as _locale
import os
import warnings
from typing import Tuple

#: Every UI string, as (English, Chinese). Unknown keys fall back to the key
#: itself so missing translations never crash the UI.
LANG: dict[str, Tuple[str, str]] = {
    # window
    "window_title": ("BeadStudio", "BeadStudio 豆趣工坊"),
    # manual language switcher (both option names are language-invariant,
    # so the combo always shows 中文 / English in either language)
    "language": ("Language", "语言"),
    "lang_zh": ("中文", "中文"),
    "lang_en": ("English", "English"),
    # settings labels
    "brand": ("Brand", "品牌"),
    "width": ("Width (beads)", "宽度（珠数）"),
    "height": ("Height (0 = auto)", "高度（0 = 自动保持比例）"),
    "series": ("Series", "系列"),
    "series_all": ("All", "全部"),
    "max_colors": ("Max colors (0 = unlimited)", "颜色数（0 = 不限）"),
    "cell_mode": ("Color per cell", "取色模式"),
    "cell_mode_dominant": ("Dominant", "众数"),
    "cell_mode_mean": ("Mean", "均值"),
    "dither": ("Dither", "抖动"),
    "dither_mean_hint": ("Dithering is auto-disabled in mean mode.",
                         "均值模式下抖动自动禁用。"),
    # background removal (optional dependency: rembg)
    "bg_remove": ("Remove background", "背景移除"),
    "bg_remove_hint": (
        "Requires optional dependency: rembg (pip install rembg onnxruntime)",
        "需要安装可选依赖：rembg（pip install rembg onnxruntime）",
    ),
    "bg_remove_disabled": (
        "Disabled (rembg not installed)", "已禁用（需安装 rembg）",
    ),
    "bg_remove_skipped": (
        "Background removal skipped (rembg not available)",
        "背景移除已跳过（未安装 rembg）",
    ),
    # view options
    "show_grid": ("Show grid", "显示网格"),
    "show_codes": ("Show bead codes", "显示色号"),
    "export_format": ("Export", "导出格式"),
    "export_pdf": ("PDF pattern", "导出 PDF"),
    "export_png": ("PNG pattern", "导出 PNG"),
    "export_csv": ("Shopping list CSV", "购物清单 CSV"),
    # buttons
    "choose_image": ("Choose image…", "选择图片"),
    "generate_preview": ("Generate Preview", "生成预览"),
    "batch": ("Batch folder…", "批量处理文件夹"),
    # output directory
    "output_dir": ("Output directory", "输出目录"),
    "choose_output_dir": ("Choose output directory…", "选择输出目录"),
    "output_dir_auto": ("Auto (image folder)", "自动（图片所在目录）"),
    # image path label
    "image_path_default": ("No image selected", "未选择图片"),
    # drag & drop / paste quick-input hints
    "drop_hint": ("Drop an image here or press Ctrl+V",
                  "拖入图片或按 Ctrl+V 粘贴"),
    "drop_accept": ("Release to load image", "松开以载入图片"),
    "image_input_hint": (
        "Tip: drag an image here or press Ctrl+V to paste",
        "提示：可拖入图片，或按 Ctrl+V 粘贴图片",
    ),
    "no_clipboard_image": ("No image found in clipboard", "剪贴板中没有图片"),
    # preview
    "cell_size": ("Cell size", "格子大小"),
    "preview_empty": ("No pattern yet — choose an image and press Generate Preview",
                      "尚无图案 —— 请选择图片后点击“生成预览”"),
    # status bar
    "status_ready": ("Ready", "就绪"),
    "status_converting": ("Converting…", "转换中…"),
    "status_done": ("Done: {n} colors used, {w}×{h}",
                    "转换完成：使用 {n} 种颜色（{w}×{h}）"),
    "status_error": ("Conversion failed", "转换失败"),
    "saved_path": ("Saved: {path}", "已保存：{path}"),
    "export_failed": ("Export failed: {msg}", "导出失败：{msg}"),
    # batch mode
    "choose_source_folder": ("Choose source folder…", "选择源文件夹"),
    "batch_progress_title": ("Batch processing", "批量处理"),
    "batch_progress_label": ("Processing {i}/{total}: {name}",
                             "正在处理第 {i}/{total} 张：{name}"),
    "batch_done": ("Batch complete: {ok} images, {fail} failed",
                   "批量完成：{ok} 张，{fail} 张失败"),
    "batch_cancelled": ("Batch cancelled: {done} images done",
                        "已取消批量处理：已完成 {done} 张"),
    "batch_no_images": ("No supported images found in the folder",
                        "文件夹中没有支持的图片"),
    "failed": ("Failed", "失败"),
    "cancel": ("Cancel", "取消"),
    # messages
    "err_no_image": ("Please choose an image first", "请先选择图片"),
    "err_image_missing": ("Image file not found", "找不到图片文件"),
    "err_title": ("Error", "错误"),
    "img_filter": (
        "Image files (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All files (*)",
        "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;所有文件 (*)",
    ),
}


def _detect_default_lang() -> str:
    """Best-effort system-locale detection: ``zh*`` → ``"zh"``, else ``"en"``.

    Checks ``LANG``/``LC_ALL``/``LC_MESSAGES`` env vars first, then the
    locale module (``getdefaultlocale`` is deprecated in 3.12+, so the
    DeprecationWarning is suppressed and ``getlocale`` is the fallback).
    """
    for name in ("LANG", "LC_ALL", "LC_MESSAGES"):
        value = os.environ.get(name)
        if value and value.lower().startswith("zh"):
            return "zh"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            lang_code, _encoding = _locale.getdefaultlocale()
            if lang_code and lang_code.lower().startswith("zh"):
                return "zh"
    except (ValueError, TypeError, AttributeError):
        pass
    try:
        lang_code, _ = _locale.getlocale()
        if lang_code and lang_code.lower().startswith("zh"):
            return "zh"
    except (ValueError, TypeError, AttributeError):
        pass
    return "en"


DEFAULT_LANG = _detect_default_lang()

#: Current language ("en" | "zh"); overridable via :func:`set_language`.
_current_lang: str = DEFAULT_LANG


def set_language(lang: str) -> None:
    """Override the UI language (``"en"`` or ``"zh"``)."""
    global _current_lang
    if lang not in ("en", "zh"):
        raise ValueError(f"Unsupported language: {lang!r} (expected 'en' or 'zh')")
    _current_lang = lang


def get_language() -> str:
    """Return the current UI language (``"en"`` or ``"zh"``)."""
    return _current_lang


def tr(key: str, lang: str | None = None) -> str:
    """Translate a UI string key for ``lang`` (default: current language).

    >>> tr('brand', 'zh')
    '品牌'
    >>> tr('brand', 'en')
    'Brand'
    """
    chosen = lang if lang is not None else _current_lang
    en, zh = LANG.get(key, (key, key))
    return zh if chosen == "zh" else en
