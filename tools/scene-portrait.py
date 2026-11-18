#!/usr/bin/env python3
"""Builds the colour cut-out of the Mona Lisa that sits in the Control Hub scene (frontend/control-scene.js, D-028), from the same
public-domain Wikimedia Commons scan as the animated backdrop (tools/backdrop-portrait.py).

    python3 tools/scene-portrait.py                     download the source, write frontend/brand/scene-portrait.webp
    python3 tools/scene-portrait.py --src mona.jpg      use a copy you already have (the 960 px wide scan)
    python3 tools/scene-portrait.py --check check.jpg   also write a check image (figure kept, background darkened)

Needs Pillow, numpy and OpenCV (pip install pillow numpy opencv-python-headless). The figure is separated from the landscape
with GrabCut seeded by the hints below (pixels of the 960 px scan); the result keeps her colours, with a feathered edge and the
lower robe fading out, so the scene's console reads in front of her lap.
"""
import argparse, io, sys, urllib.request
from pathlib import Path

try:
    import cv2
    import numpy as np
    from PIL import Image
except ImportError:
    sys.exit("Needs Pillow, numpy and OpenCV: pip install pillow numpy opencv-python-headless")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend/brand/scene-portrait.webp"
SOURCE = ("https://upload.wikimedia.org/wikipedia/commons/thumb/e/ec/Mona_Lisa%2C_by_Leonardo_da_Vinci%2C_from_C2RMF_retouched.jpg/"
          "960px-Mona_Lisa%2C_by_Leonardo_da_Vinci%2C_from_C2RMF_retouched.jpg")
REF_W = 960
CROP = (0, 110, 960, 1300)        # top of her veil down to her hands
WIDTH = 560                       # output width; height follows the crop
# GrabCut hints in pixels of the 960 px scan
SURE_FG = [("ellipse", (480, 400), (110, 150)), ("rect", (330, 600), (660, 1300))]
LIKELY_FG = [("rect", (230, 900), (780, 1350)),
             ("poly", [[340, 140], [620, 140], [700, 330], [720, 620], [850, 820], [930, 1050], [950, 1431], [10, 1431], [60, 1050], [180, 780], [260, 600], [270, 330]])]
SURE_BG = [[[40, 60], [300, 60], [230, 500], [40, 700]], [[660, 60], [920, 60], [920, 650], [730, 520]],          # sky beside her head
           [[40, 540], [290, 540], [300, 630], [70, 920], [40, 920]], [[690, 520], [920, 520], [920, 890], [860, 880], [670, 640]]]  # landscape over her shoulders


def load(src):
    if src:
        data = Path(src).read_bytes()
    else:
        req = urllib.request.Request(SOURCE, headers={"User-Agent": "axor-scene-portrait/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
    im = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if im.shape[1] != REF_W:
        im = cv2.resize(im, (REF_W, round(im.shape[0] * REF_W / im.shape[1])), interpolation=cv2.INTER_AREA)
    return im


def cut(im):
    h, w = im.shape[:2]
    mask = np.full((h, w), cv2.GC_PR_BGD, np.uint8)
    mask[:, :40] = mask[:, -40:] = cv2.GC_BGD
    mask[:60, :] = cv2.GC_BGD
    for kind, *a in LIKELY_FG:
        if kind == "rect": cv2.rectangle(mask, a[0], a[1], cv2.GC_PR_FGD, -1)
        else:
            m = np.zeros_like(mask); cv2.fillPoly(m, [np.array(a[0])], 1)
            mask[(m == 1) & (mask == cv2.GC_PR_BGD)] = cv2.GC_PR_FGD
    for kind, *a in SURE_FG:
        if kind == "rect": cv2.rectangle(mask, a[0], a[1], cv2.GC_FGD, -1)
        else: cv2.ellipse(mask, a[0], a[1], 0, 0, 360, cv2.GC_FGD, -1)
    for p in SURE_BG:
        cv2.fillPoly(mask, [np.array(p)], cv2.GC_BGD)
    cv2.setRNGSeed(7)
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.grabCut(im, mask, None, bgd, fgd, 6, cv2.GC_INIT_WITH_MASK)
    m = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(m)
    return np.where(lab == 1 + np.argmax(st[1:, cv2.CC_STAT_AREA]), 255, 0).astype(np.uint8)


def build(im, m):
    x0, y0, x1, y1 = CROP
    rgb, a = im[y0:y1, x0:x1], m[y0:y1, x0:x1].astype(np.float32) / 255
    a = cv2.GaussianBlur(a, (0, 0), 2.2)                                  # feathered edge
    hh = a.shape[0]
    fade = np.clip((hh - np.arange(hh)) / (hh * .22), 0, 1) ** 1.4      # the lower robe fades into the console
    a *= fade[:, None]
    out = np.dstack([cv2.cvtColor(rgb, cv2.COLOR_BGR2RGB), (a * 255).astype(np.uint8)])
    img = Image.fromarray(out, "RGBA")
    return img.resize((WIDTH, round(img.height * WIDTH / img.width)), Image.LANCZOS)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", help="local copy of the scan")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--check", help="write a check image of the cut")
    a = ap.parse_args()
    im = load(a.src)
    m = cut(im)
    build(im, m).save(a.out, "WEBP", quality=84, method=6)
    print(f"wrote {a.out}")
    if a.check:
        chk = im.copy()
        chk[m == 0] = (chk[m == 0] * .25 + np.array([60, 20, 0]) * .75).astype(np.uint8)
        cv2.imwrite(a.check, cv2.resize(chk, (480, round(480 * im.shape[0] / im.shape[1]))))
        print(f"wrote {a.check}")


if __name__ == "__main__":
    main()
