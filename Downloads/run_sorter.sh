#!/usr/bin/env bash
# Starts the sorter with the Pi Camera Module (--picam).
# First it stops anything else that is holding the camera, so you don't get "Device or resource busy".
# Expects sorter.py in ~/Downloads. Extra options can be added, e.g.  ./run_sorter.sh --no-cloud
cd "$HOME/Downloads" || { echo "Can't find the Downloads folder"; exit 1; }

if [ ! -f sorter.py ]; then
  echo "sorter.py not found in $HOME/Downloads"
  exit 1
fi
for f in rulebook.py localmodel.py; do
  if [ ! -f "$f" ]; then
    echo "$f not found in $HOME/Downloads (it goes in the same folder as sorter.py)"
    exit 1
  fi
done
if [ ! -x "$HOME/sorter-env/bin/python3" ]; then
  echo "Python environment not found. Run:  bash setup_pi.sh"
  exit 1
fi

# Free the camera. Only exact matches are stopped, so this script and your terminal are never touched.
echo "Freeing the camera..."
# 1) an older run of the sorter (a python command whose arguments include sorter.py)
pkill -f '^([^ ]*/)?python3?[ ].*sorter\.py' 2>/dev/null
# 2) the Pi's built-in camera programs, by exact name
for name in rpicam-hello rpicam-still rpicam-vid rpicam-jpeg rpicam-raw rpicam-apps \
            libcamera-hello libcamera-still libcamera-vid libcamera-jpeg libcamera-raw; do
  pkill -x "$name" 2>/dev/null
done
sleep 2

# Anything still holding the camera? (warns but keeps going)
if command -v fuser >/dev/null 2>&1 && fuser /dev/media* /dev/video* >/dev/null 2>&1; then
  echo "Warning: something is still using the camera. If it fails, run 'sudo reboot' and try again."
fi

# With a trained model in the folder: the model identifies items and Claude is the backup.
# Without one: Claude identifies every item.
if [ -f model_local.npz ] || { [ -f model_unquant.tflite ] && [ -f labels.txt ]; }; then
  MODE=""
  echo "Trained model found: model first, Claude as backup."
else
  MODE="--claude-main"
  echo "No trained model yet: Claude identifies every item."
fi
exec "$HOME/sorter-env/bin/python3" sorter.py $MODE --test --picam "$@"
