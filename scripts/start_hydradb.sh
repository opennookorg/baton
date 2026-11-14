#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: $0 [--background] | stop" >&2
  exit 2
}

HYDRADB_HOME="${BATON_HYDRADB_HOME:-$HOME/Projects/hydradb}"
STATE_DIR="$HYDRADB_HOME/.hydradb"
PID_FILE="$STATE_DIR/node.pid"
LOG_FILE="$STATE_DIR/node.log"
BOLT_HOST=127.0.0.1
BOLT_PORT=7687
READY_TIMEOUT="${BATON_HYDRADB_READY_TIMEOUT:-1800}"

bolt_listening() {
  nc -z "$BOLT_HOST" "$BOLT_PORT" >/dev/null 2>&1
}

listener_pids() {
  lsof -nP -t -iTCP:"$BOLT_PORT" -sTCP:LISTEN 2>/dev/null || true
}

stop_node() {
  local pids=""
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    pids="$(cat "$PID_FILE")"
  fi
  pids="$pids $(listener_pids)"
  pids="$(echo $pids | tr ' ' '\n' | sort -u | tr '\n' ' ')"
  if [[ -z "${pids// /}" ]]; then
    echo "hydradb: not running"
    rm -f "$PID_FILE"
    return 0
  fi
  echo "hydradb: stopping pid(s) $pids"
  kill $pids 2>/dev/null || true
  for _ in $(seq 1 30); do
    bolt_listening || break
    sleep 1
  done
  if bolt_listening; then
    kill -9 $(listener_pids) 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
  echo "hydradb: stopped"
}

background=false
case "${1:-}" in
  "") ;;
  --background) background=true ;;
  stop) stop_node; exit 0 ;;
  *) usage ;;
esac

if [[ ! -f "$HYDRADB_HOME/Cargo.toml" ]]; then
  echo "hydradb: no checkout at $HYDRADB_HOME (set BATON_HYDRADB_HOME)" >&2
  exit 1
fi

if bolt_listening; then
  echo "hydradb: already listening on $BOLT_HOST:$BOLT_PORT (pid $(listener_pids | tr '\n' ' '))"
  exit 0
fi

source "$(dirname "${BASH_SOURCE[0]}")/hydradb_env.sh"

if command -v brew >/dev/null 2>&1; then
  BREW_PREFIX="$(brew --prefix)"
  export BINDGEN_EXTRA_CLANG_ARGS="-I$BREW_PREFIX/include"
  export LIBRARY_PATH="$BREW_PREFIX/lib"
fi

if [[ -x "$HOME/.cargo/bin/cargo" ]]; then
  CARGO="$HOME/.cargo/bin/cargo"
else
  CARGO=cargo
fi

cd "$HYDRADB_HOME"

if [[ "$background" == false ]]; then
  exec "$CARGO" run --release --locked --features server-runtime --bin graph-node
fi

nohup "$CARGO" run --release --locked --features server-runtime --bin graph-node >>"$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
echo "hydradb: started pid $(cat "$PID_FILE"), log $LOG_FILE"

for _ in $(seq 1 "$READY_TIMEOUT"); do
  if bolt_listening; then
    echo "hydradb: listening on $BOLT_HOST:$BOLT_PORT"
    exit 0
  fi
  if ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "hydradb: node exited, see $LOG_FILE" >&2
    tail -n 20 "$LOG_FILE" >&2
    rm -f "$PID_FILE"
    exit 1
  fi
  sleep 1
done
echo "hydradb: not listening after ${READY_TIMEOUT}s, see $LOG_FILE" >&2
exit 1
