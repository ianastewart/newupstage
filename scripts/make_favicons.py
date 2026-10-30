"""
Make the site's favicons from the logo in the image library, on a dark purple square: the whole white wordmark for the
large icon, and just its "UP" lettering for the small ones (the whole wordmark is too wide to read at 16 or 32 pixels).
Usage:  python scripts/make_favicons.py [logo file]      (default: upstage/media/images/upstage_surrey.webp)
Writes favicon.ico, favicon-16.png, favicon-32.png and apple-touch-icon.png to upstage/backstage/static/favicon/.
"""
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
LOGO = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "upstage/media/images/upstage_surrey.webp"
OUT = ROOT / "upstage/backstage/static/favicon"
BACKGROUND = (20, 14, 33, 255)  # the dark of the upstage-spotlight theme
PADDING = 0.06  # of the icon's width, each side
UP_BOX = (66, 66, 352, 296)  # "UP" and its underline, in the 1191 x 469 logo's pixels


def icon(logo, size):
    """The logo, scaled to fit across the square with a margin, on the background."""
    canvas = Image.new("RGBA", (size, size), BACKGROUND)
    room = round(size * (1 - 2 * PADDING))
    scale = room / max(logo.size)
    fitted = logo.resize((max(1, round(logo.width * scale)), max(1, round(logo.height * scale))), Image.LANCZOS)
    canvas.alpha_composite(fitted, ((size - fitted.width) // 2, (size - fitted.height) // 2))
    return canvas


full = Image.open(LOGO).convert("RGBA")
up = full.crop(UP_BOX)
full = full.crop(full.getbbox())  # drop the empty margin round the wordmark
OUT.mkdir(parents=True, exist_ok=True)
icon(full, 180).save(OUT / "apple-touch-icon.png")
icon(up, 16).save(OUT / "favicon-16.png")
icon(up, 32).save(OUT / "favicon-32.png")
icon(up, 256).save(OUT / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
print("Wrote", ", ".join(sorted(path.name for path in OUT.iterdir())))
