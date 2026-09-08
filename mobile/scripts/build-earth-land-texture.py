"""Rebuild the offline Earth mask from the project's public-domain Natural Earth data.

Run from any directory with Python and Pillow. This is geographic rasterization,
not generated artwork; no remote downloads or runtime map services are involved.
"""

import base64
import json
from itertools import groupby
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "assets/branding/global-connect/journey-film/source/ne_110m_land.geojson"
TARGET = ROOT / "mobile/assets/maps/earth-land.png"
PIXEL_TARGET = TARGET.with_name("earth-land-mask.json")
WIDTH, HEIGHT, SCALE = 2048, 1024, 2
image = Image.new("L", (WIDTH * SCALE, HEIGHT * SCALE))
draw = ImageDraw.Draw(image)


def polygon(rings):
    for index, ring in enumerate(rings):
        points = [
            ((lon + 180) / 360 * WIDTH * SCALE, (90 - lat) / 180 * HEIGHT * SCALE)
            for lon, lat in ring
        ]
        draw.polygon(points, fill=255 if index == 0 else 0)


for feature in json.loads(SOURCE.read_text(encoding="utf-8"))["features"]:
    geometry = feature["geometry"]
    if geometry["type"] == "Polygon":
        polygon(geometry["coordinates"])
    elif geometry["type"] == "MultiPolygon":
        for rings in geometry["coordinates"]:
            polygon(rings)

TARGET.parent.mkdir(parents=True, exist_ok=True)
mask = image.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
mask.convert("RGB").save(TARGET, optimize=True)
# The GPU consumes these exact pixels, not a platform-decoded Android drawable.
# A run is one grayscale byte followed by its unsigned big-endian 16-bit length.
# Keep antialiased coastline values lossless; split runs exceeding 65535 pixels.
encoded = bytearray()
for value, group in groupby(mask.tobytes()):
    remaining = sum(1 for _ in group)
    while remaining:
        count = min(remaining, 65535)
        encoded.extend((value, count >> 8, count & 255))
        remaining -= count
PIXEL_TARGET.write_text(json.dumps({
    "encoding": "rle8-v1",
    "width": WIDTH,
    "height": HEIGHT,
    "data": base64.b64encode(encoded).decode("ascii"),
}, separators=(",", ":")) + "\n", encoding="utf-8")
print(f"Created {TARGET.relative_to(ROOT)} ({WIDTH} x {HEIGHT})")
print(f"Created {PIXEL_TARGET.relative_to(ROOT)} (lossless GPU pixels)")
