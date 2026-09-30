#!/usr/bin/env bash
# Start Open Dots on this Mac so your iPhone can continue your conversations.
#
#   ./scripts/start-mac.sh                       start (sets everything up on first run)
#   ./scripts/start-mac.sh --no-open             start without opening the browser
#   ./scripts/start-mac.sh --sign-in             open Open Dots in the browser, signed in
#   ./scripts/start-mac.sh --install-login-item  keep it running in the background
#   ./scripts/start-mac.sh --remove-login-item   stop running it in the background
#   ./scripts/start-mac.sh --setup-only          install and build, don't start
#
# The API listens on your local network so a linked iPhone can reach it; the
# web client stays on this Mac. While Open Dots runs, the Mac is kept from
# idle-sleeping (the display can still sleep) so your phone can reach it. Set
# OPEN_DOTS_ALLOW_SLEEP=1 to skip that. Updates install through this script:
# see scripts/update.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib.sh
. "$ROOT/scripts/lib.sh"

OPEN_BROWSER=1
SETUP_ONLY=0
PIDS=""
SERVER_PID=""
WEB_PID=""
UPDATE_REQUESTED=0

open_web() {
  local url
  [ "$OPEN_BROWSER" = 1 ] || return 0
  url=$(signin_url) || url=""
  open_url "${url:-http://localhost:$WEB_PORT}" || true
}

sign_in() {
  local url
  api_ready || { warn "Open Dots isn't running. Start it with: $0"; exit 1; }
  url=$(signin_url) || url=""
  [ -n "$url" ] || { warn "Couldn't create a sign-in link. Is $DATA_DIR/.auth-token readable?"; exit 1; }
  open_url "$url" || say "Open this link on this Mac (it works once, for 10 minutes): $url"
}

stop_children() {
  # shellcheck disable=SC2086
  [ -z "$PIDS" ] || kill $PIDS 2>/dev/null || true
  wait 2>/dev/null || true
  PIDS=""
}

stop() {
  trap - EXIT INT TERM USR1
  stop_children
  [ "$(cat "$PIDFILE" 2>/dev/null)" != "$$" ] || rm -f "$PIDFILE"
}

start_children() {
  local host="${HOST:-0.0.0.0}"
  cd "$ROOT/server"
  # Listen on the local network so a linked iPhone can reach this Mac. The
  # server asks this script (by its process id) to install updates.
  HOST="$host" PORT="$API_PORT" OPEN_DOTS_SUPERVISOR_PID=$$ \
    .venv/bin/python -m uvicorn app.main:app --host "$host" --port "$API_PORT" &
  SERVER_PID=$!
  PIDS="$SERVER_PID"

  if [ "${OPEN_DOTS_ALLOW_SLEEP:-0}" != 1 ] && command -v caffeinate >/dev/null 2>&1; then
    caffeinate -i -w "$SERVER_PID" &
    PIDS="$PIDS $!"
  fi

  (cd "$ROOT/client" && exec ./node_modules/.bin/next start -H 127.0.0.1 -p "$WEB_PORT") &
  WEB_PID=$!
  PIDS="$PIDS $WEB_PID"
  cd "$ROOT"
}

wait_until_ready() {
  local _
  for _ in $(seq 1 240); do
    api_ready && web_ready && return 0
    kill -0 "$SERVER_PID" 2>/dev/null && kill -0 "$WEB_PID" 2>/dev/null || return 1
    sleep 0.5
  done
  return 1
}

# The new version didn't come up: put the previous one back and start it.
roll_back() {
  stop_children
  "$ROOT/scripts/update.sh" rollback || true
  exec "$ROOT/scripts/start-mac.sh" --no-open
}

update_requested() {
  [ "$UPDATE_REQUESTED" = 1 ] || [ -f "$UPDATE_REQUEST" ]
}

# Stop, update, and start again as the new version of this script.
restart_for_update() {
  say "Installing an update…"
  rm -f "$UPDATE_REQUEST"
  stop_children
  "$ROOT/scripts/update.sh" apply || true
  exec "$ROOT/scripts/start-mac.sh" --no-open
}

keep_running_prompt() {
  local asked="$DATA_DIR/.background-asked" answer
  [ -t 0 ] && command -v launchctl >/dev/null 2>&1 && [ ! -f "$PLIST" ] && [ ! -f "$asked" ] || return 0
  mkdir -p "$DATA_DIR" && touch "$asked"
  printf "Keep Open Dots running in the background, so your iPhone can always reach this Mac? [Y/n] "
  read -r answer || answer=n
  case "$answer" in
    [nN]*) return 0 ;;
  esac
  install_login_item
  for _ in $(seq 1 240); do api_ready && web_ready && break; sleep 0.5; done
  say "Open Dots is running in the background: http://localhost:$WEB_PORT"
  open_web
  exit 0
}

main() {
  local arg verifying=0
  for arg in "$@"; do
    case "$arg" in
      --no-open) OPEN_BROWSER=0 ;;
      --setup-only) SETUP_ONLY=1 ;;
      --sign-in) sign_in; exit 0 ;;
      --install-login-item)
        install_login_item
        say "Open Dots now runs in the background and starts when you log in."
        say "Log: ~/Library/Logs/OpenDots.log"
        exit 0 ;;
      --remove-login-item)
        remove_login_item
        say "Open Dots no longer runs in the background."
        exit 0 ;;
      -h|--help) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
      *) warn "Unknown option: $arg (try --help)"; exit 2 ;;
    esac
  done

  if [ "$SETUP_ONLY" = 0 ] && api_ready && web_ready; then
    if [ "${OPEN_DOTS_BACKGROUND:-0}" = 1 ]; then
      # Started in the background while a copy started by hand is running: take
      # over when it stops, instead of exiting and being restarted every few seconds.
      while api_ready; do sleep 15; done
    else
      say "Open Dots is already running: http://localhost:$WEB_PORT"
      open_web
      exit 0
    fi
  fi

  command -v curl >/dev/null 2>&1 || { warn "Open Dots needs curl."; exit 1; }
  find_python >/dev/null || { warn "Open Dots needs Python 3.11 or newer. Try: brew install python"; exit 1; }
  node_ok || { warn "Open Dots needs Node.js 20 or newer. Try: brew install node"; exit 1; }

  # The first start after an update proves the new version works, or undoes it.
  [ "$(sed -n 's/.*"state": "\([a-z-]*\)".*/\1/p' "$UPDATE_DIR/status.json" 2>/dev/null)" = installed ] && verifying=1

  # ----- first run, or the first start of a new version ---------------------
  if ! setup_server || ! setup_client; then
    [ "$verifying" = 0 ] || roll_back
    warn "Couldn't set up Open Dots. See the messages above."
    exit 1
  fi
  [ "$SETUP_ONLY" = 0 ] || exit 0

  keep_running_prompt

  # ----- run ------------------------------------------------------------------
  mkdir -p "$DATA_DIR"
  printf '%s\n' "$$" > "$PIDFILE"
  trap stop EXIT
  trap 'stop; exit 0' INT TERM
  trap 'UPDATE_REQUESTED=1' USR1
  rm -f "$UPDATE_REQUEST"  # left over from before a restart

  start_children
  if ! wait_until_ready; then
    [ "$verifying" = 0 ] || roll_back
    warn "Open Dots didn't start. See the messages above."
    exit 1
  fi
  if [ "$verifying" = 1 ]; then
    "$ROOT/scripts/update.sh" confirm || true
  else
    cat <<MESSAGE

  Open Dots is running.

  On this Mac     http://localhost:$WEB_PORT
  On your iPhone  Choose "Continue on iPhone" in Open Dots and scan the code.

  Signed out? Run: $0 --sign-in
  If macOS asks whether Python may accept incoming connections, choose Allow.
  Press Ctrl+C to stop.

MESSAGE
    open_web
  fi

  # If either part stops, stop both, so a restart (by you, or by the background
  # login item) brings Open Dots back whole.
  while kill -0 "$SERVER_PID" 2>/dev/null && kill -0 "$WEB_PID" 2>/dev/null; do
    if update_requested; then restart_for_update; fi
    sleep 2
  done
  if update_requested; then restart_for_update; fi
  warn "Part of Open Dots stopped; stopping the rest."
  exit 1
}

# Everything above is read before anything runs, so an update that replaces
# this file can't change what the running copy does.
main "$@"; exit $?
