#!/usr/bin/env bash
# Install Open Dots on this Mac:
#
#   curl -fsSL https://raw.githubusercontent.com/danvoulez/mobile-seamless-opendots/main/scripts/install.sh | bash
#
# It checks for Python and Node.js (offering to install them with Homebrew),
# downloads Open Dots to ~/.open-dots/app, sets it up, keeps it running in the
# background, and opens it in your browser already signed in. Run it again to
# repair an install. To remove Open Dots: ~/.open-dots/app/scripts/uninstall.sh
#
# Options: --yes (accept the defaults without asking), --no-background
# (don't start at login), --no-open (don't open the browser).
# Environment: OPEN_DOTS_HOME (where to install), OPEN_DOTS_REPO (git URL),
# UPDATE_CHANNEL (the branch to follow; default stable).
set -euo pipefail

main() {
  local assume_yes=0 background=1 open_browser=1 arg
  for arg in "$@"; do
    case "$arg" in
      --yes|-y) assume_yes=1 ;;
      --no-background) background=0 ;;
      --no-open) open_browser=0 ;;
      -h|--help) sed -n '2,15p' "$0" 2>/dev/null | sed 's/^# \{0,1\}//'; return 0 ;;
      *) printf 'Unknown option: %s\n' "$arg" >&2; return 2 ;;
    esac
  done

  local data_dir="${DATA_DIR:-$HOME/.open-dots}"
  local app_dir="${OPEN_DOTS_HOME:-$data_dir/app}"
  local repo="${OPEN_DOTS_REPO:-https://github.com/danvoulez/mobile-seamless-opendots.git}"
  local channel="${UPDATE_CHANNEL:-stable}"

  say() { printf '%s\n' "$*"; }
  step() { printf '\n\033[1m%s\033[0m\n' "$*"; }
  fail() { printf '\n%s\n' "$*" >&2; exit 1; }
  # Questions work even when this script arrives through a pipe.
  ask() {  # question default(y|n)
    local answer=""
    if [ "$assume_yes" = 1 ] || ! (: </dev/tty) 2>/dev/null; then
      [ "$2" = y ]
      return
    fi
    printf '%s ' "$1"
    read -r answer </dev/tty || answer=""
    case "${answer:-$2}" in [yY]*) return 0 ;; *) return 1 ;; esac
  }

  say "Installing Open Dots"
  case "$(uname -s)" in
    Darwin) ;;
    Linux) say "(Linux: Open Dots will run, but starting at login is set up only on macOS.)"; background=0 ;;
    *) fail "Open Dots installs on macOS (and Linux)." ;;
  esac

  # ----- what Open Dots needs -------------------------------------------------
  step "Checking what Open Dots needs"
  local missing=""
  command -v git >/dev/null 2>&1 || missing="$missing git"
  command -v curl >/dev/null 2>&1 || missing="$missing curl"
  python_ok || missing="$missing python"
  node_ok || missing="$missing node"
  if [ -n "$missing" ]; then
    say "Missing:$missing"
    if command -v brew >/dev/null 2>&1; then
      ask "Install them with Homebrew now? [Y/n]" y || fail "Install$missing, then run this again."
      # shellcheck disable=SC2086
      brew install $missing || fail "Homebrew couldn't install$missing."
      hash -r
    else
      fail "Install$missing (the easiest way is Homebrew: https://brew.sh), then run this again."
    fi
    python_ok || fail "Open Dots needs Python 3.11 or newer."
    node_ok || fail "Open Dots needs Node.js 20 or newer."
  fi
  say "Python, Node.js and git are ready."

  # ----- download -------------------------------------------------------------
  step "Downloading Open Dots"
  if [ -d "$app_dir/.git" ]; then
    say "Already downloaded to $app_dir; setting it up again."
  elif [ -e "$app_dir" ]; then
    fail "$app_dir already exists and isn't Open Dots. Move it, or set OPEN_DOTS_HOME."
  else
    mkdir -p "$(dirname "$app_dir")"
    if ! git clone --quiet --branch "$channel" "$repo" "$app_dir" 2>/dev/null; then
      # Before CI has published a tested version, start from the default branch.
      git clone --quiet "$repo" "$app_dir" || fail "Couldn't download Open Dots from $repo."
      say "No tested ($channel) version yet; installed the latest code. Updates start once one is published."
    fi
  fi
  mkdir -p "$data_dir"
  # Tells the uninstaller this folder was created by the installer.
  printf '%s\n' "$app_dir" > "$data_dir/.installed-app"
  say "Open Dots is in $app_dir"
  # The downloaded version's own settings and checks: its port (and
  # open-dots.env), whether it is up, its address on the network.
  ROOT="$app_dir"
  export DATA_DIR="$data_dir"
  # shellcheck source=lib.sh
  . "$app_dir/scripts/lib.sh"

  # ----- set up ---------------------------------------------------------------
  step "Setting up (a minute or two the first time)"
  DATA_DIR="$data_dir" "$app_dir/scripts/start-mac.sh" --setup-only || fail "Setup didn't finish. See the messages above."

  # ----- start ----------------------------------------------------------------
  step "Starting Open Dots"
  touch "$data_dir/.background-asked"
  if [ "$background" = 1 ] && ask "Keep Open Dots running in the background and start it when you log in? [Y/n]" y; then
    if DATA_DIR="$data_dir" "$app_dir/scripts/start-mac.sh" --install-login-item >/dev/null; then
      say "Open Dots runs in the background and starts when you log in."
    else
      say "Couldn't set up starting at login; starting Open Dots for now."
      background=0
    fi
  else
    background=0
  fi
  if [ "$background" = 0 ]; then
    mkdir -p "$data_dir/logs"
    DATA_DIR="$data_dir" nohup "$app_dir/scripts/start-mac.sh" --no-open >"$data_dir/logs/open-dots.log" 2>&1 &
    say "Open Dots is running until you restart this computer. Log: $data_dir/logs/open-dots.log"
  fi
  local ready=0 network _
  for _ in $(seq 1 240); do
    if api_ready && web_ready; then
      ready=1
      break
    fi
    sleep 0.5
  done
  [ "$ready" = 1 ] || fail "Open Dots didn't start. Try: $app_dir/scripts/start-mac.sh"

  step "Open Dots is ready"
  say "  On this Mac      http://localhost:${OPEN_DOTS_PORT:-4747}"
  if network=$(network_url 2>/dev/null); then
    say "  On your network  $network   (on another Mac: open it in Safari, then File → Add to Dock)"
  fi
  say "  On your iPhone   choose Continue on iPhone in Open Dots and scan the code"
  say "  Updates          install by themselves (Settings → Updates)"
  say "  Signed out?      $app_dir/scripts/start-mac.sh --sign-in"
  say "  Uninstall        $app_dir/scripts/uninstall.sh"
  if [ "$open_browser" = 1 ]; then
    DATA_DIR="$data_dir" "$app_dir/scripts/start-mac.sh" --sign-in || true
  fi
  say ""
  say "First, add your model provider in Settings (the gear at the bottom left)."
}

python_ok() {
  local candidate
  for candidate in python3 python3.14 python3.13 python3.12 python3.11; do
    command -v "$candidate" >/dev/null 2>&1 \
      && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null && return 0
  done
  return 1
}

node_ok() {
  command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1 \
    && node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 20 ? 0 : 1)' 2>/dev/null
}

# Wrapped in main so a download cut off halfway runs nothing.
main "$@"
