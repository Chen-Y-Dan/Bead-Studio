"""
C0 Fork Evaluation Script for pypindou.
Creates 3 sample images and runs generate_pattern() on each.
Output is written to tests/fixtures/output/.
Also prints summary to stdout.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

from PIL import Image, ImageDraw

# ---------------------------------------------------------------------------
# 1. Create 3 sample images
# ---------------------------------------------------------------------------
FIXTURES = Path(__file__).resolve().parent
OUTPUT = FIXTURES / "output"
OUTPUT.mkdir(exist_ok=True)

# Image 1: photo-like gradient (simulates a real photo)
photo = Image.new("RGB", (128, 128))
draw = ImageDraw.Draw(photo)
for y in range(128):
    for x in range(128):
        r = int((x / 128) * 255)
        g = int((y / 128) * 200)
        b = int(((x + y) / 256) * 180 + 50)
        draw.point((x, y), (r, g, b))
photo_path = FIXTURES / "sample_photo.png"
photo.save(photo_path)
print(f"[OK] Created photo-like gradient: {photo_path} ({photo.size})")

# Image 2: cartoon/pixel-art (solid color blocks)
cartoon = Image.new("RGB", (64, 64), (30, 30, 30))  # dark bg
draw = ImageDraw.Draw(cartoon)
# sky
draw.rectangle((0, 0, 63, 20), fill=(100, 150, 255))
# sun
draw.ellipse((40, 2, 60, 22), fill=(255, 220, 50))
# ground
draw.rectangle((0, 40, 63, 63), fill=(50, 180, 60))
# house body
draw.rectangle((10, 22, 50, 45), fill=(200, 160, 100))
# roof
draw.polygon([(6, 22), (30, 8), (54, 22)], fill=(180, 50, 50))
# door
draw.rectangle((26, 30, 36, 45), fill=(120, 70, 40))
cartoon_path = FIXTURES / "sample_pixel_art.png"
cartoon.save(cartoon_path)
print(f"[OK] Created pixel-art / cartoon: {cartoon_path} ({cartoon.size})")

# Image 3: image with transparent regions (RGBA PNG with alpha)
alpha_img = Image.new("RGBA", (80, 80), (0, 0, 0, 0))  # fully transparent bg
draw = ImageDraw.Draw(alpha_img)
# Solid red circle (opaque)
draw.ellipse((5, 5, 55, 55), fill=(220, 50, 50, 255))
# Semi-transparent blue box
draw.rectangle((35, 30, 75, 70), fill=(50, 100, 220, 150))
# Solid green bar at bottom
draw.rectangle((10, 55, 70, 70), fill=(30, 200, 80, 255))
alpha_path = FIXTURES / "sample_alpha.png"
alpha_img.save(alpha_path)
print(f"[OK] Created alpha/transparent image: {alpha_path} ({alpha_img.size})")

# ---------------------------------------------------------------------------
# 2. Run pypindou generate_pattern() on each sample
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "vendor" / "pypindou"))
from pypindou import generate_pattern  # noqa: E402

results = {}

for label, img_path in [
    ("photo", photo_path),
    ("pixel_art", cartoon_path),
    ("alpha", alpha_path),
]:
    print(f"\n{'='*60}")
    print(f"Processing: {label} ({img_path})")
    try:
        # Use minimal parameters — just what's needed to test the pipeline
        p = generate_pattern(
            img_path,
            width=52,
            height=52,
            palette="mard-221-alfonse-doudou",
            color_space="lab",
            max_colors=16,
        )
        # Save outputs
        preview_path = OUTPUT / f"{label}_preview.png"
        p.to_image(scale=8).save(preview_path)

        symbol_path = OUTPUT / f"{label}_symbols.png"
        p.to_symbol_image(cell_size=16).save(symbol_path)

        legend = p.legend()
        colors_used = len(legend)
        bead_count = p.bead_count
        dims = p.board_size

        print(f"  bead_count     = {bead_count}")
        print(f"  board_size     = {dims}")
        print(f"  colors_used    = {colors_used}")
        print(f"  legend (top 5) = {json.dumps(legend[:5], indent=4)}")
        print(f"  preview saved  = {preview_path}")
        print(f"  symbols saved  = {symbol_path}")
        results[label] = {
            "status": "OK",
            "bead_count": bead_count,
            "board_size": dims,
            "colors_used": colors_used,
            "first_colors": [(r["code"], r["name"], r["count"]) for r in legend[:5]],
        }
    except Exception:
        print(f"  FAILED: {traceback.format_exc()}")
        results[label] = {"status": "FAIL", "error": traceback.format_exc()}

print(f"\n{'='*60}")
print("SUMMARY:")
print(json.dumps(results, indent=2))

# Write results to JSON for FORK.md
(FIXTURES / "fork_eval_results.json").write_text(json.dumps(results, indent=2))
print(f"\nResults written to {FIXTURES / 'fork_eval_results.json'}")
