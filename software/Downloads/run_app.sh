#!/usr/bin/env bash
# One command to start the rules app.
#   ./run_app.sh              the app on your Wi-Fi (phone or laptop on the same network)
#   ./run_app.sh --public     also makes a public link (needs cloudflared; stops when you press Ctrl+C)
#   ./run_app.sh --local-only only this computer
# Put this file in the same folder as app.py and rulebook.py (usually ~/Downloads).
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR" || exit 1
PORT=8080; PUBLIC=0; ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --public) PUBLIC=1 ;;
    --port) PORT="$2"; ARGS+=("--port" "$2"); shift ;;
    *) ARGS+=("$1") ;;
  esac
  shift
done

if [ -t 1 ] && [ -z "$NO_COLOR" ]; then G=$'\033[38;2;150;190;165m'; E=$'\033[1;38;2;240;138;128m'; Z=$'\033[0m'; else G=""; E=""; Z=""; fi
say() { printf '  %s%s%s\n' "$G" "$*" "$Z"; }
die() { printf '\n  %sProblem:%s %s\n\n' "$E" "$Z" "$*"; exit 1; }

for f in app.py rulebook.py; do [ -f "$f" ] || die "$f is not in $DIR"; done
[ -d presets ] || say "Tip: no 'presets' folder here, so the city picker will be empty."

# 1) Python environment: make it if it is missing, then use it
ENV="$HOME/sorter-env"
if [ ! -x "$ENV/bin/python3" ]; then
  say "Setting up the Python environment (one time, about a minute)..."
  python3 -m venv --system-site-packages "$ENV" >/dev/null 2>&1 || die "Could not make the environment. Run: sudo apt install -y python3-venv"
fi
PY="$ENV/bin/python3"

# 2) Packages: install only what is missing
if ! "$PY" -c "import flask, pypdf, docx" >/dev/null 2>&1; then
  say "Installing flask, pypdf and python-docx (one time)..."
  "$ENV/bin/pip" install -q flask pypdf python-docx || die "pip could not install the packages. Check the Wi-Fi."
fi

# 3) Public link (optional)
TUNNEL_PID=""; LOG=""
cleanup() { [ -n "$TUNNEL_PID" ] && kill "$TUNNEL_PID" 2>/dev/null; [ -n "$LOG" ] && rm -f "$LOG"; }
trap cleanup EXIT INT TERM
if [ "$PUBLIC" = 1 ]; then
  # find cloudflared: installed, or a downloaded file sitting in this folder
  CF="$(command -v cloudflared 2>/dev/null)"
  if [ -z "$CF" ]; then
    for f in ./cloudflared ./cloudflared-linux-arm64 ./cloudflared-linux-arm; do
      [ -f "$f" ] && { chmod +x "$f"; CF="$f"; break; }
    done
  fi
  [ -n "$CF" ] || die "cloudflared is not installed. Get the arm64 .deb from Cloudflare's GitHub releases, then: sudo dpkg -i cloudflared-linux-arm64.deb"
  # a public link needs a long access code
  CODE_FILE="$HOME/.sorter_app_code"
  if [ ! -s "$CODE_FILE" ] || [ "$(wc -c < "$CODE_FILE")" -lt 20 ]; then
    ( umask 077; "$PY" -c "import secrets; print(secrets.token_urlsafe(24))" > "$CODE_FILE" )
    say "Made a long access code for the public link."
  fi
  LOG="$(mktemp)"
  "$CF" tunnel --url "http://127.0.0.1:$PORT" >"$LOG" 2>&1 &
  TUNNEL_PID=$!
  say "Making the public link..."
  for _ in $(seq 1 30); do
    SORTER_PUBLIC_URL="$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$LOG" | head -1)"
    [ -n "$SORTER_PUBLIC_URL" ] && break
    kill -0 "$TUNNEL_PID" 2>/dev/null || { cat "$LOG"; die "cloudflared stopped. The message above says why."; }
    sleep 1
  done
  [ -n "$SORTER_PUBLIC_URL" ] || die "No public link appeared after 30 seconds."
  export SORTER_PUBLIC_URL
fi

# 4) Run the app (its address and access code are printed below)
"$PY" app.py "${ARGS[@]}"
