# Brand assets

This folder contains the BMW roundel icon and logo used by Home Assistant for the integration card and setup flow.

- **icon.png** – 256×256 square icon
- **logo.png** – 256×128 logo

The integration registers the brand folder so the icon can be used when Home Assistant’s brands API supports it. If the integration card still shows **"icon not available"**:

- **Home Assistant 2026.3+**: The brands proxy may use this folder automatically; try a full restart and a browser cache refresh.
- **Any version**: For a guaranteed fix, submit these files to the [Home Assistant brands repository](https://github.com/home-assistant/brands) under `custom_integrations/bmw_cardata/`. Run `python custom_components/bmw_cardata/brand/prepare_brands_pr.py` to prepare the files, then open a PR as described in the main README.

To regenerate (e.g. after changing colors or size), install Pillow and run from the repo root:

```bash
pip install Pillow
python custom_components/bmw_cardata/brand/generate_brand.py
```
