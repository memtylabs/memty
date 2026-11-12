"""Build clean Chrome extension icons from the Memty logo PNG.

Usage: python scripts/make_extension_icons.py static/assets/memty_browser_extention.png memty/integrations/browser/extension/icons preview.png
(needs Pillow, NumPy, SciPy)
"""
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

src, out = Path(sys.argv[1]), Path(sys.argv[2])
im = np.array(Image.open(src).convert("RGBA")).astype(np.float32)
alpha = im[..., 3]

# 1. Drop the faint haze and isolated specks (keep only large solid shapes).
solid = alpha >= 128
labels, n = ndimage.label(solid)
sizes = ndimage.sum(solid, labels, range(1, n + 1))
keep = np.isin(labels, 1 + np.flatnonzero(sizes >= 2000))
keep = ndimage.binary_opening(keep, iterations=2)          # shave speckled fringes
keep = ndimage.binary_fill_holes(keep) & (keep | solid)    # never fill the logo's real gaps
soft = ndimage.gaussian_filter(keep.astype(np.float32), 0.8)  # anti-aliased edge
im[..., 3] = np.clip(soft * 255, 0, 255) * (alpha > 0)
im[..., 3] = np.where(keep, 255, im[..., 3])

# 2. Crop to the artwork and make it square.
ys, xs = np.where(im[..., 3] > 8)
art = Image.fromarray(im[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.uint8), "RGBA")
side = max(art.size)
square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
square.paste(art, ((side - art.width) // 2, (side - art.height) // 2))


def icon(size: int, pad_ratio: float, halo_ratio: float) -> Image.Image:
    """Logo with transparent padding and a white halo so it reads on dark toolbars."""
    big = 1024
    canvas_art = int(big * (1 - 2 * pad_ratio))
    glyph = square.resize((canvas_art, canvas_art), Image.LANCZOS)
    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    offset = (big - canvas_art) // 2
    canvas.paste(glyph, (offset, offset), glyph)
    a = np.array(canvas)[..., 3] > 40
    radius = max(1, int(big * halo_ratio))
    # Outline the outer silhouette only: close the inner gaps first, then keep the ring.
    pad = 60
    padded = np.pad(a, pad)
    closed = ndimage.binary_closing(padded, structure=np.ones((3, 3)), iterations=45)[pad:-pad, pad:-pad]
    closed = ndimage.binary_fill_holes(closed | a)
    halo = ndimage.binary_dilation(closed, iterations=radius) & ~closed | a
    halo_img = Image.fromarray((halo * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(radius * 0.25))
    base = Image.new("RGBA", (big, big), (255, 255, 255, 0))
    base.putalpha(halo_img.point(lambda v: int(v * 0.95)))
    base.alpha_composite(canvas)
    return base.resize((size, size), Image.LANCZOS)


out.mkdir(parents=True, exist_ok=True)
# Toolbar sizes use almost the whole square; 128 follows the Web Store's 96px-art-in-128 rule.
specs = {16: (0.02, 0.035), 32: (0.03, 0.03), 48: (0.06, 0.025), 128: (0.125, 0.018)}
for size, (pad, halo) in specs.items():
    icon(size, pad, halo).save(out / f"icon{size}.png", optimize=True)
    print("wrote", out / f"icon{size}.png")

# Preview on light and dark toolbars, 8x enlarged for inspection.
row = []
for bg in ((255, 255, 255), (53, 54, 58)):
    strip = Image.new("RGB", (16 * 8 + 32 * 8 + 48 * 4 + 128 * 2 + 50, 300), bg)
    x = 10
    for size, scale in ((16, 8), (32, 8), (48, 4), (128, 2)):
        img = Image.open(out / f"icon{size}.png").resize((size * scale, size * scale), Image.NEAREST)
        strip.paste(img, (x, 10), img)
        x += size * scale + 10
    row.append(strip)
preview = Image.new("RGB", (row[0].width, 600))
preview.paste(row[0], (0, 0)); preview.paste(row[1], (0, 300))
preview.save(Path(sys.argv[3]))
