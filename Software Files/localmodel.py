#!/usr/bin/env python3
"""
The on-device model, with no TensorFlow and no website:

  photo -> MobileNetV2 (a ready-made image network, never changed) -> 1000 numbers describing the photo
        -> a small classifier trained on YOUR photos (saved in model_local.npz) -> item type + confidence

train_local.py makes model_local.npz; sorter.py loads it. Both use the code in this file, so a photo is
prepared exactly the same way when training and when sorting.

Needs: pip install onnxruntime numpy opencv-python (the Pi already has opencv via apt).
"""
import hashlib
import os
import urllib.request

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
BACKBONE_FILE = os.path.join(HERE, "mobilenetv2-7.onnx")
BACKBONE_URL = ("https://github.com/microsoft/onnxruntime-inference-examples/raw/main/"
                "quantization/image_classification/cpu/mobilenetv2-7.onnx")
BACKBONE_SHA256 = "0e7c0aa4bc74650386fa1d2c84705753de7c2bdb21909ada5c59154bb429e092"
MODEL_FILE = os.path.join(HERE, "model_local.npz")

_MEAN = np.array([0.485, 0.456, 0.406], np.float32)
_STD = np.array([0.229, 0.224, 0.225], np.float32)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_backbone(path=BACKBONE_FILE):
    """Make sure mobilenetv2-7.onnx is next to the scripts (download it once if not). Checked by hash."""
    if os.path.exists(path) and _sha256(path) == BACKBONE_SHA256:
        return path
    print("Downloading the MobileNetV2 image network (14 MB, one time)...")
    tmp = path + ".part"
    try:
        urllib.request.urlretrieve(BACKBONE_URL, tmp)
        if _sha256(tmp) != BACKBONE_SHA256:
            raise RuntimeError("the downloaded file did not match the expected hash")
        os.replace(tmp, path)
    except Exception as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise SystemExit(f"Could not get mobilenetv2-7.onnx ({e}). Put the file in {HERE} and try again.")
    return path


def preprocess(rgb):
    """RGB image (H x W x 3, uint8) -> 3 x 224 x 224 float array. Same steps for training and sorting."""
    h, w = rgb.shape[:2]
    s = 256.0 / min(h, w)
    nh, nw = max(224, round(h * s)), max(224, round(w * s))
    img = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_AREA)
    top, left = (nh - 224) // 2, (nw - 224) // 2
    img = img[top:top + 224, left:left + 224]
    return ((img.astype(np.float32) / 255.0 - _MEAN) / _STD).transpose(2, 0, 1)


class Backbone:
    def __init__(self, path=None):
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, (os.cpu_count() or 4))
        self.sess = ort.InferenceSession(ensure_backbone(path or BACKBONE_FILE), opts,
                                         providers=["CPUExecutionProvider"])
        self.input = self.sess.get_inputs()[0].name

    def features(self, rgb_images):
        """List of RGB images -> array (N x 1000)."""
        batch = np.stack([preprocess(im) for im in rgb_images])
        return self.sess.run(None, {self.input: batch})[0]


class LocalModel:
    """The trained classifier. scores(frame) returns one probability per class, in self.labels order."""

    def __init__(self, path=MODEL_FILE, backbone=None):
        data = np.load(path, allow_pickle=False)
        self.labels = [str(c) for c in data["classes"]]
        self.mean, self.scale = data["mean"], data["scale"]
        self.coef, self.intercept = data["coef"], data["intercept"]
        self.backbone = backbone or Backbone()

    def probabilities(self, feats):
        z = ((feats - self.mean) / self.scale) @ self.coef.T + self.intercept
        z -= z.max(axis=1, keepdims=True)
        e = np.exp(z)
        return e / e.sum(axis=1, keepdims=True)

    def scores(self, frame_rgb):
        return self.probabilities(self.backbone.features([frame_rgb]))[0].astype(np.float32)
