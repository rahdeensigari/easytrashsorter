#!/usr/bin/env python3
"""Build a training set sorted by ITEM TYPE (the classes in rulebook.py) from TrashNet + TrashBox.

Usage: build_items.py <trashnet_resized_dir> <trashbox_subfolders_dir> <out_dir>
Output: out_dir/<item_type>/*.jpg  (RGB JPEG, max side 384). battery and light_bulb have no public
images here: photograph them with collect.py.
"""
import random
import sys
from pathlib import Path

from PIL import Image

tn, tb, out = (Path(p) for p in sys.argv[1:4])
random.seed(7)
EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
N = 160

PLAN = {
    "aluminum_steel_can": [(tb / "metal/beverage cans", 90, "tbcan"), (tb / "metal/metal containers", 40, "tbmc"), (tn / "metal", 30, "tnmetal")],
    "spray_can":          [(tb / "metal/spray cans", N, "tbspray")],
    "plastic_bottle":     [(tb / "plastic/plastic bottles", N, "tbbottle")],
    "plastic_container":  [(tb / "plastic/plastic containers", N, "tbcont")],
    "plastic_cup":        [(tb / "plastic/plastic cups", N, "tbcup")],
    "plastic_bag":        [(tb / "plastic/plastic bags", N, "tbbag")],
    "cardboard":          [(tn / "cardboard", 80, "tncard"), (tb / "cardboard", 80, "tbcard")],
    "paper":              [(tn / "paper", 80, "tnpaper"), (tb / "paper/paper", 80, "tbpaper")],
    "newspaper":          [(tb / "paper/news paper", N, "tbnews")],
    "paper_cup":          [(tb / "paper/paper cups", N, "tbpcup")],
    "carton":             [(tb / "paper/tetra pak", N, "tbcarton")],
    "glass":              [(tn / "glass", 80, "tnglass"), (tb / "glass", 80, "tbglass")],
    "cigarette_butt":     [(tb / "plastic/cigarette butt", N, "tbcig")],
    "gloves_masks":       [(tb / "medical/gloves", 80, "tbglove"), (tb / "medical/masks", 80, "tbmask")],
    "medicine":           [(tb / "medical/medicines", N, "tbmed")],
    "sharps":             [(tb / "medical/syringe", N, "tbsyr")],
    "electronics":        [(tb / "e-waste/laptops", 40, "tblap"), (tb / "e-waste/smartphones", 40, "tbphone"),
                           (tb / "e-waste/small appliances", 40, "tbappl"), (tb / "e-waste/electronic chips", 40, "tbchip")],
    "cables":             [(tb / "e-waste/electrical cables", N, "tbcable")],
    "building_material":  [(tb / "metal/construction scrap", N, "tbscrap")],
    "other_trash":        [(tn / "trash", 137, "tntrash")],
}

total = 0
for cls, sources in PLAN.items():
    dest = out / cls
    dest.mkdir(parents=True, exist_ok=True)
    n_cls = 0
    for folder, n, prefix in sources:
        files = sorted(f for f in folder.rglob("*") if f.suffix.lower() in EXT)
        random.shuffle(files)
        kept = 0
        for f in files:
            if kept >= n:
                break
            try:
                with Image.open(f) as im:
                    im = im.convert("RGB")
                    if min(im.size) < 100:
                        continue
                    im.thumbnail((384, 384))
                    im.save(dest / f"{prefix}_{kept:03d}.jpg", quality=85)
                kept += 1
            except Exception:
                continue
        if kept < n:
            print(f"  note: {prefix} gave {kept}/{n} (only {len(files)} files)")
        n_cls += kept
    total += n_cls
    print(f"{cls:20s} {n_cls}")
print("total", total)
