"""Print the dominant colors of the APORTIL logo so the theme variables can match it.

Usage: python scripts/logo_palette.py main/static/main/images/logo.png
"""
import sys
from collections import Counter

from PIL import Image

im = Image.open(sys.argv[1]).convert("RGBA")
im.thumbnail((120, 120))
px = [(r // 16 * 16, g // 16 * 16, b // 16 * 16) for r, g, b, a in (im.get_flattened_data() if hasattr(im, "get_flattened_data") else im.getdata()) if a > 200]
for (r, g, b), n in Counter(px).most_common(8):
	print(f"#{r:02x}{g:02x}{b:02x}  {n}")
