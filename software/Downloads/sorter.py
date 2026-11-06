#!/usr/bin/env python3
"""
Self-sorting trash can: camera -> AI says WHAT the item is -> the active RULEBOOK says WHERE it goes
for this city -> servo sorts into recycling, trash or special.

The AI is the same everywhere. The rulebook (rulebook.json, made with app.py from a city's rules)
is what changes from city to city. Change it while the can is running and it picks up the new one.

Usage:
    python3 sorter.py                # trained model first, Claude as backup when unsure
    python3 sorter.py --picam        # Raspberry Pi Camera Module
    python3 sorter.py --test         # asks if each sort was right, for your accuracy table
    python3 sorter.py --no-cloud     # on-device model only (no internet needed)
    python3 sorter.py --claude-main  # Claude identifies every item; no trained model required
                                     # (start with the platform EMPTY so it can learn the background)
    python3 sorter.py --calibrate    # move the servo to each position so you can tune the angles

On-device model, either way (the folder names / class names must be item types from rulebook.py, like
aluminum_steel_can, glass, battery, plus one called "empty"; spaces or capitals are fine):
  - train it on the Pi:  python3 train_local.py <photo folders>   -> model_local.npz (used automatically)
  - or Teachable Machine: put model_unquant.tflite and labels.txt in this folder.
Needs rulebook.py and localmodel.py in the same folder. For Claude: pip install anthropic, and run setup_pi.sh once.
If there is no key or no internet, uncertain items go to trash (safer than contaminating the recycling).
"""
import argparse
import base64
import csv
import datetime
import json
import os
import re
import time

import cv2
import numpy as np

import rulebook as rbk

try:
    from ai_edge_litert.interpreter import Interpreter
except ImportError:
    try:
        from tflite_runtime.interpreter import Interpreter
    except ImportError:
        Interpreter = None  # fine when using model_local.npz (made by train_local.py)

import localmodel

# ---------- settings you may want to tweak ----------
SERVO_PIN = 18          # GPIO18 = physical pin 12

# Servo positions. Tune these with:  python3 sorter.py --calibrate
# With one 180-degree servo, the rest position and all bins must fit between -90 and +90.
REST_ANGLE = 0          # where the platform waits (under the opening / camera)
RECYCLING_ANGLE = -70   # swings toward the recycling bin
TRASH_ANGLE = 70        # swings toward the trash bin
SPECIAL_ANGLE = 90      # swings toward the special bin (only used when THIRD_BIN is True)

# True  = there is a physical third bin and the platform sorts into it.
# False = no third bin yet: special items stay on the level platform, the screen tells the
#         person to take them off by hand, and the program waits until they are removed.
THIRD_BIN = True
SPECIAL_WAIT = 5        # seconds to wait for hand removal when the camera can't check (on-device mode)

CONFIDENCE_MIN = 0.85   # on-device model must be at least this sure
FRAMES_IN_A_ROW = 3     # same confident answer this many frames before acting
UNSURE_FRAMES = 8       # item present but model unsure this many frames -> ask Claude
EMPTY_MAX = 0.50        # if "Empty" scores below this, assume an item is on the platform
DUMP_SECONDS = 1.5      # how long the platform stays tilted
COOLDOWN_SECONDS = 2.0  # pause after each sort
LOG_FILE = "sort_log.csv"
LOG_HEADER = ["time", "method", "bin", "reason", "item_type", "rulebook", "local_label", "local_confidence",
              "claude_item", "correct"]

CLAUDE_MODEL = "claude-haiku-5-5"   # fast, low-cost model with vision
CLAUDE_TIMEOUT = 10                 # seconds before giving up and using the fallback
FALLBACK_BIN = "trash"              # used when Claude can't be reached

# --claude-main item detection (compares the camera to a photo of the empty platform)
CHANGE_PIXELS = 0.03    # fraction of the image that must change to count as "item present"
STILL_FRAMES = 3        # item must sit still this many frames before the photo is sent

# On-screen tips. Phone numbers come from the active rulebook (only if the city's document had them).
def tip_for(reason, rb):
    if reason == "dropoff":
        extra = rb["contacts"]["recycling"]
        return "Tip: this can be recycled at a drop-off site, not at the curb." + (f" Questions: {extra}" if extra else "")
    if reason == "hazardous":
        extra = rb["contacts"]["hazardous"]
        return "This should not go in the trash." + (f" Hazardous waste: {extra}" if extra else "")
    return ""


# -----------------------------------------------------


def load_labels(path="labels.txt"):
    labels = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(" ", 1)  # Teachable Machine format: "0 Recycling"
            labels.append(parts[1] if len(parts) == 2 and parts[0].isdigit() else line)
    return labels


def make_camera(use_picam):
    if use_picam:
        from picamera2 import Picamera2
        cam = Picamera2()
        cam.configure(cam.create_preview_configuration(main={"size": (640, 480), "format": "RGB888"}))
        cam.start()
        time.sleep(1)
        return lambda: cam.capture_array()
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        raise SystemExit("Could not open the camera. Check the USB connection.")

    def grab():
        ok, frame = cap.read()
        if not ok:
            raise SystemExit("Camera read failed.")
        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    return grab


def load_local_model():
    """(model, labels): the model trained on the Pi (model_local.npz), or else a Teachable Machine
    model_unquant.tflite + labels.txt. (None, None) if neither is in the folder."""
    if os.path.exists(localmodel.MODEL_FILE):
        model = localmodel.LocalModel()
        print(f"On-device model: model_local.npz ({len(model.labels)} classes)")
        return model, model.labels
    if os.path.exists("model_unquant.tflite") and os.path.exists("labels.txt"):
        if Interpreter is None:
            raise SystemExit("model_unquant.tflite needs the ai-edge-litert package (pip install ai-edge-litert).")
        interp = Interpreter(model_path="model_unquant.tflite")
        interp.allocate_tensors()
        print("On-device model: Teachable Machine model_unquant.tflite")
        return interp, load_labels()
    return None, None


def classify(interpreter, frame_rgb):
    if isinstance(interpreter, localmodel.LocalModel):
        return interpreter.scores(frame_rgb)
    inp = interpreter.get_input_details()[0]
    out = interpreter.get_output_details()[0]
    h, w = inp["shape"][1], inp["shape"][2]
    img = cv2.resize(frame_rgb, (w, h))
    if inp["dtype"] == np.float32:
        img = (img.astype(np.float32) / 127.5) - 1.0
    else:
        img = img.astype(np.uint8)
    interpreter.set_tensor(inp["index"], np.expand_dims(img, 0))
    interpreter.invoke()
    scores = interpreter.get_tensor(out["index"])[0].astype(np.float32)
    if out["dtype"] != np.float32:
        scale, zero = out["quantization"]
        scores = (scores - zero) * scale
    return scores


def label_to_item(label):
    """Model label -> item type key, 'empty', or None if the label isn't one we know."""
    return rbk.item_key(label)


def decide(rb, item_type):
    """(bin, reason) for an item type under this rulebook."""
    return rbk.bin_for(rb, item_type)


class Rules:
    """Holds the active rulebook and reloads it whenever the file changes."""

    def __init__(self):
        self.mtime, self.rb = None, rbk.default_rulebook()
        self.refresh(first=True)

    def refresh(self, first=False):
        try:
            m = os.stat(rbk.ACTIVE_FILE).st_mtime
        except OSError:
            m = None
        if m != self.mtime or first:
            self.mtime = m
            self.rb = rbk.load_active()
            if m is None:
                print("No rulebook found: using the safe default (items to trash, hazardous items to special).")
                print("Run app.py to add your city's rules.")
            else:
                print(f"Rulebook: {self.rb['city']}")
        return self.rb


# ---------- Claude ----------

KEY_FILE = os.path.expanduser("~/.sorter_api_key")  # created by setup_pi.sh, readable only by you


def load_api_key():
    """Key comes from the ANTHROPIC_API_KEY environment variable, or from ~/.sorter_api_key."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    try:
        with open(KEY_FILE) as f:
            key = f.read().strip()
        if key:
            os.environ["ANTHROPIC_API_KEY"] = key
    except OSError:
        pass


def make_claude_client():
    load_api_key()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("No API key found (run setup_pi.sh): Claude is off, unsure items go to", FALLBACK_BIN)
        return None
    try:
        import anthropic
    except ImportError:
        print("anthropic package not installed (pip install anthropic): Claude is off")
        return None
    return anthropic.Anthropic(timeout=CLAUDE_TIMEOUT, max_retries=1)


def frame_to_jpeg_b64(frame_rgb, max_side=512):
    h, w = frame_rgb.shape[:2]
    scale = max_side / max(h, w)
    if scale < 1:
        frame_rgb = cv2.resize(frame_rgb, (int(w * scale), int(h * scale)))
    ok, buf = cv2.imencode(".jpg", cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])
    return base64.standard_b64encode(buf.tobytes()).decode("ascii")


def parse_reply(text):
    """Pull {"item", "type"} out of Claude's reply. Returns (item, item_type) or (None, None).
    item_type is one of rbk.ITEM_TYPES or 'empty'. Anything unrecognised becomes other_trash."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None, None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None, None
    if not isinstance(data, dict) or "type" not in data:
        return None, None
    key = rbk.item_key(data.get("type", ""))
    if key is None:
        key = "other_trash"
    return str(data.get("item", "unknown")), key


def ask_claude(client, frame_rgb):
    """Returns (item, item_type). item_type is an item type key, 'empty', or None on failure.
    Claude only says WHAT the item is; the rulebook decides where it goes."""
    types = "\n".join(f"{k}: {v[0]}" for k, v in rbk.ITEM_TYPES.items())
    prompt = (
        "You are the vision system in a smart trash can. The photo shows the sorting platform "
        "from above. Identify the single object on it and say which item type it is.\n\n"
        f"Item types:\n{types}\nempty: nothing is on the platform\n\n"
        "Pick the closest type. If nothing fits, use other_trash. Reply with only JSON, like "
        '{"item": "aluminum soda can", "type": "aluminum_steel_can"}.'
    )
    try:
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=300,
            thinking={"type": "disabled"},  # no hidden reasoning: faster, and the answer can't get cut off
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                 "data": frame_to_jpeg_b64(frame_rgb)}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        text = "".join(block.text for block in msg.content if block.type == "text")
        return parse_reply(text)
    except Exception as e:  # no internet, bad key, timeout, etc.
        print("Claude request failed:", type(e).__name__, e)
        return None, None


# ---------- item detection for --claude-main ----------

def gray(frame_rgb):
    small = cv2.resize(frame_rgb, (160, 120))
    return cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_RGB2GRAY), (7, 7), 0)


def changed_fraction(a, b):
    return float((cv2.absdiff(a, b) > 25).mean())


# ---------- servo, bins and log ----------

class Rig:
    """The servo, the three places an item can go, and the log file."""

    def __init__(self, servo_class, test_mode):
        self.test_mode = test_mode
        self.servo = servo_class(SERVO_PIN, min_angle=-90, max_angle=90)
        self.servo.angle = REST_ANGLE
        self.angles = {"recycling": RECYCLING_ANGLE, "trash": TRASH_ANGLE}
        if THIRD_BIN:
            self.angles["special"] = SPECIAL_ANGLE
        self._open_log()

    def _open_log(self):
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, newline="") as f:
                first = next(csv.reader(f), [])
            if first != LOG_HEADER:  # an older log with different columns: keep it, start a fresh one
                stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                os.rename(LOG_FILE, f"sort_log_old_{stamp}.csv")
        new_log = not os.path.exists(LOG_FILE)
        self.log = open(LOG_FILE, "a", newline="")
        self.writer = csv.writer(self.log)
        if new_log:
            self.writer.writerow(LOG_HEADER)

    def place(self, bin_, reason, method, rb, item_type="", local_label="", conf=0.0, item="", wait_clear=None):
        """Send the item to its bin (or, for special items with no third bin, ask for hand removal)."""
        what = item or (f"{local_label} {conf:.0%}" if local_label else "unknown")
        kind = f", {item_type}" if item_type else ""
        print(f"[{method}] -> {bin_.upper()}  ({what}{kind})")
        tip = tip_for(reason, rb)
        if bin_ in self.angles:
            self.servo.angle = self.angles[bin_]
            time.sleep(DUMP_SECONDS)
            self.servo.angle = REST_ANGLE
            if tip:
                print("  " + tip)
        else:  # special item and no third bin: hand removal
            print("=" * 60)
            print(f"SPECIAL ITEM: {item or item_type or 'unknown'}")
            print("This does not go in the recycling OR the trash.")
            print("Please take it off the platform and dispose of it separately.")
            if tip:
                print(tip)
            print("=" * 60)
        correct = ""
        if self.test_mode:
            correct = "y" if input("Was that correct? (y/n): ").strip().lower().startswith("y") else "n"
        self.writer.writerow([datetime.datetime.now().isoformat(timespec="seconds"), method, bin_, reason,
                              item_type, rb["city"], local_label, f"{conf:.3f}", item, correct])
        self.log.flush()
        if bin_ not in self.angles:
            if wait_clear:
                wait_clear()
            else:
                time.sleep(SPECIAL_WAIT)
            time.sleep(1)
        time.sleep(COOLDOWN_SECONDS)

    def close(self):
        self.servo.angle = REST_ANGLE
        time.sleep(0.5)
        self.servo.detach()
        self.log.close()
        print("Stopped. Results saved to", LOG_FILE)


def calibrate(servo_class):
    """Move the servo to each position so the angles can be adjusted by eye."""
    servo = servo_class(SERVO_PIN, min_angle=-90, max_angle=90)
    spots = {"rest": REST_ANGLE, "recycling": RECYCLING_ANGLE, "trash": TRASH_ANGLE}
    if THIRD_BIN:
        spots["special"] = SPECIAL_ANGLE
    print("Calibration. Type a position name to move there, a number from -90 to 90 to try that angle,")
    print("or q to quit. Positions:", ", ".join(f"{k}={v}" for k, v in spots.items()))
    try:
        while True:
            cmd = input("> ").strip().lower()
            if cmd in ("q", "quit", ""):
                break
            if cmd in spots:
                servo.angle = spots[cmd]
                continue
            try:
                angle = float(cmd)
            except ValueError:
                print("Not a position name or number.")
                continue
            if -90 <= angle <= 90:
                servo.angle = angle
            else:
                print("Angle must be between -90 and 90.")
    finally:
        servo.angle = REST_ANGLE
        time.sleep(0.5)
        servo.detach()
        print("Edit the *_ANGLE lines at the top of sorter.py with the numbers that worked.")


# ---------- main loop ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--picam", action="store_true", help="use Pi Camera Module")
    ap.add_argument("--test", action="store_true", help="ask for ground truth after each sort")
    ap.add_argument("--no-cloud", action="store_true", help="never call Claude")
    ap.add_argument("--claude-main", action="store_true", help="Claude classifies every item")
    ap.add_argument("--calibrate", action="store_true", help="move the servo to tune the angles")
    args = ap.parse_args()
    if args.claude_main and args.no_cloud:
        raise SystemExit("--claude-main needs the cloud; drop --no-cloud.")

    from gpiozero import AngularServo

    if args.calibrate:
        return calibrate(AngularServo)

    get_frame = make_camera(args.picam)
    claude = None if args.no_cloud else make_claude_client()
    if args.claude_main:
        if claude is None:
            raise SystemExit("--claude-main needs an API key (run setup_pi.sh) and the anthropic package.")
        return claude_main_loop(args, get_frame, claude, AngularServo)

    interpreter, labels = load_local_model()
    if interpreter is None:
        raise SystemExit("No trained model found. Train one with train_local.py, or put Teachable Machine's "
                         "model_unquant.tflite and labels.txt in this folder, or run with --claude-main.")
    empty_idx = next((i for i, l in enumerate(labels) if "empty" in l.lower()), None)
    rig = Rig(AngularServo, args.test)
    rules = Rules()

    def wait_until_empty():
        if empty_idx is None:
            time.sleep(SPECIAL_WAIT)
            return
        while classify(interpreter, get_frame())[empty_idx] < EMPTY_MAX:
            time.sleep(0.5)

    print("Running. Put an item on the platform. Ctrl+C to quit.")
    streak_label, streak, unsure = None, 0, 0
    try:
        while True:
            frame = get_frame()
            scores = classify(interpreter, frame)
            idx = int(np.argmax(scores))
            label, conf = labels[idx], float(scores[idx])
            item_present = empty_idx is None or scores[empty_idx] < EMPTY_MAX
            rb = rules.refresh()  # picks up a new rulebook if one was activated in the app
            key = label_to_item(label)

            # 1) On-device model is confident about an item type: look up where it goes in this city.
            if conf >= CONFIDENCE_MIN and key not in (None, rbk.EMPTY):
                streak = streak + 1 if label == streak_label else 1
                streak_label, unsure = label, 0
                if streak >= FRAMES_IN_A_ROW:
                    bin_, reason = decide(rb, key)
                    rig.place(bin_, reason, "local", rb, key, label, conf, wait_clear=wait_until_empty)
                    streak_label, streak = None, 0
                continue

            streak_label, streak = None, 0

            # 2) Something is there but the model is unsure: count frames, then escalate.
            if item_present:
                unsure += 1
                if unsure >= UNSURE_FRAMES:
                    unsure = 0
                    if claude:
                        print("Not sure, asking Claude...")
                        item, ckey = ask_claude(claude, frame)
                        if ckey == rbk.EMPTY:
                            continue  # Claude sees nothing on the platform
                        if ckey:
                            bin_, reason = decide(rb, ckey)
                            rig.place(bin_, reason, "claude", rb, ckey, label, conf, item, wait_clear=wait_until_empty)
                            continue
                    rig.place(FALLBACK_BIN, "", "fallback", rb, "", label, conf)
            else:
                unsure = 0
    except KeyboardInterrupt:
        pass
    finally:
        rig.close()


def claude_main_loop(args, get_frame, claude, AngularServo):
    """Claude decides every item. The Pi only detects that something new is on the platform.
    If a trained model is in the folder, it is used as the offline backup."""
    model, labels = load_local_model()
    local = (model, labels) if model is not None else None
    if local is None:
        print("Offline backup: none (no trained model), uncertain items go to", FALLBACK_BIN)

    rig = Rig(AngularServo, args.test)
    rules = Rules()

    def wait_until_removed():
        while changed_fraction(gray(get_frame()), background) > CHANGE_PIXELS:
            time.sleep(0.5)  # still there

    print("Learning the empty platform, keep it clear...")
    time.sleep(1)
    background = gray(get_frame())
    print("Ready. Put an item on the platform. Ctrl+C to quit.")

    prev, still = None, 0
    try:
        while True:
            frame = get_frame()
            g = gray(frame)
            present = changed_fraction(g, background) > CHANGE_PIXELS
            if not present:
                prev, still = None, 0
                background = cv2.addWeighted(background, 0.95, g, 0.05, 0)  # follow slow light changes
                continue
            still = still + 1 if prev is not None and changed_fraction(g, prev) < 0.01 else 0
            prev = g
            if still < STILL_FRAMES:
                continue  # wait until the item stops moving

            print("Item detected, asking Claude...")
            item, key = ask_claude(claude, frame)
            if key == rbk.EMPTY:
                print("Claude sees nothing there, re-learning the background.")
                background, prev, still = g, None, 0
                continue

            rb = rules.refresh()
            method, local_label, conf = "claude", "", 0.0
            if key is None:  # Claude unreachable: use the on-device model, then the fallback
                method = "fallback"
                if local:
                    scores = classify(local[0], frame)
                    i = int(np.argmax(scores))
                    local_label, conf = local[1][i], float(scores[i])
                    if label_to_item(local_label) not in (None, rbk.EMPTY):
                        method, key = "local", label_to_item(local_label)
            if key:
                bin_, reason = decide(rb, key)
            else:
                bin_, reason, key = FALLBACK_BIN, "", ""

            rig.place(bin_, reason, method, rb, key, local_label, conf, item or "", wait_clear=wait_until_removed)
            prev, still = None, 0
    except KeyboardInterrupt:
        pass
    finally:
        rig.close()


if __name__ == "__main__":
    main()
