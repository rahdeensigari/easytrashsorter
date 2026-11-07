#!/usr/bin/env bash
# One command to start the rules app.
#   ./run_app.sh              the app on your Wi-Fi (phone or laptop on the same network)
#   ./run_app.sh --public     also turns on the permanent public link (Tailscale Funnel; set up once with setup_tailscale.sh)
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

# 3) Public link (optional): Tailscale Funnel gives this Pi one permanent https://<name>.<tailnet>.ts.net link
ts() {  # run a tailscale command; without sudo if this user is the Tailscale operator, else with sudo
  tailscale "$@" 2>/dev/null || sudo tailscale "$@"
}
if [ "$PUBLIC" = 1 ]; then
  command -v tailscale >/dev/null 2>&1 || die "Tailscale isn't installed yet. In the launcher press 6, or run: bash setup_tailscale.sh"
  tailscale status >/dev/null 2>&1 || die "Tailscale isn't signed in. In the launcher press 6, or run: bash setup_tailscale.sh"
  say "Turning on the public link (Tailscale Funnel)..."
  say "The first time, Tailscale may print a link to approve Funnel: open it, allow it, and this continues."
  if ! tailscale funnel --bg "$PORT" 2>/dev/null; then
    sudo tailscale funnel --bg "$PORT" || die "Tailscale couldn't turn on Funnel. The message above says why."
  fi
  SORTER_PUBLIC_URL="$(ts funnel status | grep -o 'https://[A-Za-z0-9.-]*\.ts\.net' | head -1)"
  [ -n "$SORTER_PUBLIC_URL" ] || die "Funnel is on but no link was found. Check with: tailscale funnel status"
  export SORTER_PUBLIC_URL
  say "Public link: $SORTER_PUBLIC_URL (it stays the same every time)"
fi

# 4) Run the app (its address and access code are printed below)
"$PY" app.py "${ARGS[@]}"
