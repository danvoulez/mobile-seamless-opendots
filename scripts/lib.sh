# shellcheck shell=bash disable=SC2034
# Shared by start-mac.sh, update.sh and uninstall.sh. Needs ROOT set to the
# Open Dots folder. Works with the bash 3.2 that ships with macOS.

# Settings that should survive restarts and updates, such as PUBLIC_URL for a
# Cloudflare Tunnel, go in ~/.open-dots/open-dots.env as KEY=value lines.
CONFIG="${DATA_DIR:-$HOME/.open-dots}/open-dots.env"
if [ -f "$CONFIG" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$CONFIG"
  set +a
fi

DATA_DIR="${DATA_DIR:-$HOME/.open-dots}"
LABEL="dev.opendots.open-dots"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PIDFILE="$DATA_DIR/open-dots.pid"
UPDATE_DIR="$DATA_DIR/update"
# The server asks for an update by creating this file (and sending SIGUSR1).
UPDATE_REQUEST="$UPDATE_DIR/requested"
# One address serves the Mac page, the iPhone app and the API. Not 3000 or
# 8000: many other tools use those. Set OPEN_DOTS_PORT in open-dots.env to change it.
OPEN_DOTS_PORT="${OPEN_DOTS_PORT:-4747}"

say() { printf '%s\n' "$*"; }
warn() { printf '%s\n' "$*" >&2; }

api_ready() {
  curl -fsS -m 5 "http://127.0.0.1:$OPEN_DOTS_PORT/api/v1/health" >/dev/null 2>&1
}

# The Mac page is served (it is missing until the web client is built).
web_ready() {
  curl -fsS -m 10 -o /dev/null "http://127.0.0.1:$OPEN_DOTS_PORT/" 2>/dev/null
}

# The address other computers and phones on this network use: the Bonjour name,
# which stays valid when the IP changes. Nothing when Open Dots stays on loopback.
network_url() {
  local name
  case "${HOST:-0.0.0.0}" in 127.0.0.1|localhost|::1) return 1 ;; esac
  name=$(scutil --get LocalHostName 2>/dev/null) || return 1
  printf 'http://%s.local:%s\n' "$name" "$OPEN_DOTS_PORT"
}

# The start script that is running Open Dots, if any.
supervisor_pid() {
  local pid
  pid=$(cat "$PIDFILE" 2>/dev/null) || return 1
  case "$pid" in ''|*[!0-9]*) return 1 ;; esac
  kill -0 "$pid" 2>/dev/null || return 1
  printf '%s\n' "$pid"
}

# A Python new enough for Open Dots (3.11 or newer).
find_python() {
  local candidate
  for candidate in "${PYTHON:-}" python3 python3.14 python3.13 python3.12 python3.11; do
    [ -n "$candidate" ] || continue
    command -v "$candidate" >/dev/null 2>&1 || continue
    if "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

node_ok() {
  command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1 \
    && node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 20 ? 0 : 1)' 2>/dev/null
}

# ----- server -------------------------------------------------------------------

# Create the Python environment and install exactly the tested versions.
# Reinstalls whenever the lockfile's contents change (an update or a rollback).
setup_server() {
  local python lock
  python=$(find_python) || { warn "Open Dots needs Python 3.11 or newer. Try: brew install python"; return 1; }
  (
    cd "$ROOT/server" || exit 1
    if [ -x .venv/bin/python ] && ! .venv/bin/python -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
      rm -rf .venv  # made with an older Python
    fi
    if [ ! -x .venv/bin/python ]; then
      say "Setting up the Open Dots server…"
      "$python" -m venv .venv || exit 1
      rm -f .venv/.installed-lock
    fi
    lock=requirements.lock
    [ -f "$lock" ] || lock=requirements.txt
    if ! cmp -s "$lock" .venv/.installed-lock; then
      if ! .venv/bin/python -m pip install --quiet --disable-pip-version-check -r "$lock"; then
        [ "$lock" = requirements.lock ] || exit 1
        warn "The tested versions didn't install on this Mac; installing the latest compatible ones instead."
        .venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt || exit 1
      fi
      cp "$lock" .venv/.installed-lock
    fi
  )
}

# ----- web client ---------------------------------------------------------------

setup_client_modules() {
  (
    cd "$ROOT/client" || exit 1
    if [ -f package-lock.json ]; then
      cmp -s package-lock.json node_modules/.open-dots-lock && exit 0
      say "Installing the web client…"
      npm ci --no-audit --no-fund --loglevel=error || exit 1
      cp package-lock.json node_modules/.open-dots-lock
    elif [ ! -d node_modules ] || [ package.json -nt node_modules/.package-lock.json ]; then
      say "Installing the web client…"
      npm install --no-audit --no-fund --loglevel=error || exit 1
    fi
  )
}

# Identifies the committed web client sources; empty with local edits.
client_stamp() {
  git -C "$ROOT" rev-parse -q --verify HEAD:client 2>/dev/null || return 1
  [ -z "$(git -C "$ROOT" status --porcelain -- client 2>/dev/null)" ]
}

client_needs_build() {
  local stamp
  [ -f "$ROOT/client/.next/BUILD_ID" ] && [ -f "$ROOT/client/out/index.html" ] || return 0
  if stamp=$(client_stamp); then
    [ "$stamp" != "$(cat "$ROOT/client/.next/.open-dots-source" 2>/dev/null)" ]
    return
  fi
  (cd "$ROOT/client" && [ -n "$(find app components lib package.json next.config.mjs tailwind.config.js -newer .next/BUILD_ID -print -quit 2>/dev/null)" ])
}

build_client() {
  say "Building the web client…"
  (cd "$ROOT/client" && ./node_modules/.bin/next build >/dev/null) || return 1
  client_stamp > "$ROOT/client/.next/.open-dots-source" 2>/dev/null || rm -f "$ROOT/client/.next/.open-dots-source"
}

setup_client() {
  setup_client_modules || return 1
  if client_needs_build; then build_client || return 1; fi
}

# ----- signing in ---------------------------------------------------------------

owner_token() {
  if [ -n "${APP_AUTH_TOKEN:-}" ]; then printf '%s\n' "$APP_AUTH_TOKEN"; else cat "$DATA_DIR/.auth-token" 2>/dev/null; fi
}

# A one-time link that opens the web client already signed in.
signin_url() {
  local token response
  token=$(owner_token) || return 1
  [ -n "$token" ] || return 1
  response=$(curl -fsS -m 10 -X POST -H "Authorization: Bearer $token" \
    "http://127.0.0.1:$OPEN_DOTS_PORT/api/v1/auth/signin-links" 2>/dev/null) || return 1
  printf '%s\n' "$response" | sed -n 's/.*"url":"\([^"]*\)".*/\1/p'
}

open_url() {
  command -v open >/dev/null 2>&1 && open "$1" >/dev/null 2>&1
}

# ----- running in the background (macOS login item) ---------------------------

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
  <dict>
    <key>PATH</key><string>$PATH</string>
    <key>OPEN_DOTS_BACKGROUND</key><string>1</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/OpenDots.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/OpenDots.log</string>
</dict>
</plist>
PLIST
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
}

remove_login_item() {
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
}
