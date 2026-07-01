#!/usr/bin/env python3
"""
Copy brand assets into a structure ready for a PR to the Home Assistant brands repo.
Run from the repo root. Creates brand_for_ha_brands/ with the files and instructions.

Usage:
  python custom_components/bmw_cardata/brand/prepare_brands_pr.py

Then:
  1. Fork https://github.com/home-assistant/brands
  2. Create folder custom_integrations/bmw_cardata/ in your fork
  3. Copy icon.png and logo.png from brand_for_ha_brands/bmw_cardata/ into that folder
  4. Open a PR to home-assistant/brands
  5. After merge, the icon will appear in Settings > Integrations (may take a short while for CDN)
"""

from __future__ import annotations

import shutil
from pathlib import Path

BRAND_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "brand_for_ha_brands" / "bmw_cardata"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("icon.png", "logo.png"):
        src = BRAND_DIR / name
        if src.is_file():
            shutil.copy2(src, OUTPUT_DIR / name)
            print(f"Copied {name}")
        else:
            print(f"Skip (missing): {name}")
    readme = OUTPUT_DIR / "README.txt"
    readme.write_text(
        "Add these files to your fork of home-assistant/brands:\n"
        "  custom_integrations/bmw_cardata/icon.png\n"
        "  custom_integrations/bmw_cardata/logo.png\n"
        "\n"
        "Then open a PR. See: https://github.com/home-assistant/brands\n",
        encoding="utf-8",
    )
    print(f"Output: {OUTPUT_DIR}")
    print("See custom_components/bmw_cardata/brand/README.md for PR steps.")


if __name__ == "__main__":
    main()
