# Changelog

All notable changes to BeadStudio (豆趣工坊) are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.1.1] - 2026-08-18

### Fixed
- Perler 103-color data deduplicated to single source via palette.py/perler.json (f89ddcd)
- Pattern dict-compat shim removed — export accepts Pattern, attr access unified, compat tests removed (c57de63)
- 15 core exception messages converted to English (W1 consumer-agnostic consistency) (0236829)
- Documentation test-count drift corrected (README/AGENTS/CHANGELOG) (c1c08ba)

### Added
- CLI convert command exposes EdgeConfig via 6 flags (--edge-low/high/deltae/--stroke-frac/len/deltae), matching GUI sliders (ff20a93)

## [1.1.0] - 2026-08-16

### Added
- Dark modern theme with a DESIGN.md token system and Fusion QSS styling — amber accent, CJK fonts, interactive states, preview card / empty-state, and a fix for scroll clipping (eb0998d)
- Manual **生成预览 / Generate Preview** button — replaced the live debounce auto-convert, so parameters can be adjusted without UI stalls; visible spinbox/combo arrows in dark theme (6c5b30d)
- Manual **中文 / English language switcher** with instant re-translation of the UI — values are preserved across the toggle (c9b7ffa)
- **Drag & drop and Ctrl+V paste** image input — drag/paste loads the image only (no auto-convert), with bilingual hints (3f9f5ae, e1cfbec)
- Advanced-parameters collapsible area with **6 EdgeConfig sliders** (smoothness / edge / thin-line / length / high-boundary / color-diff), reset-to-defaults, LOW < HIGH linkage, and preview rendering via `Pattern.grid_rgb` (f4ae524)

### Changed
- Refactored the engine core from upstream — `models.py` + `conversion/` subpackage, `Pattern` return type, `EdgeConfig` parameters, and regression fixtures; 302 tests green (1 skipped) (a831109)

### Fixed
- GUI launch crash `DLL load failed while importing pyexpat` — added conda DLLs (libexpat / libffi-7,8 / libcrypto / liblzma / zlib) to `--add-binary` in the build (88d889a)

## [1.0.0] - initial

### Added
- PySide6 desktop app for bead pattern design — image to bead pattern conversion with brand color matching, PDF/PNG/CSV exports, batch conversion, and background removal (8e5ec1c)
