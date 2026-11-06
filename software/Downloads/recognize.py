#!/usr/bin/env python3
"""
recognize.py: one file that trains a model to recognize objects and then shows what it sees.
No API key, no internet (after the first run), no servo, no rulebook.

    python3 recognize.py train trashnet                 # photos in folders, one folder per object type
    python3 recognize.py train trashnet my_photos       # several photo folders are combined
    python3 recognize.py photo cup.jpg can.jpg          # what is in these pictures?
    python3 recognize.py live --picam                   # what does the camera see right now? (Ctrl+C to stop)
    python3 recognize.py live                           # same, with a USB webcam

The folder names are the names it learns, whatever they are ("glass", "battery", "banana"...).
Training saves model_local.npz next to this file; the other commands load it.

Needs:  pip install onnxruntime scikit-learn pillow numpy opencv-python
        and mobilenetv2-7.onnx in the same folder (it is downloaded once if missing).
"""
import argparse
import hashlib
import os
import random
import sys
import time
import urllib.request
from collections import Counter, defaultdict

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
BACKBONE_FILE = os.path.join(HERE, "mobilenetv2-7.onnx")
BACKBONE_URL = ("https://github.com/microsoft/onnxruntime-inference-examples/raw/main/"
                "quantization/image_classification/cpu/mobilenetv2-7.onnx")
BACKBONE_SHA256 = "0e7c0aa4bc74650386fa1d2c84705753de7c2bdb21909ada5c59154bb429e092"
MODEL_FILE = os.path.join(HERE, "model_local.npz")
CACHE_FILE = os.path.join(HERE, "features_cache.npz")
EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)


# ---------- the image network (MobileNetV2: already knows how to "see", never changed) ----------

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_backbone():
    if os.path.exists(BACKBONE_FILE) and sha256(BACKBONE_FILE) == BACKBONE_SHA256:
        return BACKBONE_FILE
    print("Downloading the MobileNetV2 image network (14 MB, one time)...")
    tmp = BACKBONE_FILE + ".part"
    try:
        urllib.request.urlretrieve(BACKBONE_URL, tmp)
        if sha256(tmp) != BACKBONE_SHA256:
            raise RuntimeError("the downloaded file did not match the expected hash")
        os.replace(tmp, BACKBONE_FILE)
    except Exception as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise SystemExit(f"Could not get mobilenetv2-7.onnx ({e}). Put the file in {HERE} and try again.")
    return BACKBONE_FILE


def preprocess(rgb):
    h, w = rgb.shape[:2]
    s = 256.0 / min(h, w)
    nh, nw = max(224, round(h * s)), max(224, round(w * s))
    img = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_AREA)
    top, left = (nh - 224) // 2, (nw - 224) // 2
    img = img[top:top + 224, left:left + 224]
    return ((img.astype(np.float32) / 255.0 - MEAN) / STD).transpose(2, 0, 1)


class Backbone:
    def __init__(self):
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, os.cpu_count() or 4)
        self.sess = ort.InferenceSession(ensure_backbone(), opts, providers=["CPUExecutionProvider"])
        self.input = self.sess.get_inputs()[0].name

    def features(self, rgb_images):
        return self.sess.run(None, {self.input: np.stack([preprocess(im) for im in rgb_images])})[0]


class Model:
    """Loads model_local.npz. predict(rgb) -> list of (name, probability), best first."""

    def __init__(self):
        if not os.path.exists(MODEL_FILE):
            raise SystemExit("No model yet. Train one first:  python3 recognize.py train <photo folders>")
        d = np.load(MODEL_FILE, allow_pickle=False)
        self.labels = [str(c) for c in d["classes"]]
        self.mean, self.scale, self.coef, self.intercept = d["mean"], d["scale"], d["coef"], d["intercept"]
        self.backbone = Backbone()

    def predict(self, rgb):
        x = (self.backbone.features([rgb]) - self.mean) / self.scale
        z = (x @ self.coef.T + self.intercept)[0]
        e = np.exp(z - z.max())
        p = e / e.sum()
        order = np.argsort(-p)
        return [(self.labels[i], float(p[i])) for i in order]


# ---------- train ----------

def read_rgb(path):
    from PIL import Image
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"))


def cmd_train(a):
    mapping = {}
    for m in a.map:
        if "=" not in m:
            raise SystemExit(f"--map needs OLD=NEW, got '{m}'")
        old, new = m.split("=", 1)
        mapping[old.strip().lower()] = new.strip()

    found = defaultdict(list)
    for root in a.folders:
        if not os.path.isdir(root):
            raise SystemExit(f"Folder not found: {root}")
        for cls in sorted(os.listdir(root)):
            d = os.path.join(root, cls)
            if not os.path.isdir(d) or cls.startswith((".", "__")):
                continue
            name = mapping.get(cls.lower(), cls)
            for dirpath, _, files in os.walk(d):
                for f in sorted(files):
                    if os.path.splitext(f)[1].lower() in EXT:
                        found[name].append(os.path.join(dirpath, f))
    random.seed(0)
    items = []
    for c, paths in found.items():
        random.shuffle(paths)
        items += [(p, c) for p in paths[:a.max_per_class]]
    counts = Counter(c for _, c in items)
    if len(counts) < 2:
        raise SystemExit("Need at least two folders of photos (one folder per object type).")
    print("What it will learn:")
    for c, n in sorted(counts.items()):
        print(f"  {c:24s} {n:5d} photos" + ("   (few: add more)" if n < 20 else ""))

    backbone = Backbone()
    try:
        z = np.load(CACHE_FILE, allow_pickle=False)
        cache = dict(zip(z["keys"].tolist(), z["feats"]))
    except (OSError, ValueError, KeyError):
        cache = {}
    keys = {p: f"{os.path.abspath(p)}|{os.path.getsize(p)}|{int(os.path.getmtime(p))}" for p, _ in items}
    todo = [p for p, _ in items if keys[p] not in cache]
    print(f"\nReading {len(todo)} new photos ({len(items) - len(todo)} already done)...")
    t0, B = time.time(), 16
    for i in range(0, len(todo), B):
        imgs, ok = [], []
        for p in todo[i:i + B]:
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
            print(f"  {done}/{len(todo)}  (about {rate * (len(todo) - done) / 60:.1f} min left)", flush=True)
    if todo:
        ks = list(cache)
        np.savez(CACHE_FILE, keys=np.array(ks), feats=np.stack([cache[k] for k in ks]))

    data = [(cache[keys[p]], c) for p, c in items if keys[p] in cache]
    X = np.stack([f for f, _ in data]).astype(np.float32)
    y = np.array([c for _, c in data])

    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    idx = list(range(len(y)))
    random.shuffle(idx)
    held, per_class = set(), defaultdict(int)
    for i in idx:
        if per_class[y[i]] < max(1, int(counts[y[i]] * 0.2)):
            held.add(i); per_class[y[i]] += 1
    tr = np.array([i for i in range(len(y)) if i not in held]); te = np.array(sorted(held))
    sc = StandardScaler().fit(X[tr])
    clf = LogisticRegression(max_iter=3000, C=0.5).fit(sc.transform(X[tr]), y[tr])
    ok = clf.predict(sc.transform(X[te])) == y[te]
    print(f"\nTested on {len(te)} photos it never trained on: {ok.mean():.1%} right")
    for c in sorted(counts):
        m = y[te] == c
        if m.any():
            print(f"  {c:24s} {ok[m].mean():6.1%}")
    print("(Those photos come from the same collections as the training photos. Real accuracy on your own\n"
          " camera will be lower: try it with 'live' and add photos where it is wrong.)")

    sc = StandardScaler().fit(X)
    clf = LogisticRegression(max_iter=3000, C=0.5).fit(sc.transform(X), y)
    np.savez(MODEL_FILE, classes=np.array(clf.classes_), mean=sc.mean_.astype(np.float32),
             scale=sc.scale_.astype(np.float32), coef=clf.coef_.astype(np.float32),
             intercept=clf.intercept_.astype(np.float32), n_photos=len(y))
    print(f"\nSaved {MODEL_FILE}. Try it:  python3 recognize.py live --picam")


# ---------- photo / live ----------

def show(preds, top=3):
    return "   ".join(f"{n} {p:.0%}" for n, p in preds[:top])


def cmd_photo(a):
    model = Model()
    for path in a.files:
        try:
            print(f"{path}:  {show(model.predict(read_rgb(path)))}")
        except Exception as e:
            print(f"{path}:  could not read ({e})")


def open_camera(use_picam):
    if use_picam:
        from picamera2 import Picamera2
        cam = Picamera2()
        cam.configure(cam.create_preview_configuration(main={"size": (640, 480), "format": "RGB888"}))
        cam.start()
        time.sleep(1)
        return (lambda: cam.capture_array()), cam.close
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        raise SystemExit("Could not open the camera. Check the USB connection.")

    def grab():
        ok, frame = cap.read()
        if not ok:
            raise SystemExit("Camera read failed.")
        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    return grab, cap.release


def cmd_live(a):
    model = Model()
    grab, close = open_camera(a.picam)
    print("Hold an object in front of the camera. Ctrl+C to stop.\n")
    last = ""
    try:
        while True:
            line = show(model.predict(grab()))
            if line != last:
                print(line)
                last = line
            time.sleep(a.every)
    except KeyboardInterrupt:
        pass
    finally:
        close()


def main():
    ap = argparse.ArgumentParser(description="Train a model to recognize objects, then see what the camera sees.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train", help="train on folders of photos")
    t.add_argument("folders", nargs="+")
    t.add_argument("--map", action="append", default=[], metavar="OLD=NEW", help="rename a folder, e.g. trash=other_trash")
    t.add_argument("--max-per-class", type=int, default=400)
    p = sub.add_parser("photo", help="what is in these pictures?")
    p.add_argument("files", nargs="+")
    lv = sub.add_parser("live", help="what does the camera see?")
    lv.add_argument("--picam", action="store_true", help="use the Pi Camera Module")
    lv.add_argument("--every", type=float, default=0.5, help="seconds between looks")
    a = ap.parse_args()
    {"train": cmd_train, "photo": cmd_photo, "live": cmd_live}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
