#!/usr/bin/env python3
"""
organize_photos.py: sort a pile of photos into folders by object type, using your trained model.

    python3 organize_photos.py trashnet/plastic trashnet/metal --out sorted_photos
    python3 organize_photos.py Recycling --out sorted_recycling --min-confidence 0.9
    python3 organize_photos.py trashnet --out sorted --dry-run        # just show the counts, copy nothing

Every photo goes to  <out>/<what the model thinks it is>/ . If the model is not sure (below
--min-confidence, default 0.85) the photo goes to <out>/_unsure/ for you to sort by hand.
Your original photos are only COPIED, never moved or changed. A list of every decision is saved to
<out>/report.csv.

The model can only use names it was trained on. To split TrashNet's "plastic" photos into bottles, cups,
bags and containers, first train on photos that already have those folders (item_types_training_set),
then run this on the plastic photos:
    python3 recognize.py train item_types_training_set
    python3 organize_photos.py trashnet/plastic --out plastic_sorted
It is not perfect. Look through each folder afterwards and move the ones that landed in the wrong place.

Needs recognize.py and model_local.npz (from "recognize.py train") in the same folder.
"""
import argparse
import csv
import os
import shutil
import sys
from collections import Counter

import numpy as np

import recognize

EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def find_photos(folders):
    paths = []
    for root in folders:
        if os.path.isfile(root) and os.path.splitext(root)[1].lower() in EXT:
            paths.append(root)
            continue
        if not os.path.isdir(root):
            raise SystemExit(f"Folder not found: {root}")
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith((".", "__"))]
            for f in sorted(files):
                if os.path.splitext(f)[1].lower() in EXT:
                    paths.append(os.path.join(dirpath, f))
    return paths


def safe_name(name):
    return "".join(ch if ch.isalnum() or ch in "-_ ." else "_" for ch in name).strip() or "unnamed"


def unique_path(folder, filename, source):
    """Never overwrite: if the name is taken, put the source folder's name in front of it."""
    dest = os.path.join(folder, filename)
    if not os.path.exists(dest):
        return dest
    prefix = safe_name(os.path.basename(os.path.dirname(source)))
    dest = os.path.join(folder, f"{prefix}_{filename}")
    n = 2
    while os.path.exists(dest):
        dest = os.path.join(folder, f"{prefix}_{n}_{filename}")
        n += 1
    return dest


def main():
    ap = argparse.ArgumentParser(description="Sort photos into folders by object type with your trained model.")
    ap.add_argument("folders", nargs="+", help="folders (or photos) to sort")
    ap.add_argument("--out", required=True, help="where the sorted copies go")
    ap.add_argument("--min-confidence", type=float, default=0.85,
                    help="below this the photo goes to _unsure (default 0.85)")
    ap.add_argument("--dry-run", action="store_true", help="only show the counts; copy nothing")
    a = ap.parse_args()
    if not 0 <= a.min_confidence <= 1:
        raise SystemExit("--min-confidence must be between 0 and 1")

    out_abs = os.path.abspath(a.out)
    photos = [p for p in find_photos(a.folders) if not os.path.abspath(p).startswith(out_abs + os.sep)]
    if not photos:
        raise SystemExit("No photos found.")
    model = recognize.Model()
    print(f"Sorting {len(photos)} photos with a model that knows: {', '.join(model.labels)}")

    rows, counts = [], Counter()
    B = 16
    for i in range(0, len(photos), B):
        chunk, imgs = [], []
        for p in photos[i:i + B]:
            try:
                imgs.append(recognize.read_rgb(p)); chunk.append(p)
            except Exception:
                print("  skipped unreadable photo:", p)
        if not imgs:
            continue
        x = (model.backbone.features(imgs) - model.mean) / model.scale
        z = x @ model.coef.T + model.intercept
        z -= z.max(axis=1, keepdims=True)
        e = np.exp(z)
        probs = e / e.sum(axis=1, keepdims=True)
        for p, pr in zip(chunk, probs):
            j = int(pr.argmax())
            label, conf = model.labels[j], float(pr[j])
            folder = safe_name(label) if conf >= a.min_confidence else "_unsure"
            rows.append((p, label, conf, folder))
            counts[folder] += 1
        done = min(i + B, len(photos))
        if done % 160 < B or done == len(photos):
            print(f"  {done}/{len(photos)}", flush=True)

    print("\nResult:")
    for folder, n in sorted(counts.items(), key=lambda kv: (kv[0] == "_unsure", -kv[1])):
        print(f"  {folder:24s} {n:5d}")
    if a.dry_run:
        print("\nDry run: nothing was copied.")
        return

    os.makedirs(a.out, exist_ok=True)
    report = []
    for p, label, conf, folder in rows:
        os.makedirs(os.path.join(a.out, folder), exist_ok=True)
        dest = unique_path(os.path.join(a.out, folder), os.path.basename(p), p)
        shutil.copy2(p, dest)
        report.append([p, label, f"{conf:.3f}", os.path.relpath(dest, a.out)])
    with open(os.path.join(a.out, "report.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["original", "model_guess", "confidence", "copied_to"])
        w.writerows(report)
    print(f"\nCopied {len(report)} photos into {a.out}/  (your originals were not touched).")
    print("Look through each folder and move any photo that landed in the wrong one.")


if __name__ == "__main__":
    sys.exit(main())
