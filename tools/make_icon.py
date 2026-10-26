"""Draw the app icon: a Material 3 Expressive "cookie" (scalloped) shape in lavender with a lens.

Writes footage_finder/icon.ico (all Windows sizes), icon.png (README) and ui/public/logo.svg (sidebar).
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
LAVENDER, ON_PRIMARY, CONTAINER = "#D0BCFF", "#381E72", "#4F378B"


def cookie(cx, cy, r, lobes=9, depth=0.075, steps=720):
    """Points of a scalloped circle: radius wobbles with `lobes` bumps."""
    return [(cx + r * (1 + depth * math.cos(lobes * a)) * math.cos(a - math.pi / 2),
             cy + r * (1 + depth * math.cos(lobes * a)) * math.sin(a - math.pi / 2))
            for a in (2 * math.pi * i / steps for i in range(steps))]


def draw(size):
    s = 4  # supersample, then downscale for smooth edges
    S = size * s
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.polygon(cookie(S / 2, S / 2, S * 0.43), fill=LAVENDER)
    # lens: ring + handle, centred slightly up-left
    cx, cy, rr, w = S * 0.46, S * 0.45, S * 0.17, S * 0.065
    d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=ON_PRIMARY, width=int(w))
    d.line([cx + rr * 0.72, cy + rr * 0.72, S * 0.70, S * 0.69], fill=ON_PRIMARY, width=int(w * 1.05))
    d.ellipse([S * 0.70 - w / 2, S * 0.69 - w / 2, S * 0.70 + w / 2, S * 0.69 + w / 2], fill=ON_PRIMARY)
    # play triangle inside the lens: footage
    t = rr * 0.42
    d.polygon([(cx - t * 0.55, cy - t), (cx - t * 0.55, cy + t), (cx + t, cy)], fill=CONTAINER)
    return img.resize((size, size), Image.LANCZOS)


def svg():
    pts = cookie(50, 50, 43, steps=180)
    path = "M" + " L".join(f"{x:.2f} {y:.2f}" for x, y in pts) + " Z"
    cx, cy, rr = 46, 45, 17
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            f'<path d="{path}" fill="{LAVENDER}"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{rr}" fill="none" stroke="{ON_PRIMARY}" stroke-width="6.5"/>'
            f'<path d="M{cx + rr * .72:.1f} {cy + rr * .72:.1f} L70 69" stroke="{ON_PRIMARY}" stroke-width="6.8" stroke-linecap="round"/>'
            f'<path d="M{cx - 3.9:.1f} {cy - 7.1:.1f} V{cy + 7.1:.1f} L{cx + 7.1:.1f} {cy} Z" fill="{CONTAINER}"/></svg>')


big = draw(256)
assert big.getpixel((128, 128))[3] > 0, "icon centre should be painted"
ico = ROOT / "footage_finder" / "icon.ico"
big.save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
big.save(ico.with_suffix(".png"))
(ROOT / "ui" / "public").mkdir(exist_ok=True)
(ROOT / "ui" / "public" / "logo.svg").write_text(svg(), encoding="utf-8")
print(ico)
