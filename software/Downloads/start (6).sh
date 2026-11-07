#!/usr/bin/env bash
# start.sh: the EZtrash control panel. Press 1-7 to run something; Esc closes.
#
#   ./start.sh            open the control panel
#   ./start.sh app        rules app on your Wi-Fi
#   ./start.sh public     rules app + permanent public link (Tailscale)
#   ./start.sh sort       run the trash sorter
#   ./start.sh train trashnet_sorted   train the model on a photo folder
#   ./start.sh live       show what the camera sees

# Where the sorter files live: next to this script if they are there, otherwise ~/Downloads.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ ! -f "$DIR/app.py" ] && [ ! -f "$DIR/sorter.py" ]; then
  for d in "$HOME/Downloads" "$HOME/Desktop" "$HOME"; do
    if [ -f "$d/app.py" ] || [ -f "$d/sorter.py" ]; then DIR="$d"; break; fi
  done
fi
cd "$DIR" || exit 1
PY="$HOME/sorter-env/bin/python3"
export EZTRASH_LAUNCHER=1   # lets the programs say "Esc" instead of "Ctrl+C"
chmod +x run_app.sh run_sorter.sh 2>/dev/null

# Keyboard: Ctrl+C no longer stops anything, so it's free for copying.
# Esc stops whatever is running and closes the launcher. The terminal goes back to normal when this closes.
if [ -t 0 ]; then
  SAVED_TTY="$(stty -g)"
  trap 'stty "$SAVED_TTY" 2>/dev/null; printf "\033[?25h"' EXIT
  stty intr '^['
fi

# ---------- colors: the same greens as the website ----------
if [ -t 1 ] && [ -z "$NO_COLOR" ]; then
  if [ "$COLORTERM" = truecolor ] || [ "$COLORTERM" = 24bit ] || [ -n "$VTE_VERSION" ]; then
    fg() { printf '\033[38;2;%sm' "$1"; }; bg() { printf '\033[48;2;%sm' "$1"; }
    CHART="201;218;63"; LEAF="52;165;99"; FOREST="19;57;43"; MINT="150;190;165"; WHITE="238;243;236"; RED="240;138;128"; DIMG="70;110;88"
  else
    fg() { printf '\033[38;5;%sm' "$1"; }; bg() { printf '\033[48;5;%sm' "$1"; }
    CHART=185; LEAF=71; FOREST=22; MINT=151; WHITE=255; RED=210; DIMG=65
  fi
  B=$'\033[1m'; R=$'\033[0m'
  C_CH="$(fg $CHART)"; C_LEAF="$(fg $LEAF)"; C_MINT="$(fg $MINT)"; C_WHITE="$(fg $WHITE)"; C_RED="$(fg $RED)"; C_DIM="$(fg $DIMG)"
  KEYC="$(bg $CHART)$(fg $FOREST)$B"
  CLEAR=$'\033[H\033[2J'; HIDE=$'\033[?25l'; SHOW=$'\033[?25h'; COLOR=1
else
  B=""; R=""; C_CH=""; C_LEAF=""; C_MINT=""; C_WHITE=""; C_RED=""; C_DIM=""; KEYC=""; CLEAR=""; HIDE=""; SHOW=""; COLOR=0
fi
ok()   { printf '  %s%s%s\n' "$C_LEAF$B" "$*" "$R"; }
bad()  { printf '  %s%s%s\n' "$C_RED$B" "$*" "$R"; }
note() { printf '  %s%s%s\n' "$C_MINT" "$*" "$R"; }

# ---------- the logo: the trash can whose body spells EZ (28 x 28 pixels, two pixels per text row) ----------
LOGO_MAP=(
  "....cccccccccccccccccccc...."
  "..cccccccccccccccccccccccc.."
  ".cccccccccccccccccccccccccc."
  ".cccccccccccccccccccccccccc."
  "ccccccccccccffffcccccccccccc"
  "ccccccccccccfccfcccccccccccc"
  "cccccffffffffffffffffffccccc"
  "ccccffffffffffffffffffffcccc"
  "cccccccccccccccccccccccccccc"
  "cccccccccccccccccccccccccccc"
  "ccccccfffffffffffffffffccccc"
  "ccccccfffffffffffffffffccccc"
  "ccccccffcccccccccccfffcccccc"
  "ccccccffcccccccccccfffcccccc"
  "ccccccffccccccccccfffccccccc"
  "ccccccffccccccccccfffccccccc"
  "cccccccffffffccccfffcccccccc"
  "cccccccffffffccccfffcccccccc"
  "cccccccffcccccccfffccccccccc"
  "cccccccffcccccccfffccccccccc"
  "cccccccffccccccfffcccccccccc"
  "cccccccfffffffffffffffcccccc"
  "ccccccccfffffffffffffccccccc"
  "cccccccccccccccccccccccccccc"
  ".cccccccccccccccccccccccccc."
  ".cccccccccccccccccccccccccc."
  "..cccccccccccccccccccccccc.."
  "....cccccccccccccccccccc...."
)
LOGO_LINES=()
build_logo() {
  local y x t b line
  for ((y = 0; y < ${#LOGO_MAP[@]}; y += 2)); do
    line=""
    for ((x = 0; x < ${#LOGO_MAP[y]}; x++)); do
      t="${LOGO_MAP[y]:x:1}"; b="${LOGO_MAP[y+1]:x:1}"
      if [ "$COLOR" = 0 ]; then
        if [ "$t$b" = ".." ]; then line+=" "; elif [ "$t" = f ] || [ "$b" = f ]; then line+="#"; else line+="+"; fi
        continue
      fi
      local ct cb
      [ "$t" = c ] && ct=$CHART || ct=$FOREST
      [ "$b" = c ] && cb=$CHART || cb=$FOREST
      if [ "$t$b" = ".." ]; then line+="$R "
      elif [ "$t" = . ]; then line+="$R$(fg "$cb")▄"
      elif [ "$b" = . ]; then line+="$R$(fg "$ct")▀"
      else line+="$(fg "$ct")$(bg "$cb")▀"; fi
    done
    LOGO_LINES+=("$line$R")
  done
}
build_logo
LOGO_W=${#LOGO_MAP[0]}

# ---------- live status ----------
pad() { printf "%-${2}s" "${1:0:$2}"; }                # cut/pad plain text to a width
dot() { if [ "$1" = on ]; then printf '%s●%s' "$C_LEAF" "$R"; else printf '%s○%s' "$C_RED" "$R"; fi; }
status_lines() {
  local city model cam ip temp up app
  city="$(sed -n 's/.*"city": *"\([^"]*\)".*/\1/p' rulebook.json 2>/dev/null | head -1)"
  if [ -n "$city" ]; then S_RULES="on $city"; else S_RULES="off none picked (safe defaults)"; fi
  if [ -f model_local.npz ]; then S_MODEL="on trained $(date -r model_local.npz +%Y-%m-%d)"; else S_MODEL="off not trained yet"; fi
  if ls /dev/video0 >/dev/null 2>&1; then S_CAM="on video device found"; else S_CAM="off no camera found"; fi
  ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  if [ -n "$ip" ]; then S_NET="on $ip"; else S_NET="off offline"; fi
  temp="$(awk '{printf "%.1f°C", $1/1000}' /sys/class/thermal/thermal_zone0/temp 2>/dev/null)"
  up="$(uptime -p 2>/dev/null | sed 's/^up //; s/ hours\?/h/; s/ minutes\?/m/; s/ days\?/d/; s/,//g')"
  S_SYS="on ${temp:-n/a}  up ${up:-?}"
  if pgrep -f "python[0-9.]* .*app\.py" >/dev/null 2>&1; then S_APP="on running"; else S_APP="off stopped"; fi
  if ! command -v tailscale >/dev/null 2>&1; then S_PUB="off not set up (press 6)"
  else
    local url; url="$(tailscale funnel status 2>/dev/null | grep -o 'https://[A-Za-z0-9.-]*\.ts\.net' | head -1)"
    if [ -n "$url" ]; then S_PUB="on ${url#https://}"
    elif tailscale status >/dev/null 2>&1; then S_PUB="off off (press 2 to turn on)"
    else S_PUB="off not signed in (press 6)"; fi
  fi
}
srow() {  # srow label "on|off text"
  local state="${2%% *}" text="${2#* }"
  printf '%s %s%s%s %s' "$(dot "$state")" "$C_MINT" "$(pad "$1" 8)" "$R" "$C_WHITE$(pad "$text" 34)$R"
}
mrow() {  # mrow key "title" "hint"
  printf '%s %s %s %s%s%s %s' "$KEYC" "$1" "$R" "$C_WHITE$B" "$(pad "$2" 16)" "$R" "$C_DIM$(pad "$3" 24)$R"
}
rule() { printf '%s%s%s' "$C_DIM" "$(printf '─%.0s' $(seq 1 46))" "$R"; }

panel() {
  status_lines
  local host; host="$(whoami)@$(hostname 2>/dev/null)"
  local right=(
    "${B}${C_CH}EZ${C_WHITE}trash${R} ${C_MINT}control panel${R}"
    "${C_DIM}$(pad "$host" 30)$(date +%H:%M)${R}"
    "$(rule)"
    "$(srow rules "$S_RULES")"
    "$(srow model "$S_MODEL")"
    "$(srow camera "$S_CAM")"
    "$(srow network "$S_NET")"
    "$(srow system "$S_SYS")"
    "$(srow app "$S_APP")"
    "$(srow link "$S_PUB")"
    "$(rule)"
    "$(mrow 1 "rules app" "serve on your wi-fi")"
    "$(mrow 2 "rules app+link" "permanent public link")"
    "$(mrow 3 "sorter" "camera + servo, live")"
    "$(mrow 4 "train" "from a photo folder")"
    "$(mrow 5 "camera check" "live predictions")"
    "$(mrow 6 "link setup" "tailscale, one time")"
    "$(mrow 7 "link off" "turn the public link off")"
    "$(rule)"
    "${KEYC} esc ${R} ${C_WHITE}${B}close${R}          ${C_DIM}press a key${R} ${C_CH}▌${R}"
  )
  local blank; blank="$(printf '%*s' "$LOGO_W" '')"
  printf '\n'
  local i n=${#right[@]}
  [ ${#LOGO_LINES[@]} -gt $n ] && n=${#LOGO_LINES[@]}
  for ((i = 0; i < n; i++)); do
    printf '  %s   %s\n' "${LOGO_LINES[i]:-$blank}" "${right[i]}"
  done
  printf '\n'
}

# a one-line header shown above a running program
header() {
  printf '%s\n  %s %s %s%s%s %s\n  %s\n\n' "$CLEAR" "${KEYC} EZ ${R}" "${B}${C_CH}EZ${C_WHITE}trash${R}" "$C_DIM" "//" "$R" "${C_MINT}$1${R}  ${C_DIM}esc stops it${R}" "$(rule)$(rule)"
}

# quick self-check the first time the panel opens
boot() {
  [ "$COLOR" = 1 ] || return
  printf '%s%s\n' "$CLEAR" "$HIDE"
  local step
  for step in "loading rules" "checking model" "scanning camera" "reading network" "checking link" "starting panel"; do
    printf '  %sezt>%s %s%s%s ' "$C_CH$B" "$R" "$C_MINT" "$(pad "$step" 18)" "$R"
    sleep 0.06; printf '%s........%s %sok%s\n' "$C_DIM" "$R" "$C_LEAF$B" "$R"; sleep 0.04
  done
  sleep 0.12; printf '%s' "$SHOW"
}

# ---------- keys ----------
key() {
  local k rest
  IFS= read -rsn1 k || { KEY="ESC"; return; }
  if [ "$k" = $'\e' ]; then
    IFS= read -rsn2 -t 0.05 rest
    if [ -n "$rest" ]; then KEY=""; else KEY="ESC"; fi
  else
    KEY="$k"
  fi
}
quit() { printf '\n  %sezt>%s %ssession closed. thanks for sorting.%s\n\n' "$C_CH$B" "$R" "$C_MINT" "$R"; exit 0; }
pause() {
  printf '  %sPress any key for the panel, or %sEsc%s%s to close.%s' "$C_MINT" "$C_CH$B" "$R" "$C_MINT" "$R"
  key; echo
  [ "$KEY" = "ESC" ] && quit
}

# ---------- running things ----------
run() {  # run "label" command...
  local label="$1"; shift
  header "$label"
  "$@"
  code=$?
  echo
  if [ "$code" -eq 0 ] || [ "$code" -eq 130 ]; then ok "Stopped."
  else bad "It stopped with an error (exit code $code). The message above says why."; fi
  pause
}
missing() {
  for f in "$@"; do
    if [ ! -e "$f" ]; then echo; bad "Missing: $f"; note "Put it in $DIR"; echo; pause; return 0; fi
  done
  return 1
}
no_env() {
  [ -x "$PY" ] && return 1
  echo; bad "No Python environment yet."; note "Pick option 1 once (it sets one up), or run: bash setup_pi.sh"; echo; pause; return 0
}
do_app()   { missing run_app.sh app.py rulebook.py && return; run "rules app" ./run_app.sh "$@"; }
do_sort()  { missing run_sorter.sh sorter.py rulebook.py localmodel.py && return; run "sorter" ./run_sorter.sh "$@"; }
do_live()  { missing recognize.py && return; no_env && return; run "camera check" "$PY" recognize.py live --picam; }
do_link_setup() { missing setup_tailscale.sh && return; run "public link setup" bash setup_tailscale.sh; }
do_link_off() {
  if ! command -v tailscale >/dev/null 2>&1; then echo; bad "Tailscale isn't set up, so there's no public link to turn off."; echo; pause; return; fi
  run "public link off" bash -c 'tailscale funnel reset 2>/dev/null || sudo tailscale funnel reset; echo "  The public link is off. Press 2 to turn it back on (same link)."'
}
do_train() {
  missing recognize.py && return; no_env && return
  local folder="$1"
  if [ -z "$folder" ]; then
    printf '  %sPhoto folder to train on%s %s(e.g. trashnet_sorted)%s: ' "$C_WHITE$B" "$R" "$C_MINT" "$R"
    read -r folder || return
  fi
  if [ ! -d "$folder" ]; then echo; bad "Folder not found: $folder"; echo; pause; return; fi
  run "train" "$PY" recognize.py train "$folder"
}

# A shortcut word runs that first, then shows the panel.
case "$1" in
  app)    shift; do_app "$@" ;;
  public) shift; do_app --public "$@" ;;
  sort)   shift; do_sort "$@" ;;
  train)  shift; do_train "$1" ;;
  live)   do_live ;;
  "")     boot ;;
  *)      echo "Unknown option: $1  (use app, public, sort, train, live, or nothing for the panel)"; exit 1 ;;
esac

while true; do
  printf '%s' "$CLEAR"
  panel
  key
  case "$KEY" in
    1) do_app ;;
    2) do_app --public ;;
    3) do_sort ;;
    4) do_train ;;
    5) do_live ;;
    6) do_link_setup ;;
    7) do_link_off ;;
    ESC|q|Q) quit ;;
    *) ;;
  esac
done

# Copy and paste in the Pi's terminal: select text and press Ctrl+Shift+C, paste with Ctrl+Shift+V
# (or right-click > Copy / Paste). To use plain Ctrl+C / Ctrl+V instead, change it in the terminal's
# Edit > Preferences > Shortcuts.
