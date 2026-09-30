#!/usr/bin/env bash
# The whole life of an install, against a throwaway git origin:
#   install with scripts/install.sh, sign in with a one-time link,
#   update to a new version from the API (as the Update button does),
#   try a broken version and roll back (code and database),
#   pick up a fixed version automatically, then uninstall.
# Uses ports 8000 and 3000. Runs on Linux and macOS.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
ORIGIN="$WORK/origin.git"
SRC="$WORK/src"
export DATA_DIR="$WORK/data"
export OPEN_DOTS_HOME="$WORK/app"
API=http://127.0.0.1:8000/api/v1

log() { printf '[update-flow] %s\n' "$*"; }
fail() { log "FAILED: $*"; [ -f "$WORK/data/logs/open-dots.log" ] && tail -40 "$WORK/data/logs/open-dots.log"; exit 1; }

cleanup() {
  local pid
  pid=$(cat "$DATA_DIR/open-dots.pid" 2>/dev/null || true)
  [ -n "$pid" ] && kill "$pid" 2>/dev/null && sleep 2
  rm -rf "$WORK"
}
trap cleanup EXIT

git_in() { git -C "$1" -c user.name="Update Flow" -c user.email=update-flow@example.com "${@:2}"; }
token() { cat "$DATA_DIR/.auth-token"; }
api() { curl -fsS -m 30 -H "Authorization: Bearer $(token)" "$@"; }
json() { python3 -c "import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1], {}, {'d': d}))" "$1"; }

wait_for() {  # seconds description command...
  local seconds=$1 what=$2 _
  shift 2
  for _ in $(seq 1 "$seconds"); do
    if "$@" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  fail "timed out waiting for: $what"
}

running_commit() { api "$API/system/update" | json "d['current']['commit']"; }
last_state() { api "$API/system/update" | json "(d.get('last') or {}).get('state')"; }
is_running() { [ "$(running_commit 2>/dev/null)" = "$1" ]; }
last_is() { [ "$(last_state 2>/dev/null)" = "$1" ]; }

publish() {  # message
  git_in "$SRC" add -A
  git_in "$SRC" commit --quiet -m "$1" >/dev/null
  git_in "$SRC" push --quiet origin HEAD:main HEAD:stable 2>/dev/null
  git_in "$SRC" rev-parse HEAD
}

# ----- an origin holding this working tree as version 1 ------------------------
log "creating an origin from the working tree"
mkdir -p "$SRC"
(cd "$REPO_DIR" && git ls-files -co --exclude-standard | while IFS= read -r file; do
  [ -e "$file" ] && printf '%s\0' "$file"
done | tar --null -T - -cf -) | tar -xf - -C "$SRC"
git init --quiet -b main "$SRC"
git init --quiet --bare -b main "$ORIGIN"
git_in "$SRC" remote add origin "$ORIGIN"
V1=$(publish "Version 1")

# ----- install -------------------------------------------------------------------
log "installing"
mkdir -p "$DATA_DIR"
# Check quickly for new versions, so the automatic update below doesn't take minutes.
printf 'UPDATE_CHECK_MINUTES=0.1\n' > "$DATA_DIR/open-dots.env"
OPEN_DOTS_REPO="file://$ORIGIN" bash "$SRC/scripts/install.sh" --yes --no-background --no-open \
  || fail "install.sh"
[ -d "$OPEN_DOTS_HOME/.git" ] || fail "no app folder"
is_running "$V1" || fail "not running version 1"
api -X PUT -H 'Content-Type: application/json' -d '{"auto": false}' "$API/system/update" >/dev/null

log "signing in with a one-time link"
url=$(api -X POST "$API/auth/signin-links" | json "d['url']")
code=${url#*signin=}
curl -fsS -c "$WORK/cookies" -H 'Content-Type: application/json' -d "{\"code\": \"$code\"}" "$API/auth/signin" >/dev/null \
  || fail "sign-in link didn't work"
curl -fsS -b "$WORK/cookies" "$API/bots" >/dev/null || fail "no session after the sign-in link"
if curl -fsS -H 'Content-Type: application/json' -d "{\"code\": \"$code\"}" "$API/auth/signin" >/dev/null 2>&1; then
  fail "a sign-in link worked twice"
fi

# ----- a new version, installed from the API (the Update button) -----------------
log "publishing version 2 (changes the web client)"
printf '\n// Version 2 of the update-flow test.\n' >> "$SRC/client/lib/liveChat.js"
V2=$(publish "Version 2")
[ "$(api -X POST "$API/system/update/check" | json "d['available']['commit']")" = "$V2" ] || fail "version 2 not found"
api -X POST "$API/system/update" >/dev/null
wait_for 300 "version 2 to be running" is_running "$V2"
wait_for 30 "the update to be confirmed" last_is "done"
[ "$(cat "$OPEN_DOTS_HOME/client/.next/.open-dots-source")" = "$(git -C "$OPEN_DOTS_HOME" rev-parse HEAD:client)" ] \
  || fail "the web client wasn't rebuilt"
curl -fsS -b "$WORK/cookies" "$API/bots" >/dev/null || fail "the update signed the browser out"
log "version 2 is running and the browser is still signed in"

# ----- a broken version goes back, code and database ------------------------------
log "publishing version 3 (migrates the database, then fails to start)"
schema_before=$(python3 -c "import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute('select max(version) from schema_migrations').fetchone()[0])" "$DATA_DIR/open-dots.sqlite3")
cat >> "$SRC/server/app/services/database.py" <<'PY'

SCHEMA_MIGRATIONS[99] = "CREATE TABLE IF NOT EXISTS update_flow_probe (id INTEGER);"
PY
printf '\nraise RuntimeError("Version 3 is broken on purpose")\n' >> "$SRC/server/app/main.py"
V3=$(publish "Version 3 (broken)")
api -X POST "$API/system/update/check" >/dev/null
api -X POST "$API/system/update" >/dev/null
wait_for 300 "version 3 to be rolled back" last_is rolled-back
is_running "$V2" || fail "not back on version 2"
[ "$(api "$API/system/update" | json "d['last']['to']")" = "$V3" ] || fail "the rollback doesn't name version 3"
schema_after=$(python3 -c "import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute('select max(version) from schema_migrations').fetchone()[0])" "$DATA_DIR/open-dots.sqlite3")
[ "$schema_after" = "$schema_before" ] || fail "database not restored ($schema_after, expected $schema_before)"
[ "$(api -X POST "$API/system/update/check" | json "d['available']['failed_before']")" = True ] \
  || fail "the broken version isn't marked as tried"
log "rolled back to version 2 with the database as it was"

# ----- automatic updates skip the broken version and take the fix -----------------
api -X PUT -H 'Content-Type: application/json' -d '{"auto": true}' "$API/system/update" >/dev/null
sleep 15
is_running "$V2" || fail "retried the broken version by itself"
log "publishing version 4 (the fix); it should install by itself"
git_in "$SRC" revert --no-commit HEAD
V4=$(publish "Version 4")
wait_for 300 "version 4 to be running" is_running "$V4"
wait_for 30 "the update to be confirmed" last_is "done"
log "version 4 installed automatically"

# ----- uninstall -----------------------------------------------------------------
log "uninstalling"
bash "$OPEN_DOTS_HOME/scripts/uninstall.sh" --yes --delete-data || fail "uninstall.sh"
[ ! -e "$OPEN_DOTS_HOME" ] || fail "the app folder is still there"
[ ! -e "$DATA_DIR" ] || fail "the data folder is still there"
if curl -fsS -m 3 "$API/health" >/dev/null 2>&1; then fail "Open Dots is still running"; fi
log "passed"
