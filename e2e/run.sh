#!/usr/bin/env bash
# Browser end-to-end tests: the iPhone app, the Mac web client and the two
# together, against a real Open Dots server and a stand-in model.
#
#   e2e/run.sh              all suites (phone, both, resilience)
#   e2e/run.sh phone both   some of them
#
# Needs the server's environment (server/.venv), the web client built
# (client/.next), and `npm ci` in e2e/. Uses ports 8000, 3000 and 9100.
# Screenshots land in e2e/shots/ (SHOTS=… to change).
set -euo pipefail

E2E="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$E2E")"
PYTHON="${E2E_PYTHON:-$ROOT/server/.venv/bin/python}"
WORK="$(mktemp -d)"
PIDS=""
export E2E_PYTHON="$PYTHON" E2E_TOKEN="${E2E_TOKEN:-e2e-owner-token}"
# This project's cloud containers ship a Chromium; elsewhere Playwright's own is used.
if [ -z "${CHROMIUM_PATH:-}" ] && [ -x /opt/pw-browsers/chromium ]; then export CHROMIUM_PATH=/opt/pw-browsers/chromium; fi

stop() {
  # shellcheck disable=SC2086
  [ -z "$PIDS" ] || kill $PIDS 2>/dev/null || true
  wait 2>/dev/null || true
  PIDS=""
}
trap 'stop; rm -rf "$WORK"' EXIT

wait_for() {  # url
  local _
  for _ in $(seq 1 120); do
    curl -fsS -m 5 -o /dev/null "$1" 2>/dev/null && return 0
    sleep 0.5
  done
  echo "Timed out waiting for $1" >&2
  return 1
}

suites=("$@")
[ ${#suites[@]} -gt 0 ] || suites=(phone both resilience)

(cd "$E2E" && FAKE_DELAY="${FAKE_DELAY:-0.1}" exec "$PYTHON" -m uvicorn fake_model:app --port 9100 --log-level warning) &
PIDS="$!"

start_shared() {
  (cd "$ROOT/server" && DATA_DIR="$WORK/data" APP_AUTH_TOKEN="$E2E_TOKEN" WORKSPACE_ROOT="$ROOT" \
    exec "$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level warning) &
  PIDS="$PIDS $!"
  (cd "$ROOT/client" && exec ./node_modules/.bin/next start -H 127.0.0.1 -p 3000) >/dev/null &
  PIDS="$PIDS $!"
  wait_for http://127.0.0.1:8000/api/v1/health
  wait_for http://127.0.0.1:3000/
}

shared_running=0
for name in "${suites[@]}"; do
  if [ "$name" = resilience ]; then
    # It starts and stops its own server.
    if [ "$shared_running" = 1 ]; then
      stop
      (cd "$E2E" && FAKE_DELAY="${FAKE_DELAY:-0.1}" exec "$PYTHON" -m uvicorn fake_model:app --port 9100 --log-level warning) &
      PIDS="$!"
      shared_running=0
    fi
  elif [ "$shared_running" = 0 ]; then
    start_shared
    shared_running=1
  fi
  wait_for http://127.0.0.1:9100/docs
  echo "== $name"
  (cd "$E2E" && node "$name.mjs")
done
echo "All end-to-end suites passed."
