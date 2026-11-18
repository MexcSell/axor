#!/usr/bin/env python3
"""Rebuilds the portrait behind AXoR's animated backdrop (frontend/backdrop.js, "Neural Renaissance") from the public-domain
Mona Lisa on Wikimedia Commons, and draws a check image with backdrop.js's facial contours over the result.

    python3 tools/backdrop-portrait.py                      download the source, write frontend/brand/neural-portrait.webp
    python3 tools/backdrop-portrait.py --src mona.jpg       use a copy you already have (any size of the same scan)
    python3 tools/backdrop-portrait.py --check check.png    also write the contour check image (portrait as the page shows it)

Needs Pillow and numpy (pip install pillow numpy). The output is a grayscale image whose alpha holds the vignette; backdrop.js
tints it to the theme. The contours in backdrop.js (FACE) are fractions of this crop: change CROP and they must be measured
again, which is what the check image is for (red lines should sit on her jaw, eyes, brows, nose and mouth).
"""
import argparse, io, json, re, sys, urllib.request
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageDraw
except ImportError:
    sys.exit("Needs Pillow and numpy: pip install pillow numpy")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend/brand/neural-portrait.webp"
SOURCE = ("https://upload.wikimedia.org/wikipedia/commons/thumb/e/ec/Mona_Lisa%2C_by_Leonardo_da_Vinci%2C_from_C2RMF_retouched.jpg/"
          "960px-Mona_Lisa%2C_by_Leonardo_da_Vinci%2C_from_C2RMF_retouched.jpg")
REF_W = 960                        # CROP is in pixels of the 960 px wide scan; other sizes are scaled to it
CROP = (90, 60, 810, 960)          # head and shoulders, down to above her hands
SIZE = (600, 750)


def load(src):
    if src:
        return Image.open(src).convert("RGB")
    req = urllib.request.Request(SOURCE, headers={"User-Agent": "axor-backdrop-portrait/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return Image.open(io.BytesIO(r.read())).convert("RGB")


def build(im):
    k = im.width / REF_W
    im = im.crop(tuple(round(v * k) for v in CROP)).resize(SIZE, Image.LANCZOS)
    W, H = SIZE
    a = np.asarray(im).astype(np.float32) / 255
    L = a[..., 0] * .2126 + a[..., 1] * .7152 + a[..., 2] * .0722
    L = np.clip((L - .10) / .72, 0, 1) ** 1.15            # lift the face, sink the varnish
    yy, xx = np.mgrid[0:H, 0:W]
    d = np.sqrt(((xx - .47 * W) / (.50 * W)) ** 2 + ((yy - .50 * H) / (.56 * H)) ** 2)
    A = np.clip((1 - d) / .45, 0, 1); A = A * A * (3 - 2 * A)  # an ellipse around head and shoulders
    A *= np.clip((H - yy) / (.18 * H), 0, 1)               # fade out before the hands
    g = (L * 255).astype(np.uint8)
    return Image.fromarray(np.dstack([g, g, g, (A * 255).astype(np.uint8)]), "RGBA")


def contours():
    js = (ROOT / "frontend/backdrop.js").read_text()
    body = re.search(r"const FACE = \{(.*?)\n  \};", js, re.S)
    if not body:
        sys.exit("Couldn't find FACE in frontend/backdrop.js")
    src = re.sub(r"(\w+):", r'"\1":', body.group(1))
    src = re.sub(r"(?<![\d])\.(\d)", r"0.\1", src)
    return json.loads("{" + src.strip().rstrip(",") + "}")


def check(portrait, path):
    W, H = portrait.size
    p = np.asarray(portrait).astype(np.float32) / 255
    al = (p[..., 3] * (.1 + .9 * p[..., 0]) * .26)[..., None]  # dark mode, Subtle, accent emerald: as backdrop.js draws it
    bg, tint = np.array([10, 15, 23], np.float32), np.array([40, 220, 170], np.float32)
    c = Image.fromarray((bg * (1 - al) + tint * al).astype(np.uint8))
    d = ImageDraw.Draw(c)
    for pts in contours().values():
        d.line([(x * W, y * H) for x, y in pts], fill=(255, 80, 80), width=1)
    side = Image.new("RGB", (W * 2, H), (10, 15, 23))
    side.paste(c, (0, 0)); side.paste(portrait.convert("RGB"), (W, 0))
    side.save(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--src", help="a local copy of the C2RMF scan instead of downloading it")
    ap.add_argument("--out", default=str(OUT), help=f"where to write the portrait (default {OUT.relative_to(ROOT)})")
    ap.add_argument("--check", metavar="PNG", help="also write a check image: the portrait as the page shows it, with the contours")
    ap.add_argument("--quality", type=int, default=72, help="WebP quality (default 72, about 100 kB)")
    a = ap.parse_args()
    portrait = build(load(a.src))
    portrait.save(a.out, "WEBP", quality=a.quality, method=6)
    print(f"wrote {a.out} ({Path(a.out).stat().st_size // 1024} kB, {portrait.width}x{portrait.height})")
    if a.check:
        check(portrait, a.check)
        print(f"wrote {a.check}")


if __name__ == "__main__":
    main()
