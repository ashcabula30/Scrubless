"""Draw the app icon in Riff's icon style: a muted violet 12-lobe "cookie" badge with one chunky,
puffy lavender shape (overlapping soft circles), flat two-tone, no strokes. The shape is a magnifier:
a lens ring of circles like Riff's ring, plus a rounded handle.

Writes footage_finder/icon.ico (all Windows sizes), icon.png (README) and ui/public/logo.svg (app).
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
BADGE, SHAPE = "#554971", "#C0A9F5"  # sampled from Riff's assets/icon.png


def cookie(cx, cy, r, lobes=12, depth=0.055, steps=1440):
    """Points of a scalloped circle: the radius wobbles with `lobes` bumps."""
    return [(cx + r * (1 + depth * math.cos(lobes * a)) * math.cos(a), cy + r * (1 + depth * math.cos(lobes * a)) * math.sin(a))
            for a in (2 * math.pi * i / steps for i in range(steps))]


def shape_circles(size):
    """The magnifier as (x, y, r) circles in a size x size canvas."""
    s = size / 100
    cx, cy, ring, bumps = 43 * s, 42 * s, 20 * s, 12
    circles = []
    for i in range(bumps):
        a = 2 * math.pi * i / bumps - math.pi / 2
        r = (8.0 + 1.2 * math.sin(3 * a + 0.6)) * s  # slightly uneven bumps, like Riff's ring
        circles.append((cx + ring * math.cos(a), cy + ring * math.sin(a), r))
    # handle: three overlapping circles down-right from the ring
    a = math.pi / 4
    for d, r in ((29.5, 8.2), (35.5, 8.7), (41.5, 9.2)):
        circles.append((cx + d * s * math.cos(a), cy + d * s * math.sin(a), r * s))
    return circles


def draw(size):
    ss = 4  # supersample, then downscale for smooth edges
    S = size * ss
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.polygon(cookie(S / 2, S / 2, S * 0.47), fill=BADGE)
    for x, y, r in shape_circles(S):
        d.ellipse([x - r, y - r, x + r, y + r], fill=SHAPE)
    return img.resize((size, size), Image.LANCZOS)


def svg():
    pts = cookie(50, 50, 47, steps=360)
    path = "M" + " L".join(f"{x:.2f} {y:.2f}" for x, y in pts) + " Z"
    dots = "".join(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{r:.2f}"/>' for x, y, r in shape_circles(100))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            f'<path d="{path}" fill="{BADGE}"/><g fill="{SHAPE}">{dots}</g></svg>')


big = draw(256)
# self-check: badge colour at the edge area, lavender on the ring, badge (not lavender) in the lens hole
px = lambda x, y: "#%02x%02x%02x" % big.getpixel((x, y))[:3]
assert px(128, 20).lower() == BADGE.lower(), px(128, 20)
assert px(round(2.56 * 43), round(2.56 * (42 - 20))).lower() == SHAPE.lower()
assert px(round(2.56 * 43), round(2.56 * 42)).lower() == BADGE.lower(), "lens should be open"
ico = ROOT / "footage_finder" / "icon.ico"
big.save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
big.save(ico.with_suffix(".png"))
(ROOT / "ui" / "public").mkdir(exist_ok=True)
(ROOT / "ui" / "public" / "logo.svg").write_text(svg(), encoding="utf-8")
print(ico)
