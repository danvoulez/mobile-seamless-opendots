#!/usr/bin/env bash
# Start Open Dots on this Mac so your iPhone can continue your conversations.
#
#   ./scripts/start-mac.sh                       start (sets everything up on first run)
#   ./scripts/start-mac.sh --no-open             start without opening the browser
#   ./scripts/start-mac.sh --install-login-item  keep it running in the background
#   ./scripts/start-mac.sh --remove-login-item   stop running it in the background
#
# The API listens on your local network so a linked iPhone can reach it; the
# web client stays on this Mac. While Open Dots runs, the Mac is kept from
# idle-sleeping (the display can still sleep) so your phone can reach it. Set
# OPEN_DOTS_ALLOW_SLEEP=1 to skip that.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Settings that should survive restarts, such as PUBLIC_URL for a Cloudflare
# Tunnel, go in ~/.open-dots/open-dots.env as KEY=value lines.
CONFIG="${DATA_DIR:-$HOME/.open-dots}/open-dots.env"
if [ -f "$CONFIG" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$CONFIG"
  set +a
fi

LABEL="dev.opendots.open-dots"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
API_PORT=8000   # the web client expects the API here
WEB_PORT=3000
OPEN_BROWSER=1

install_login_item() {
  mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
  # launchd starts with a bare PATH; keep the one that found python3 and npm.
  cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$ROOT/scripts/start-mac.sh</string>
    <string>--no-open</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>$PATH</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/OpenDots.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/OpenDots.log</string>
</dict>
</plist>
PLIST
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  echo "Open Dots now runs in the background and starts when you log in."
  echo "Log: ~/Library/Logs/OpenDots.log"
}

remove_login_item() {
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Open Dots no longer runs in the background."
}

api_ready() {
  curl -fsS "http://127.0.0.1:$API_PORT/api/v1/health" >/dev/null 2>&1
}

web_ready() {
  curl -fsS "http://127.0.0.1:$WEB_PORT" >/dev/null 2>&1
}

open_web() {
  if [ "$OPEN_BROWSER" = 1 ] && command -v open >/dev/null 2>&1; then
    open "http://localhost:$WEB_PORT" || true
  fi
}

for arg in "$@"; do
  case "$arg" in
    --no-open) OPEN_BROWSER=0 ;;
    --install-login-item) install_login_item; exit 0 ;;
    --remove-login-item) remove_login_item; exit 0 ;;
    -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

# Already running (for example in the background): just open it.
if api_ready && web_ready; then
  echo "Open Dots is already running: http://localhost:$WEB_PORT"
  open_web
  exit 0
fi

need() {
  command -v "$1" >/dev/null 2>&1 || { echo "Open Dots needs $1. $2" >&2; exit 1; }
}
need python3 "Install Python 3.10 or newer: brew install python"
need npm "Install Node.js: brew install node"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
  || { echo "Open Dots needs Python 3.10 or newer (found $(python3 --version)). Try: brew install python" >&2; exit 1; }

# ----- first-run setup ----------------------------------------------------------

cd "$ROOT/server"
if [ ! -x .venv/bin/python ]; then
  echo "Setting up the Open Dots server…"
  python3 -m venv .venv
fi
if [ ! -f .venv/.installed ] || [ requirements.txt -nt .venv/.installed ]; then
  .venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt
  touch .venv/.installed
fi

cd "$ROOT/client"
if [ ! -f node_modules/.package-lock.json ] || [ package.json -nt node_modules/.package-lock.json ]; then
  echo "Installing the web client…"
  npm install --no-audit --no-fund
fi
if [ ! -f .next/BUILD_ID ] || [ -n "$(find app components lib -newer .next/BUILD_ID -print -quit)" ]; then
  echo "Building the web client…"
  npm run build
fi

# ----- keep it running ----------------------------------------------------------

# Your iPhone can only reach the Mac while Open Dots runs, so offer once to keep
# it running in the background (it then also starts when you log in).
ASKED="${DATA_DIR:-$HOME/.open-dots}/.background-asked"
if [ -t 0 ] && command -v launchctl >/dev/null 2>&1 && [ ! -f "$PLIST" ] && [ ! -f "$ASKED" ]; then
  mkdir -p "$(dirname "$ASKED")" && touch "$ASKED"
  printf "Keep Open Dots running in the background, so your iPhone can always reach this Mac? [Y/n] "
  read -r answer || answer=n
  case "$answer" in
    [nN]*) ;;
    *)
      install_login_item
      for _ in $(seq 1 120); do api_ready && web_ready && break; sleep 0.5; done
      echo "Open Dots is running: http://localhost:$WEB_PORT"
      open_web
      exit 0
      ;;
  esac
fi

# ----- run ----------------------------------------------------------------------

PIDS=""
stop() {
  trap - EXIT INT TERM
  # shellcheck disable=SC2086
  kill $PIDS 2>/dev/null || true
  wait 2>/dev/null || true
}
trap stop EXIT INT TERM

cd "$ROOT/server"
# Listen on the local network so a linked iPhone can reach this Mac.
export HOST="${HOST:-0.0.0.0}" PORT="$API_PORT"
.venv/bin/python -m uvicorn app.main:app --host "$HOST" --port "$API_PORT" &
SERVER_PID=$!
PIDS="$SERVER_PID"

if [ "${OPEN_DOTS_ALLOW_SLEEP:-0}" != 1 ] && command -v caffeinate >/dev/null 2>&1; then
  caffeinate -i -w "$SERVER_PID" &
  PIDS="$PIDS $!"
fi

(cd "$ROOT/client" && exec ./node_modules/.bin/next start -H 127.0.0.1 -p "$WEB_PORT") &
PIDS="$PIDS $!"

for _ in $(seq 1 60); do
  api_ready && break
  kill -0 "$SERVER_PID" 2>/dev/null || { echo "The Open Dots server stopped. See the messages above." >&2; exit 1; }
  sleep 0.5
done

DATA_DIR_SHOWN="${DATA_DIR:-~/.open-dots}"
cat <<MESSAGE

  Open Dots is running.

  On this Mac     http://localhost:$WEB_PORT
  On your iPhone  Choose "Continue on iPhone" in Open Dots and scan the code.

  First sign-in: cat $DATA_DIR_SHOWN/.auth-token
  If macOS asks whether Python may accept incoming connections, choose Allow.
  Press Ctrl+C to stop.

MESSAGE

open_web
wait "$SERVER_PID"
