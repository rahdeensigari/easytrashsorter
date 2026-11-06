#!/usr/bin/env bash
# One-time setup for the sorter on a Raspberry Pi (Raspberry Pi OS 64-bit).
# Run it from the folder that contains sorter.py:   bash setup_pi.sh
set -e

echo "== 1/4 Installing system packages =="
sudo apt update
sudo apt install -y python3-opencv python3-picamera2 python3-lgpio python3-venv

echo "== 2/4 Creating the Python environment =="
python3 -m venv --system-site-packages "$HOME/sorter-env"
# shellcheck disable=SC1091
source "$HOME/sorter-env/bin/activate"
pip install --upgrade pip
pip install anthropic ai-edge-litert flask pypdf python-docx onnxruntime scikit-learn pillow

echo "== 3/4 API key (optional) =="
echo "The key is only for Claude: the backup when the on-device model is unsure, and reading a city's rules in app.py."
echo "Training and running the on-device model do NOT need it. Press Enter to skip."
KEY_FILE="$HOME/.sorter_api_key"
if [ -s "$KEY_FILE" ]; then
  read -r -p "A key is already saved. Replace it? (y/N) " ans
  [ "$ans" = "y" ] || [ "$ans" = "Y" ] || { echo "Keeping the existing key."; SKIP_KEY=1; }
fi
if [ -z "$SKIP_KEY" ]; then
  echo "Paste your API key (it starts with sk-ant-), or press Enter to skip. Nothing will show as you paste, that's normal."
  read -r -s -p "API key: " KEY
  echo
  if [ -z "$KEY" ]; then
    echo "Skipped. Claude is off until you run this script again and add a key."
    SKIP_KEY=1
    NO_KEY=1
  elif [[ "$KEY" != sk-ant-* ]]; then
    echo "That doesn't look like an Anthropic key (should start with sk-ant-). Run this script again."
    exit 1
  else
    ( umask 077; printf '%s\n' "$KEY" > "$KEY_FILE" )   # only your user can read it
    chmod 600 "$KEY_FILE"
    echo "Saved to $KEY_FILE (private)."
  fi
  unset KEY
fi

echo "== 4/4 Testing the connection to Claude =="
if [ -n "$NO_KEY" ] || [ ! -s "$KEY_FILE" ]; then
  echo "No key saved, so nothing to test. That's fine for the on-device model."
else
python3 - <<'PY'
import os, sys
try:
    import anthropic
    key = open(os.path.expanduser("~/.sorter_api_key")).read().strip()
    msg = anthropic.Anthropic(api_key=key, timeout=15).messages.create(
        model="claude-haiku-5-5", max_tokens=20, thinking={"type": "disabled"},
        messages=[{"role": "user", "content": "Reply with the single word: ready"}])
    print("Claude says:", "".join(b.text for b in msg.content if b.type == "text"))
except Exception as e:
    print("Connection test FAILED:", type(e).__name__, e)
    print("Check the key, your Wi-Fi, and that the account has credit.")
    sys.exit(1)
PY
fi

cat <<'DONE'

All set. To run the sorter:
    source ~/sorter-env/bin/activate
    python3 app.py                              # add a city's rules (open the address it prints)
    python3 train_local.py <photo folders>      # train the on-device model on the Pi (makes model_local.npz)
    python3 sorter.py --test                    # trained model first, Claude as backup
    python3 sorter.py --claude-main --test      # Claude identifies every item
Press Ctrl+C to stop. Results are saved to sort_log.csv.
DONE
