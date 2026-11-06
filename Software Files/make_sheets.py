#!/usr/bin/env python3
"""Contact sheets for labeling by eye. Usage: make_sheets.py <photo_dir> <prefix> <out_dir> [per_sheet]"""
import sys, os
from PIL import Image, ImageDraw, ImageFont
src, prefix, out = sys.argv[1:4]
per = int(sys.argv[4]) if len(sys.argv) > 4 else 40
files = sorted(f for f in os.listdir(src) if f.lower().endswith(".jpg"))
cols, rows, T = 8, 5, 170
font = ImageFont.load_default(size=22)
with open(os.path.join(out, f"{prefix}_files.txt"), "w") as f:
    f.write("\n".join(files))
for s in range(0, len(files), per):
    chunk = files[s:s + per]
    sheet = Image.new("RGB", (cols * T, rows * T), "white")
    d = ImageDraw.Draw(sheet)
    for i, name in enumerate(chunk):
        im = Image.open(os.path.join(src, name)).convert("RGB"); im.thumbnail((T - 4, T - 4))
        x, y = (i % cols) * T, (i // cols) * T
        sheet.paste(im, (x + 2, y + 2))
        d.rectangle([x, y, x + 34, y + 26], fill="black"); d.text((x + 3, y + 1), str(i + 1), fill="yellow", font=font)
        d.rectangle([x, y, x + T - 1, y + T - 1], outline="#888", width=1)
    sheet.save(os.path.join(out, f"{prefix}_{s // per + 1:02d}.jpg"), quality=82)
print(len(files), "photos,", (len(files) + per - 1) // per, "sheets")
