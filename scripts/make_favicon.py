"""Build the site icons from the brand logo.

    python scripts/make_favicon.py

Writes, into frontend/app/ where Next.js picks them up automatically:

    favicon.ico     16 / 32 / 48 / 64 / 128 / 256, transparent
    icon.png        512, transparent - what high-DPI tabs and Android use
    apple-icon.png  180 on white - iOS composites transparency onto black

The source is a JPEG on a white field, so the white has to go or the mark
shows up as a white tile on a dark tab strip. Flooding in from the corners
rather than keying every light pixel is what keeps the capsule's white half:
keying by brightness alone punched a hole straight through the pill.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "public" / "mednuskha-logo.jpg"
OUT = ROOT / "frontend" / "app"

ICO_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
SENTINEL = (255, 0, 255)


def cut_out(path: Path) -> Image.Image:
    """The logo with the surrounding white removed, cropped to the mark."""
    im = Image.open(path).convert("RGB")

    a = np.asarray(im).astype(np.int16)
    ys, xs = np.where(a.sum(axis=2) < 720)
    pad = 6
    im = im.crop((max(0, xs.min() - pad), max(0, ys.min() - pad),
                  min(im.width, xs.max() + pad), min(im.height, ys.max() + pad)))

    flood = im.copy()
    for xy in [(0, 0), (flood.width - 1, 0),
               (0, flood.height - 1), (flood.width - 1, flood.height - 1)]:
        ImageDraw.floodfill(flood, xy, SENTINEL, thresh=70)
    f = np.asarray(flood).astype(np.int16)
    exterior = (f[:, :, 0] == 255) & (f[:, :, 1] == 0) & (f[:, :, 2] == 255)

    rgb = np.asarray(im).astype(np.float32)
    feather = np.clip((255.0 - rgb.max(axis=2)) / 55.0 * 1.3, 0, 1)
    # JPEG ringing in the white field lands at a few percent alpha. Kept, it
    # paints a faint grey rectangle around the mark that is invisible on white
    # and obvious on a dark tab strip. Anything that faint is background.
    feather = np.clip((feather - 0.35) / 0.65, 0, 1)
    alpha = np.where(exterior, feather, 1.0)

    return Image.fromarray(np.dstack([rgb, alpha * 255.0]).astype(np.uint8), "RGBA")


def square(mark: Image.Image, size: int, pad: float = 0.04,
           background: tuple | None = None) -> Image.Image:
    """Centre the mark on a square canvas, filling it as far as padding allows."""
    inner = int(size * (1 - pad * 2))
    art = mark.copy()
    art.thumbnail((inner, inner), Image.LANCZOS)

    canvas = Image.new("RGBA", (size, size), background or (0, 0, 0, 0))
    canvas.alpha_composite(art, ((size - art.width) // 2, (size - art.height) // 2))
    return canvas


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"logo not found: {SRC}")

    mark = cut_out(SRC)
    print(f"logo cut out: {mark.width}x{mark.height}")

    master = square(mark, 512)
    master.save(OUT / "favicon.ico", sizes=ICO_SIZES)
    master.save(OUT / "icon.png", optimize=True)
    square(mark, 180, pad=0.08, background=(255, 255, 255, 255)) \
        .convert("RGB").save(OUT / "apple-icon.png", optimize=True)

    for name in ("favicon.ico", "icon.png", "apple-icon.png"):
        p = OUT / name
        print(f"  {name:16} {p.stat().st_size / 1024:6.1f} KB")


if __name__ == "__main__":
    main()
