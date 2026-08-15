# BeadStudio 豆趣工坊 — Design System (Dark Modern Theme)

> Design-system gate document. Read this BEFORE touching any UI code.
> This is the single source of truth for the dark theme; the implementation
> in `beadstudio/ui/theme.py` mirrors these tokens verbatim (the `COLORS`
> dict is generated from this document's palette).

---

## 1. Brand

| | |
|---|---|
| **Product** | BeadStudio 豆趣工坊 — bead (拼豆) pattern design app |
| **Audience** | Hobbyist crafters (en + zh-CN) working on Windows |
| **Design language** | Dark modern *pro-tool* (Photoshop / Linear / Figma vibe): deep neutral surfaces, one warm craft accent, calm motion, everything quiet except the pattern itself |
| **Motif** | Beads are small colorful objects on a dark workbench. The app should feel like a well-lit bead board on a dark desk — the **pattern is the star**, chrome stays subdued. |
| **Theme name** | `bead-dark` |
| **Style engine** | Qt Fusion style + QSS stylesheet (Fusion makes QSS reliable across all widgets) |

---

## 2. Color tokens

All values are hexadecimal. Semantic names, not per-widget names — widgets
reference *roles* so a future light theme can reuse the same structure.

### 2.1 Surfaces (layered dark neutrals — cool slate, not pure black)

| Token | Hex | Usage |
|---|---|---|
| `bg` | `#1B1D21` | App base / window background / status bar / scrollbar track |
| `panel` | `#212328` | Group boxes, settings panel regions (elevation +1) |
| `surface` | `#26292F` | Raised elements: inputs, buttons, combo popups, progress track |
| `surface_hover` | `#2E323A` | Hover state for raised elements |
| `surface_pressed` | `#191B1F` | Pressed state for raised elements (darker than base) |

### 2.2 Borders & dividers

| Token | Hex | Usage |
|---|---|---|
| `border` | `#33373F` | Subtle dividers, default widget outlines |
| `border_strong` | `#424752` | Stronger outlines: popups, tooltips, hover borders |

### 2.3 Text

| Token | Hex | Usage | Contrast on `bg` |
|---|---|---|---|
| `text` | `#E6E9EF` | Primary text / labels / values | 13.4 : 1 ✅ AA |
| `text_secondary` | `#9AA3B2` | Hints, group titles, status text | 6.2 : 1 ✅ AA |
| `text_disabled` | `#5C6470` | Disabled controls | — (non-interactive) |
| `text_on_accent` | `#1B1203` | Text on amber accent (buttons) | 7.8 : 1 ✅ AA |

### 2.4 Accent — *bead amber* 🧡 (brand color)

> **Why amber, not blue?** The palette-matching engine already produces
> blue-heavy bead colors (Perler/Hama blues are ubiquitous). A blue accent
> would compete with the content. **Amber/orange reads as "craft + warmth"**
> — like actual fused amber beads, heat-set bead sheets, and "ready-to-use"
> affordances (the Convert action). It also sits on the opposite side of the
> wheel from the cool slate surfaces, giving the dark UI a single warm focal
> point instead of a generic blue corporate tint.

| Token | Hex | Usage |
|---|---|---|
| `accent` | `#FFA52C` | Primary action button, focus ring, checked indicators, progress chunk, selection |
| `accent_hover` | `#FFB85C` | Accent elements on hover |
| `accent_pressed` | `#E08F1F` | Accent elements on press |
| `accent_disabled` | `#6B5A3F` | Accent elements in disabled state |
| `focus` | `#FFA52C` | Keyboard focus outline (same as accent) |

### 2.5 Semantic status

| Token | Hex | Usage |
|---|---|---|
| `success` | `#3ECF8E` | Success messages / done state |
| `warning` | `#F2B84B` | Warnings (e.g. bg-remove skipped) |
| `danger` | `#F0584A` | Errors / failed conversion |

### 2.6 Preview surface

| Token | Hex | Usage |
|---|---|---|
| `preview_bg` | `#16181C` | Canvas surround — slightly **darker** than the window base so the bead card reads as recessed |
| `empty_cell` | `#26292F` | Fill for `None` (empty) cells — neutral dark, matches `surface` |
| `grid` | `#3A3F48` | Grid lines — one step lighter than the empty-cell fill so lines stay legible on dark cells but never shout over bright bead colors |

---

## 3. Typography

### Font stack

```
"Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei", sans-serif
```

- **en**: Segoe UI (native Windows, crisp at 9pt).
- **zh**: Segoe UI has no CJK glyphs → the family list falls through to
  **Microsoft YaHei UI / Microsoft YaHei** (ships with Windows, renders
  Simplified Chinese cleanly). Both the QSS `font-family` and a programmatic
  `QFont.setFamilies()` fallback in `apply_theme()` carry the same list.
- Windows-only stack is accepted debt (the app is Windows-first).

### Size scale (points — Qt widget default is 9pt; we keep DPI-aware points)

| Token | Size | Weight | Usage |
|---|---|---|---|
| `size_caption` | 8pt | Regular | Tooltips, hint text (`dither_hint`, `bg_remove_hint`) |
| `size_body` | 9pt | Regular | Default — labels, inputs, buttons, status bar |
| `size_strong` | 9pt | SemiBold (600) | Group titles, primary button text, zoom header |
| `size_title` | 10pt | SemiBold | Preview empty-state placeholder line |

Code text inside preview cells is pixel-based (not pt): `max(6, cell_size//3)`
px, contrast decided by cell luminance (unchanged engine behavior).

---

## 4. Spacing & layout

**4px base grid** — all paddings/margins are multiples of 4.

| Token | Value | Usage |
|---|---|---|
| `space_1` | 4px | Tight gaps, icon padding |
| `space_2` | 8px | Root window margins (`8,8,8,8` — already in `app.py`) |
| `space_3` | 12px | **Panel padding** (QGroupBox inner margins) |
| `space_4` | 16px | Group-to-group spacing |
| `space_5` | 24px | Section separation, popup padding |

Layout rules:
- Left settings panel: keep **320px fixed** (current) — sufficient for the
  longest bilingual labels ("Max colors (0 = unlimited)"). Not bumped to 340;
  the 8px root margin + 12px group padding leaves enough breathing room.
- Right side: view-options row (grid/codes toggles) above the preview card.
- Margins never exceed the 4px scale — no magic numbers.

---

## 5. Radius

| Token | Value | Usage |
|---|---|---|
| `radius_sm` | 4px | Tooltips, menu items, scrollbar handle ends |
| `radius_md` | 6px | **Buttons**, combo/spin/input boxes, menu popup |
| `radius_lg` | 8px | Group boxes, preview card, scrollbar caps |
| `radius_xl` | 10px | (reserved — cards/heavy containers) |

Indicators: checkboxes `3px`, radio buttons fully round (`7px` = 14px/2).

---

## 6. Component states

Every interactive control defines **default / hover / pressed / disabled / focus**.
Qt has no CSS transitions — state swaps are instant; the *color deltas* do
the perceptual work (see §10 debt).

| Component | Default | Hover | Pressed | Disabled | Focus |
|---|---|---|---|---|---|
| `QPushButton` | bg `surface`, border `border`, text `text` | bg `surface_hover`, border `border_strong` | bg `surface_pressed` | text `text_disabled`, bg `surface`, border `border` | border `focus` (1px) |
| `QPushButton#primaryButton` (Convert) | bg `accent`, border `accent`, text `text_on_accent`, weight 600 | bg `accent_hover` | bg `accent_pressed` | bg `accent_disabled`, text `text_disabled` | border `accent` |
| `QComboBox` | bg `surface`, border `border` | border `border_strong` | bg `surface_pressed` | text `text_disabled` | border `focus` |
| Combo popup item | text `text` | bg `surface_hover` | — | text `text_disabled` | outline 0 |
| Combo popup selected | bg accent-tinted `#3A3322`, text `accent` | bg `surface_hover` | — | — | — |
| `QSpinBox` | bg `surface`, border `border` | border `border_strong` | — | text `text_disabled` | border `focus` |
| Spin up/down button | bg `surface`, radius 5px | bg `surface_hover` | bg `surface_pressed` | — | — |
| `QCheckBox` / `QRadioButton` indicator (14px) | bg `surface`, border `border_strong` | bg `surface_hover`, border `border_strong` | bg `surface_pressed` | bg `surface`, border `border` | border `focus` |
| Indicator checked | bg `accent`, border `accent` (check glyph from Fusion, dark-on-amber) | bg `accent_hover` | bg `accent_pressed` | bg `accent_disabled` | border `accent` |
| `QGroupBox` | bg `panel`, border `border`, radius 8px; title `text_secondary` 600 | — | — | title `text_disabled` | — |
| `QScrollBar` handle | bg `scrollbar_handle` `#4A505B`, radius 6px | bg `scrollbar_handle_hover` `#5A6170` | — | — | — |
| `QToolTip` | bg `surface_hover`, border `border_strong`, text `text` | — | — | — | — |
| `QStatusBar` | bg `bg`, top border `border`, text `text_secondary` | — | — | text `text_disabled` | — |
| `QProgressBar` | bg `surface`, border `border`; chunk bg `accent` | — | — | — | — |
| `QLabel` | text `text`, bg transparent | — | — | text `text_disabled` | — |

**State cues never rely on color alone**: pressed also darkens *and* the
border stays; hover also strengthens the border; focus is a distinct 1px
outline; disabled additionally has muted text. Shape/border always reinforces
the color change.

---

## 7. Motion

Qt QSS has **no CSS transitions** — accepted. Motion budget is deliberately
tiny for a pro tool:

| Motion | Where | Spec |
|---|---|---|
| Hover color swap | buttons, combo, indicators | Instant (QSS `:hover`) — the small color deltas make it feel intentional, not jarring |
| Window appear | main window | Optional: single `QPropertyAnimation` on `windowOpacity` 0→1, **120ms**, easing `OutCubic`. Skipped by default; only added if trivial and safe offscreen. |
| Content swap | preview | Instant repaint (existing behavior) |

No animations on scroll, no button bounce, no spring effects.

---

## 8. Preview surface

- The pattern sits on a **recessed card** darker than the window (`preview_bg
  #16181C`) with a `1px border border` + `8px radius` — reads as an inset
  work surface (Photoshop's dark canvas).
- **Empty state**: when no pattern is set, the canvas paints the centered
  bilingual placeholder: "尚无图案 —— 请选择图片后点击"转换"" /
  "No pattern yet — choose an image and press Convert" (`preview_empty` key),
  in `text_secondary` at 10pt. Canvas keeps a 400×280 minimum so the
  placeholder is always legible.
- **Empty cells** (`None` code): neutral dark `#26292F` (`empty_cell`) — no
  light gray, no checkerboard (bead sheets are uniform).
- **Grid lines**: `#3A3F48` (`grid`) — subtle on dark, still visible over
  bright bead colors.
- Cell-code text contrast stays luminance-driven (threshold 140, unchanged).
- Zoom header (cell-size combo) stays above the card.

---

## 9. Accessibility

- **Contrast (WCAG AA)**: body `text` on `bg` = 13.4:1; `text_secondary`
  = 6.2:1 (both ≥ 4.5:1). `text_on_accent` on `accent` = 7.8:1. Disabled
  text is exempt (non-interactive). Empty-state text uses `text_secondary`
  (6.2:1 ✅).
- **Focus visibility**: every interactive control gets a 1px `focus`
  (amber) outline — `QPushButton:focus`, `QComboBox:focus`, `QSpinBox:focus`,
  `QCheckBox::indicator:focus`, `QRadioButton::indicator:focus`,
  `QLineEdit:focus`. Popups get `outline: 0` (the keyboard cursor inside the
  popup is the focus indicator).
- **Not color-alone**: hover/pressed/disabled all combine background *and*
  border/text changes (§6).
- **Fonts**: 9pt body, no anti-aliasing hacks; CJK renders via YaHei UI.
- **Reduced motion**: no continuous animations exist to reduce; the optional
  fade-in is a single short opacity pass (not gated, but trivially short).

---

## 10. Accepted debt

1. **No CSS transitions in Qt QSS** — state changes are instant. Mitigated
   with small, legible color deltas (§6) instead of animation.
2. **Windows-only font stack** — Segoe UI / Microsoft YaHei UI; macOS/Linux
   would need a different stack (out of scope; app is Windows-first).
3. **Check/radio glyphs are Fusion-drawn** — we style the indicator *box*
   only (background/border) and let Fusion draw the check/dot. We do not ship
   image assets for indicators (no extra deps / no asset bloat). Verified by
   the rendered screenshot.
4. **Combo popup selection uses an accent-tinted bg + amber text** rather
   than a full-amber fill — keeps long item lists readable in a dark popup
   without blowing up contrast on the whole row.
5. **Group-box titles are un-styled text in code** — the settings panel
   creates titles group boxes without captions; the QSS `QGroupBox::title`
   styling is future-proofing only.
6. **No animations on scroll / no drop shadows** — Qt QSS shadows require
   image assets; borders + layered surfaces carry the depth instead.
