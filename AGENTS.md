# AGENTS.md — BeadStudio (豆趣工坊) repo guide

PySide6 desktop app for bead (拼豆) patterns. GPL-3.0. W5: docs + git init.

## Repo layout

```
beadstudio/
├── app.py            # QApplication + main window (GUI flow)
├── ui/               # i18n.py (tr()), preview.py, settings_panel.py
│   └── theme.py      # dark theme tokens + QSS + apply_theme() (DESIGN.md)
├── core/             # ENGINE COPY of bead-pattern-cli (see copy rule)
│   ├── cli.py        # CLI entry: python -m beadstudio.core.cli
│   ├── models.py     # typed models: Pattern, EdgeConfig, BeadColor, Palette
│   ├── convert.py    # re-export shell (logic in conversion/)
│   ├── conversion/   # conversion pipeline subpackage (W3 split)
│   │   ├── pipeline.py  # image → bead grid pipeline (CIEDE2000/OKLab, dither)
│   │   ├── color.py     # sRGB/XYZ/Lab/OKLab conversions
│   │   ├── matching.py  # nearest-neighbour palette matching
│   │   ├── dither.py    # Floyd-Steinberg error diffusion
│   │   ├── edge.py      # dominant color / clustering / edge detection
│   │   ├── stroke.py    # stroke tracking + line-color voting
│   │   └── cleanup.py   # BFS region cleanup + color-count limiting
│   ├── palette.py    # palette loading (core/data/palettes/*.json, 21 brands)
│   ├── estimate.py   # time/cost estimation
│   ├── export.py     # PNG / CSV / PDF export
│   └── data/         # bundled data (palettes)
│       └── palettes/ # 21 brand palette JSONs (perler/hama/artkal/...)
├── assets/           # app_icon.ico, app_icon_512.png
├── tests/            # pytest, 302 tests (smoke, bg preview, exports, i18n)
├── scripts/build_exe.ps1  # PyInstaller onefile build → dist\BeadStudio.exe
├── LICENSE           # GPL-3.0
├── NOTICE            # third-party attribution (engine MIT, palettes, Qt)
├── README.md         # bilingual (zh/en), release-grade
└── pyproject.toml    # name=beadstudio, version=1.1.1, setuptools
```

## Commands (conda env `beadGUI`)

```powershell
# tests
conda run -n beadGUI python -m pytest tests/ -q          # 302 passed, 1 skipped
# or directly (conda run can deadlock on this machine with big output):
# use the env's python directly, e.g.:
python -m pytest tests/ -q

# run GUI
conda run -n beadGUI python -m beadstudio

# run engine CLI
conda run -n beadGUI python -m beadstudio.core.cli convert photo.png --brand perler --width 52 --pdf
conda run -n beadGUI python -m beadstudio.core.cli list-brands

# build exe (PyInstaller in beadGUI env)
powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1
# verify frozen bundle: dist\BeadStudio.exe --list-brands  (expect list-brands=21)
```

## Copy rule (CRITICAL)

`beadstudio/core/` is a **copy of the bead-pattern-cli engine**
(upstream bead-pattern-cli engine, MIT). All imports from the app must be
`beadstudio.core.*`. Do NOT diverge the core locally without syncing
upstream first; keep the copy in sync with upstream, and never edit core
files for UI-only reasons (work around in `beadstudio/ui/` or `app.py`).

## Bilingual i18n convention

Every user-visible UI string goes through `tr()` in `beadstudio/ui/i18n.py`
— a dict of `(English, Chinese)` tuples. No hardcoded UI text. Language
follows system locale (`zh*` → Chinese, else English), overridable with
`set_language()`. Add new UI strings to the LANG dict in both languages.

## Release flow

1. Bump `version` in `pyproject.toml` (and README if mentioned).
2. Run tests: `python -m pytest tests/ -q` (must be green).
3. Build exe: `scripts\build_exe.ps1` → `dist\BeadStudio.exe` (~89 MB).
4. Verify frozen bundle: `dist\BeadStudio.exe --list-brands`.
5. `git add -A && git commit` (dist/, build/, *.spec are gitignored —
   never commit the exe).
6. Tag: `git tag vX.Y.Z`.
7. Push + create GitHub Release with the exe attached (user-authorized).

## Do not

- Commit `dist/`, `build/`, `*.spec`, `__pycache__/`, `.omo/`,
  `.pytest_cache/`, `.venv*/` (all in .gitignore).
- Modify the upstream bead-pattern-cli repo from this repo's work.
