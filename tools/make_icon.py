"""Draw the app icon (flat, Editing Assistant colours): a film frame with a search lens."""
from pathlib import Path

from PIL import Image, ImageDraw

S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle([8, 8, S - 8, S - 8], radius=44, fill="#1e1e1e", outline="#3a3a3a", width=4)
# film frame
d.rounded_rectangle([40, 62, 176, 170], radius=10, outline="#c8c8c8", width=12)
for y in (78, 108, 138):
    d.rectangle([52, y, 64, y + 14], fill="#c8c8c8")
    d.rectangle([152, y, 164, y + 14], fill="#c8c8c8")
# lens
d.ellipse([112, 104, 204, 196], fill="#1e1e1e", outline="#1473e6", width=16)
d.line([190, 186, 228, 224], fill="#1473e6", width=22)
out = Path(__file__).resolve().parent.parent / "footage_finder" / "icon.ico"
img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
img.save(out.with_suffix(".png"))
print(out)
