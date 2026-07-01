"""
Generate BMW roundel icon and logo for the integration brand.
Run from repo root: python -m custom_components.bmw_cardata.brand.generate_brand
Requires: pip install Pillow
"""
from __future__ import annotations

import math
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    raise SystemExit("Install Pillow: pip install Pillow")

# BMW roundel colors (approximate)
BLUE = (0, 102, 153)  # BMW blue
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
TRANSPARENT = (0, 0, 0, 0)

BRAND_DIR = Path(__file__).resolve().parent


def draw_roundel(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int, ring: int) -> None:
    """Draw BMW-style roundel: outer black ring, then quadrants blue/white."""
    # Outer black ring
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=BLACK, outline=BLACK)
    inner = r - ring
    # Inner circle (will be clipped by quadrants)
    draw.ellipse([cx - inner, cy - inner, cx + inner, cy + inner], fill=WHITE, outline=None)
    # Quadrants: blue top-left (135-225°), bottom-right (315-45°); white the rest
    for i in range(360):
        angle = math.radians(i)
        next_angle = math.radians(i + 1)
        # Mid-angle for quadrant
        mid = math.radians(i + 0.5)
        # Blue if mid in [135, 225] or [315, 45] (wrapping)
        deg = math.degrees(mid) % 360
        is_blue = (45 <= deg <= 135) or (225 <= deg <= 315)
        color = BLUE if is_blue else WHITE
        x1 = cx + inner * math.cos(angle)
        y1 = cy - inner * math.sin(angle)
        x2 = cx + inner * math.cos(next_angle)
        y2 = cy - inner * math.sin(next_angle)
        draw.polygon([cx, cy, x1, y1, x2, y2], fill=color, outline=color)
    # Black ring inner edge
    draw.ellipse([cx - inner, cy - inner, cx + inner, cy + inner], outline=BLACK, width=max(1, ring // 4))


def make_icon(size: int = 256) -> Image.Image:
    im = Image.new("RGBA", (size, size), TRANSPARENT)
    draw = ImageDraw.Draw(im)
    cx = cy = size // 2
    r = size // 2 - 2
    ring = max(2, size // 16)
    draw_roundel(draw, cx, cy, r, ring)
    return im


def make_logo(width: int = 256, height: int = 128) -> Image.Image:
    im = Image.new("RGBA", (width, height), TRANSPARENT)
    draw = ImageDraw.Draw(im)
    cx, cy = width // 2, height // 2
    r = min(width, height) // 2 - 2
    ring = max(2, r // 8)
    draw_roundel(draw, cx, cy, r, ring)
    return im


def main() -> None:
    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    icon = make_icon(256)
    icon.save(BRAND_DIR / "icon.png", "PNG", optimize=True)
    logo = make_logo(256, 128)
    logo.save(BRAND_DIR / "logo.png", "PNG", optimize=True)
    print("Generated brand/icon.png and brand/logo.png")


if __name__ == "__main__":
    main()
