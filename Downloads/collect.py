#!/usr/bin/env python3
"""
Take training photos with the can's own camera, sorted into folders by item type.

    python3 collect.py battery --picam          # then press Enter to take each photo
    python3 collect.py light_bulb --picam --burst 10   # Enter takes 10 photos, 0.4 s apart: turn the item between them
    python3 collect.py empty --picam            # photos of the empty platform (a class the model needs)

Photos go to  my_photos/<item_type>/ . Upload those folders to Teachable Machine next to the public set.
Aim for 40-60 photos per type, with different items, angles and positions on the platform, in the same
light the can will use. This matters most for battery and light_bulb, which the public sets don't cover.
"""
import argparse
import os
import sys
import time

import cv2

import rulebook as rbk


def open_camera(use_picam):
    if use_picam:
        from picamera2 import Picamera2
        cam = Picamera2()
        cam.configure(cam.create_preview_configuration(main={"size": (640, 480), "format": "RGB888"}))
        cam.start()
        time.sleep(1)
        return lambda: cam.capture_array(), cam.close
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        raise SystemExit("Could not open the camera. Check the USB connection.")

    def grab():
        for _ in range(3):  # drop stale buffered frames
            cap.grab()
        ok, frame = cap.read()
        if not ok:
            raise SystemExit("Camera read failed.")
        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    return grab, cap.release


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("label", help="item type, e.g. battery (or 'empty')")
    ap.add_argument("--picam", action="store_true", help="use the Pi Camera Module")
    ap.add_argument("--burst", type=int, default=1, help="photos per Enter press")
    ap.add_argument("--out", default="my_photos")
    args = ap.parse_args()

    key = rbk.item_key(args.label)
    if key is None:
        raise SystemExit("Unknown item type '%s'. Choose one of: %s, empty" % (args.label, ", ".join(rbk.ITEM_TYPES)))
    if not 1 <= args.burst <= 30:
        raise SystemExit("--burst must be between 1 and 30")
    folder = os.path.join(args.out, key)
    os.makedirs(folder, exist_ok=True)
    n = len([f for f in os.listdir(folder) if f.endswith(".jpg")])

    grab, close = open_camera(args.picam)
    print(f"Saving to {folder}/  ({n} photos already there). Press Enter to take photo(s), q then Enter to quit.")
    try:
        while True:
            if input("> ").strip().lower().startswith("q"):
                break
            for i in range(args.burst):
                frame = grab()
                n += 1
                cv2.imwrite(os.path.join(folder, f"{key}_{int(time.time())}_{n:04d}.jpg"),
                            cv2.cvtColor(frame, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 90])
                if i < args.burst - 1:
                    time.sleep(0.4)
            print(f"  {n} photos of {key}")
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        close()
    print(f"Done: {n} photos in {folder}/")


if __name__ == "__main__":
    sys.exit(main())
