#!/usr/bin/env python3
"""Stand-in for Teachable Machine on the ITEM-TYPE set: pre-trained MobileNetV2 + a classifier trained on our images.

Usage: eval_items.py <mobilenetv2.onnx> <item_types_dir> <out_json> [rulebook.json]
20% of every class is held out. Prints accuracy per class and the most common mix-ups.
Note: held-out images come from the same photo collections as the training images, so real-world
accuracy on your platform will be lower. Measure that with sorter.py --test.
If a rulebook is given, also reports how often the item lands in the RIGHT BIN (what actually matters).
"""
import json
import random
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import onnxruntime as ort

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rulebook as rbk
from PIL import Image
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

model_path, data_dir, out_json = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
random.seed(0)
sess = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
inp = sess.get_inputs()[0].name
MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)


def load(path):
    im = Image.open(path).convert("RGB")
    w, h = im.size
    s = 256 / min(w, h)
    im = im.resize((max(224, round(w * s)), max(224, round(h * s))))
    w, h = im.size
    l, t = (w - 224) // 2, (h - 224) // 2
    im = im.crop((l, t, l + 224, t + 224))
    return ((np.asarray(im, np.float32) / 255.0 - MEAN) / STD).transpose(2, 0, 1)


def feats(paths, batch=32):
    out = []
    for i in range(0, len(paths), batch):
        out.append(sess.run(None, {inp: np.stack([load(p) for p in paths[i:i + batch]])})[0])
    return np.concatenate(out)


classes = sorted(d.name for d in data_dir.iterdir() if d.is_dir())
train, test = [], []
for c in classes:
    files = sorted((data_dir / c).glob("*.jpg"))
    random.shuffle(files)
    k = max(1, len(files) // 5)
    test += [(f, c) for f in files[:k]]
    train += [(f, c) for f in files[k:]]
print(f"{len(classes)} classes, train {len(train)}, held-out {len(test)}", flush=True)

Xtr = feats([str(f) for f, _ in train])
scaler = StandardScaler().fit(Xtr)
clf = LogisticRegression(max_iter=3000, C=0.5).fit(scaler.transform(Xtr), [c for _, c in train])
Xte = scaler.transform(feats([str(f) for f, _ in test]))
proba = clf.predict_proba(Xte)
pred = clf.classes_[proba.argmax(1)]
conf = proba.max(1)
truth = np.array([c for _, c in test])
ok = pred == truth
print(f"\nOverall: {ok.mean():.1%} ({ok.sum()}/{len(ok)})")
sure = conf >= 0.85
print(f"When confident (>=85%): {ok[sure].mean():.1%} correct on {sure.sum()}/{len(ok)} items; "
      f"the other {(~sure).sum()} would go to the Claude backup")
print("\nPer class:")
for c in classes:
    m = truth == c
    print(f"  {c:20s} {ok[m].mean():6.1%}  (n={m.sum()})")
if len(sys.argv) > 4:
    rb = rbk.load(sys.argv[4])
    tb = np.array([rbk.bin_for(rb, t)[0] for t in truth])
    pb = np.array([rbk.bin_for(rb, p)[0] for p in pred])
    print(f"\nRight BIN under {rb['city']}: {(tb == pb).mean():.1%}  "
          f"(item type can be wrong while the bin is still right, e.g. paper vs cardboard)")
    sure_bin = (tb == pb)[sure].mean()
    print(f"  right bin when the model is confident: {sure_bin:.1%} on {sure.sum()} items")
    bad_rec = ((pb == "recycling") & (tb != "recycling")).sum()
    haz_leak = ((tb == "special") & (pb != "special")).sum()
    print(f"  contamination (something not recyclable sent to recycling): {bad_rec} of {len(tb)}")
    print(f"  special items that missed the special bin: {haz_leak} of {(tb == 'special').sum()}")
pairs = Counter((t, p) for t, p, o in zip(truth, pred, ok) if not o)
print("\nMost common mix-ups (true -> predicted):")
for (t, p), n in pairs.most_common(10):
    print(f"  {t} -> {p}: {n}")
json.dump({"overall": float(ok.mean()), "per_class": {c: float(ok[truth == c].mean()) for c in classes},
           "confusions": [[t, p, n] for (t, p), n in pairs.most_common(20)]}, open(out_json, "w"), indent=1)
