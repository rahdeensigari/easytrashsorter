#!/usr/bin/env python3
"""
Train the can's image model on the Pi (or any computer), with no website and no TensorFlow.

    python3 train_local.py trashnet                       # folders of photos, one folder per item type
    python3 train_local.py trashnet my_photos             # several photo folders are combined
    python3 train_local.py trashnet --map trash=other_trash --map metal=aluminum_steel_can

It reads every photo with the MobileNetV2 image network, then trains a small classifier on the results,
and saves model_local.npz. sorter.py uses that file automatically. Adding photos and running this again
only re-reads the NEW photos, so retraining takes seconds.

Class names = folder names. They should be item types from rulebook.py (or "empty"). Use --map old=new
to rename a folder on the fly (TrashNet's "trash" folder is automatically treated as other_trash).
Needs: pip install onnxruntime scikit-learn pillow opencv-python numpy
"""
import argparse
import os
import random
import sys
import time
from collections import Counter, defaultdict

import numpy as np
from PIL import Image

import localmodel
import rulebook as rbk

EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
DEFAULT_MAP = {"trash": "other_trash"}
CACHE_FILE = os.path.join(localmodel.HERE, "features_cache.npz")


def find_photos(folders, mapping):
    """-> list of (path, class_name). Folder names are mapped to item types."""
    items = []
    for root in folders:
        if not os.path.isdir(root):
            raise SystemExit(f"Folder not found: {root}")
        for cls in sorted(os.listdir(root)):
            d = os.path.join(root, cls)
            if not os.path.isdir(d) or cls.startswith((".", "__")):
                continue
            name = mapping.get(cls.lower(), rbk.item_key(cls) or cls)
            for dirpath, _, files in os.walk(d):
                for f in sorted(files):
                    if os.path.splitext(f)[1].lower() in EXT:
                        items.append((os.path.join(dirpath, f), name))
    return items


def load_cache():
    try:
        z = np.load(CACHE_FILE, allow_pickle=False)
        return dict(zip(z["keys"].tolist(), z["feats"]))
    except (OSError, ValueError, KeyError):
        return {}


def save_cache(cache):
    keys = list(cache)
    np.savez(CACHE_FILE, keys=np.array(keys), feats=np.stack([cache[k] for k in keys]))


def read_rgb(path):
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folders", nargs="+", help="photo folders (each has one subfolder per item type)")
    ap.add_argument("--out", default=localmodel.MODEL_FILE)
    ap.add_argument("--map", action="append", default=[], metavar="OLD=NEW", help="rename a folder, e.g. trash=other_trash")
    ap.add_argument("--max-per-class", type=int, default=400, help="use at most this many photos per class")
    ap.add_argument("--holdout", type=float, default=0.2, help="share of photos kept aside to measure accuracy")
    a = ap.parse_args()

    mapping = dict(DEFAULT_MAP)
    for m in a.map:
        if "=" not in m:
            raise SystemExit(f"--map needs OLD=NEW, got '{m}'")
        old, new = m.split("=", 1)
        mapping[old.strip().lower()] = rbk.item_key(new) or new.strip()

    items = find_photos(a.folders, mapping)
    random.seed(0)
    by_class = defaultdict(list)
    for p, c in items:
        by_class[c].append(p)
    items = []
    for c, paths in by_class.items():
        random.shuffle(paths)
        items += [(p, c) for p in paths[:a.max_per_class]]
    counts = Counter(c for _, c in items)
    if len(counts) < 2:
        raise SystemExit("Need at least two classes (folders of photos).")
    print("Classes and photo counts:")
    for c, n in sorted(counts.items()):
        known = c in rbk.ITEM_TYPES or c == rbk.EMPTY
        print(f"  {c:22s} {n:5d}" + ("" if known else "   <- not an item type: the sorter will treat it as unknown"))
        if n < 20:
            print("     (few photos: add more for this class)")
    if rbk.EMPTY not in counts:
        print("Note: no 'empty' folder. Add photos of the empty platform (collect.py empty) so the sorter can tell "
              "when nothing is there.")

    backbone = localmodel.Backbone()
    cache = load_cache()
    keys = {p: f"{os.path.abspath(p)}|{os.path.getsize(p)}|{int(os.path.getmtime(p))}" for p, _ in items}
    todo = [p for p, _ in items if keys[p] not in cache]
    print(f"\nReading {len(todo)} new photos ({len(items) - len(todo)} already done)...")
    t0, B = time.time(), 16
    for i in range(0, len(todo), B):
        chunk = todo[i:i + B]
        imgs, ok = [], []
        for p in chunk:
            try:
                imgs.append(read_rgb(p)); ok.append(p)
            except Exception:
                print("  skipped unreadable photo:", p)
        if imgs:
            for p, f in zip(ok, backbone.features(imgs)):
                cache[keys[p]] = f
        done = min(i + B, len(todo))
        if done % 160 < B or done == len(todo):
            rate = (time.time() - t0) / max(1, done)
            print(f"  {done}/{len(todo)}  ({rate:.2f} s per photo, about {rate * (len(todo) - done) / 60:.1f} min left)",
                  flush=True)
    if todo:
        save_cache(cache)

    data = [(cache[keys[p]], c) for p, c in items if keys[p] in cache]
    X = np.stack([f for f, _ in data]).astype(np.float32)
    y = np.array([c for _, c in data])

    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    # 1) measure: train on most photos, test on the rest
    idx = list(range(len(y)))
    random.shuffle(idx)
    held = set()
    per_class = defaultdict(int)
    for i in idx:
        if per_class[y[i]] < max(1, int(counts[y[i]] * a.holdout)):
            held.add(i); per_class[y[i]] += 1
    tr = np.array([i for i in range(len(y)) if i not in held]); te = np.array(sorted(held))
    sc = StandardScaler().fit(X[tr])
    clf = LogisticRegression(max_iter=3000, C=0.5).fit(sc.transform(X[tr]), y[tr])
    pred = clf.predict(sc.transform(X[te]))
    ok = pred == y[te]
    print(f"\nAccuracy on {len(te)} photos kept aside: {ok.mean():.1%}")
    for c in sorted(counts):
        m = y[te] == c
        if m.any():
            print(f"  {c:22s} {ok[m].mean():6.1%}  (n={m.sum()})")
    print("These photos come from the same collections as the training photos, so accuracy on your real platform\n"
          "will be lower. Test it with sorter.py --test and add photos from collect.py where it gets things wrong.")

    # 2) save: retrain on ALL photos
    sc = StandardScaler().fit(X)
    clf = LogisticRegression(max_iter=3000, C=0.5).fit(sc.transform(X), y)
    np.savez(a.out, classes=np.array(clf.classes_), mean=sc.mean_.astype(np.float32),
             scale=sc.scale_.astype(np.float32), coef=clf.coef_.astype(np.float32),
             intercept=clf.intercept_.astype(np.float32), n_photos=len(y))
    print(f"\nSaved {a.out}  ({len(clf.classes_)} classes, {len(y)} photos). sorter.py will use it automatically.")


if __name__ == "__main__":
    sys.exit(main())
