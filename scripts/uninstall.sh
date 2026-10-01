#!/usr/bin/env bash
# Remove Open Dots from this Mac.
#
#   ./scripts/uninstall.sh                 asks before removing anything
#   ./scripts/uninstall.sh --yes           remove the app, keep your chats
#   ./scripts/uninstall.sh --yes --delete-data
#                                          remove the app and your data too
#
# It stops Open Dots, removes the background login item, and deletes the app
# folder if the installer created it (a folder you cloned yourself is left in
# place). Your chats, settings and linked devices in ~/.open-dots are kept
# unless you choose to delete them; reinstalling picks them up again.
set -euo pipefail

main() {
  local assume_yes=0 delete_data=ask arg
  for arg in "$@"; do
    case "$arg" in
      --yes|-y) assume_yes=1 ;;
      --delete-data) delete_data=yes ;;
      --keep-data) delete_data=no ;;
      -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; return 0 ;;
      *) warn "Unknown option: $arg (try --help)"; return 2 ;;
    esac
  done

  ask() {  # question default(y|n); --yes answers yes, no terminal answers no
    local answer=""
    [ "$assume_yes" = 0 ] || return 0
    (: </dev/tty) 2>/dev/null || return 1
    printf '%s ' "$1"
    read -r answer </dev/tty || answer=""
    case "${answer:-$2}" in [yY]*) return 0 ;; *) return 1 ;; esac
  }

  local installed_app="" app_owned=0
  installed_app=$(cat "$DATA_DIR/.installed-app" 2>/dev/null || true)
  [ -n "$installed_app" ] && [ "$installed_app" = "$ROOT" ] && app_owned=1

  say "This removes Open Dots from this Mac:"
  say "  • stops Open Dots and removes it from your login items"
  if [ "$app_owned" = 1 ]; then
    say "  • deletes the app in $ROOT"
  else
    say "  • leaves $ROOT in place (you downloaded it yourself)"
  fi
  if [ "$delete_data" = yes ]; then
    say "  • deletes your chats, settings and linked devices in $DATA_DIR"
  fi
  ask "Continue? [y/N]" n || { say "Nothing was removed. (Use --yes to run without a terminal.)"; return 1; }
  if [ "$delete_data" = ask ]; then
    if [ "$assume_yes" = 0 ] && ask "Also delete your chats, settings and linked devices in $DATA_DIR? [y/N]" n; then
      delete_data=yes
    else
      delete_data=no
    fi
  fi

  # ----- stop -------------------------------------------------------------------
  if command -v launchctl >/dev/null 2>&1; then
    remove_login_item
  fi
  local pid _
  if pid=$(supervisor_pid); then
    kill -TERM "$pid" 2>/dev/null || true
    for _ in $(seq 1 40); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
  fi
  if api_ready; then
    warn "Something is still answering on port $OPEN_DOTS_PORT (another copy of Open Dots?). Stop it with Ctrl+C where it runs."
  fi
  say "Stopped Open Dots."

  # ----- remove -----------------------------------------------------------------
  rm -f "$HOME/Library/Logs/OpenDots.log"
  if [ "$app_owned" = 1 ]; then
    cd "$HOME"
    rm -rf "$ROOT"
    rm -f "$DATA_DIR/.installed-app"
    say "Removed the app."
  fi
  if [ "$delete_data" = yes ]; then
    rm -rf "$DATA_DIR"
    say "Deleted your chats, settings and linked devices."
  else
    rm -f "$PIDFILE" "$DATA_DIR/.background-asked"
    say "Kept your chats and settings in $DATA_DIR. Reinstalling picks them up again."
  fi

  say ""
  say "Open Dots is uninstalled. Two things it can't do for you:"
  say "  • On your iPhone, touch and hold the Open Dots icon, then Remove App."
  say "  • If you set up a Cloudflare Tunnel or Tailscale for it, remove that separately."
}

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib.sh
. "$ROOT/scripts/lib.sh"

# Wrapped in main: the script deletes its own folder while it runs.
main "$@"; exit $?
