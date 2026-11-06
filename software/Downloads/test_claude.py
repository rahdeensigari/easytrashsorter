#!/usr/bin/env python3
"""Run sorter.py's real ask_claude() on test photos, with timing.

Usage: ANTHROPIC_API_KEY=... test_claude.py <scratchpad_dir>
The key is read from the environment only and never written anywhere.
"""
import importlib.util
import json
import os
import random
import statistics
import sys
import time
import types
from pathlib import Path

import numpy as np
import requests
from PIL import Image

sys.path.insert(0, '/home/claude')
import rulebook as rbk
RB = rbk.load('/home/claude/rulebooks/marietta-ga.json')

S = Path(sys.argv[1])
KEY = os.environ["ANTHROPIC_API_KEY"]

# import sorter.py without needing the Pi-only libraries
lri = types.ModuleType("ai_edge_litert.interpreter"); lri.Interpreter = object
sys.modules["ai_edge_litert"] = types.ModuleType("ai_edge_litert")
sys.modules["ai_edge_litert.interpreter"] = lri
spec = importlib.util.spec_from_file_location("sorter", "/home/claude/sorter.py")
sorter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sorter)


class Block:
    def __init__(self, d):
        self.type, self.text = d.get("type"), d.get("text", "")


class Client:
    """Minimal stand-in for anthropic.Anthropic().messages.create"""
    class messages:
        @staticmethod
        def create(model, max_tokens, messages, **extra):
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": model, "max_tokens": max_tokens, "messages": messages, **extra},
                timeout=sorter.CLAUDE_TIMEOUT,
            )
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
            return types.SimpleNamespace(content=[Block(b) for b in r.json()["content"]])


# ---- test set ----
random.seed(11)
tn = S / "trashnet_raw/dataset-resized"
items = []
for cls in ["cardboard", "glass", "metal", "paper", "plastic"]:
    items += [(f, "trash" if cls == "glass" else "recycling", f"tn_{cls}") for f in random.sample(sorted((tn / cls).glob("*.jpg")), 6)]
items += [(f, "trash", "tn_trash") for f in random.sample(sorted((tn / "trash").glob("*.jpg")), 14)]
cig = [p for p in sorted(Path("/home/claude/gh_TrashBox/TrashBox_train_dataset_subfolders/plastic/cigarette butt").glob("*"))
       if p.suffix.lower() in {".jpg", ".jpeg", ".png"}]
items += [(f, "trash", "cigarette_butt") for f in random.sample(cig, 6)]
random.shuffle(items)

if len(sys.argv) > 2:  # smoke test: just a few
    items = items[: int(sys.argv[2])]

rows = []
for i, (f, truth, src) in enumerate(items, 1):
    frame = np.asarray(Image.open(f).convert("RGB"))
    t0 = time.perf_counter()
    item, itype = sorter.ask_claude(Client, frame)
    bin_ = rbk.bin_for(RB, itype)[0] if itype and itype != 'empty' else None
    dt = time.perf_counter() - t0
    ok = bin_ == truth
    rows.append({"file": str(f), "src": src, "truth": truth, "claude_item": item, "claude_bin": bin_, "ok": ok, "sec": dt})
    print(f"{i:2d}/{len(items)} {src:15s} truth={truth:9s} claude={str(bin_):9s} {'OK ' if ok else 'BAD'} {dt:5.2f}s  {item}", flush=True)

json.dump(rows, open(S / "claude_test_results.json", "w"), indent=1)
secs = [r["sec"] for r in rows if r["claude_bin"]]
print(f"\nAccuracy: {sum(r['ok'] for r in rows)}/{len(rows)} = {np.mean([r['ok'] for r in rows]):.1%}")
if secs:
    print(f"Time per image: avg {statistics.mean(secs):.2f}s  median {statistics.median(secs):.2f}s  "
          f"min {min(secs):.2f}s  max {max(secs):.2f}s")
by = {}
for r in rows:
    by.setdefault(r["src"], []).append(r["ok"])
for k, v in sorted(by.items()):
    print(f"  {k:15s} {sum(v)}/{len(v)}")
