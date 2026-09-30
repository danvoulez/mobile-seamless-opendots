#!/usr/bin/env bash
# Update Open Dots to the latest tested version.
#
#   ./scripts/update.sh          update now (Open Dots restarts in a moment)
#   ./scripts/update.sh check    show what's new without changing anything
#
# You rarely need this: Open Dots checks every few minutes, shows an Update
# button on the Mac, and installs updates by itself unless you turn that off
# in Settings. Every change merged to main is tested first; only versions that
# pass reach the "stable" branch this Mac follows (UPDATE_CHANNEL).
#
# The start script uses these while Open Dots is stopped:
#   apply     fetch, back up the database, check out, install and build
#   confirm   the new version started: forget the previous one
#   rollback  the new version didn't start: put the previous one back
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib.sh
. "$ROOT/scripts/lib.sh"

CHANNEL="${UPDATE_CHANNEL:-stable}"
STATUS="$UPDATE_DIR/status.json"
BACKUPS="$DATA_DIR/backups"
DATABASE="$DATA_DIR/open-dots.sqlite3"

write_status() {  # state from to message (no quotes in any of them)
  mkdir -p "$UPDATE_DIR"
  printf '{"state": "%s", "from": "%s", "to": "%s", "at": "%s", "message": "%s"}\n' \
    "$1" "$2" "$3" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$4" > "$STATUS.tmp" && mv "$STATUS.tmp" "$STATUS"
}

status_field() {
  sed -n "s/.*\"$1\": \"\\([^\"]*\\)\".*/\\1/p" "$STATUS" 2>/dev/null
}

fetch_channel() {
  git -C "$ROOT" fetch --quiet --no-tags origin "+refs/heads/$CHANNEL:refs/remotes/origin/$CHANNEL" 2>/dev/null \
    && git -C "$ROOT" rev-parse "refs/remotes/origin/$CHANNEL"
}

python_in_venv() {
  "$ROOT/server/.venv/bin/python" "$@"
}

schema_version() {  # database
  [ -f "$1" ] || { echo 0; return; }
  python_in_venv - "$1" <<'PY' 2>/dev/null || echo 0
import sqlite3, sys
try:
    row = sqlite3.connect(sys.argv[1]).execute("SELECT max(version) FROM schema_migrations").fetchone()
    print(row[0] or 0)
except sqlite3.Error:
    print(0)
PY
}

# A consistent copy of the database, even if something is still writing to it.
backup_database() {  # from
  local destination
  [ -f "$DATABASE" ] || return 0
  destination="$BACKUPS/$(date +%Y%m%d-%H%M%S)-$(printf '%s' "$1" | cut -c1-7)"
  mkdir -p "$destination" || return 1
  python_in_venv - "$DATABASE" "$destination/open-dots.sqlite3" <<'PY' || return 1
import sqlite3, sys
source, target = sqlite3.connect(sys.argv[1]), sqlite3.connect(sys.argv[2])
source.backup(target)
target.close()
source.close()
PY
  printf '%s\n' "$destination" > "$UPDATE_DIR/last-backup"
  # Keep the five most recent backups.
  ls -1d "$BACKUPS"/*/ 2>/dev/null | sort -r | tail -n +6 | while IFS= read -r old; do rm -rf "$old"; done
}

# Install and build the checked-out version, keeping the previous build and
# modules aside so going back is instant.
prepare_version() {
  rm -rf "$ROOT/client/.next.previous" "$ROOT/client/node_modules.previous"
  setup_server || return 1
  if [ -f "$ROOT/client/package-lock.json" ] && ! cmp -s "$ROOT/client/package-lock.json" "$ROOT/client/node_modules/.open-dots-lock"; then
    [ -d "$ROOT/client/node_modules" ] && mv "$ROOT/client/node_modules" "$ROOT/client/node_modules.previous"
  fi
  setup_client_modules || return 1
  if client_needs_build; then
    [ -d "$ROOT/client/.next" ] && mv "$ROOT/client/.next" "$ROOT/client/.next.previous"
    build_client || return 1
  fi
}

# Back to a version that worked, with the build and modules it had.
restore_version() {  # commit
  git -C "$ROOT" checkout --quiet --force --detach "$1" || return 1
  if [ -d "$ROOT/client/.next.previous" ]; then
    rm -rf "$ROOT/client/.next" && mv "$ROOT/client/.next.previous" "$ROOT/client/.next"
  fi
  if [ -d "$ROOT/client/node_modules.previous" ]; then
    rm -rf "$ROOT/client/node_modules" && mv "$ROOT/client/node_modules.previous" "$ROOT/client/node_modules"
  fi
  setup_server && setup_client
}

cmd_apply() {
  local from to short
  cd "$ROOT" || return 1
  if ! git rev-parse --git-dir >/dev/null 2>&1; then
    write_status "failed" "" "" "This copy of Open Dots is not a git checkout"
    return 1
  fi
  from=$(git rev-parse HEAD)
  if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    write_status "failed" "$from" "" "There are local changes in $ROOT"
    warn "Not updating: there are local changes in $ROOT."
    return 1
  fi
  if ! to=$(fetch_channel); then
    write_status "failed" "$from" "" "Could not reach GitHub"
    warn "Couldn't get the new version. Is this Mac online?"
    return 1
  fi
  if [ "$from" = "$to" ]; then
    write_status "current" "$from" "$to" "Already up to date"
    say "Open Dots is up to date."
    return 0
  fi
  short=$(printf '%s' "$to" | cut -c1-7)
  say "Updating Open Dots to $short…"
  write_status "updating" "$from" "$to" "Installing"
  mkdir -p "$UPDATE_DIR"
  schema_version "$DATABASE" > "$UPDATE_DIR/schema-before"
  if ! backup_database "$from"; then
    write_status "failed" "$from" "$to" "Could not back up the database"
    return 1
  fi
  if ! git checkout --quiet --detach "$to"; then
    write_status "failed" "$from" "$to" "Could not check out the new version"
    return 1
  fi
  if ! bash -n scripts/start-mac.sh || ! bash -n scripts/update.sh || ! bash -n scripts/lib.sh; then
    restore_version "$from"
    write_status "failed" "$from" "$to" "The new version has a broken start script"
    return 1
  fi
  if ! prepare_version; then
    restore_version "$from"
    write_status "failed" "$from" "$to" "The new version did not install or build"
    warn "The new version didn't build; staying on $(printf '%s' "$from" | cut -c1-7)."
    return 1
  fi
  write_status "installed" "$from" "$to" "Starting the new version"
}

cmd_confirm() {
  [ "$(status_field state)" = installed ] || return 0
  rm -rf "$ROOT/client/.next.previous" "$ROOT/client/node_modules.previous"
  write_status "done" "$(status_field from)" "$(status_field to)" "Updated"
  say "Open Dots updated to $(status_field to | cut -c1-7)."
}

cmd_rollback() {
  local from to before after backup
  [ "$(status_field state)" = installed ] || return 0
  from=$(status_field from)
  to=$(status_field to)
  warn "The new version didn't start; going back to $(printf '%s' "$from" | cut -c1-7)."
  restore_version "$from" || warn "Couldn't fully restore the previous version."
  # Undo the new version's database changes, if it made any.
  before=$(cat "$UPDATE_DIR/schema-before" 2>/dev/null || echo 0)
  after=$(schema_version "$DATABASE")
  backup=$(cat "$UPDATE_DIR/last-backup" 2>/dev/null || true)
  if [ "${after:-0}" -gt "${before:-0}" ] && [ -f "$backup/open-dots.sqlite3" ]; then
    rm -f "$DATABASE-wal" "$DATABASE-shm"
    cp "$backup/open-dots.sqlite3" "$DATABASE"
  fi
  write_status "rolled-back" "$from" "$to" "The new version did not start, so Open Dots went back to the previous one"
}

cmd_check() {
  local head to
  cd "$ROOT" || return 1
  git rev-parse --git-dir >/dev/null 2>&1 || { warn "This copy of Open Dots is not a git checkout."; return 1; }
  head=$(git rev-parse HEAD)
  to=$(fetch_channel) || { warn "Couldn't check for updates. Is this Mac online?"; return 1; }
  if [ "$head" = "$to" ] || git merge-base --is-ancestor "$to" "$head"; then
    say "Open Dots is up to date ($(git log -1 --format='%h, %cd' --date=short))."
    return 0
  fi
  say "New in Open Dots:"
  git log --no-merges --format='  %h  %s' "$head..$to" | head -20
}

cmd_now() {
  local pid
  if pid=$(supervisor_pid); then
    mkdir -p "$UPDATE_DIR" && date -u +%Y-%m-%dT%H:%M:%SZ > "$UPDATE_REQUEST"
    kill -USR1 "$pid" 2>/dev/null || true
    say "Updating. Open Dots restarts in a moment."
    return
  fi
  cmd_apply || return 1
  if [ "$(status_field state)" = installed ]; then
    say "Updated. Start it with: $ROOT/scripts/start-mac.sh"
  fi
}

main() {
  case "${1:-now}" in
    now) cmd_now ;;
    check) cmd_check ;;
    apply) cmd_apply ;;
    confirm) cmd_confirm ;;
    rollback) cmd_rollback ;;
    -h|--help) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//' ;;
    *) warn "Unknown command: $1 (try --help)"; return 2 ;;
  esac
}

# Everything above is read before anything runs, so checking out a new copy
# of this file mid-update can't change what this run does.
main "$@"; exit $?
