#!/usr/bin/env bash
set -euo pipefail

STATE_DIR="${BATON_STATE_DIR:-/tmp/hydradb}"
BOLT_HOST=127.0.0.1
BOLT_PORT="${BATON_BOLT_PORT:-7687}"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${BATON_PYTHON:-python}"
GRAPH_NODE="${BATON_GRAPH_NODE:-graph-node}"

source "$APP_DIR/scripts/hydradb_env.sh"
export GRAPH_BOLT_ADDR="$BOLT_HOST:$BOLT_PORT"
export BATON_HYDRADB_URI="bolt://$BOLT_HOST:$BOLT_PORT"

"$GRAPH_NODE" >"$STATE_DIR/node.log" 2>&1 &
node_pid=$!
for _ in $(seq 1 120); do
  if nc -z "$BOLT_HOST" "$BOLT_PORT" >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$node_pid" 2>/dev/null; then
    echo "hydradb: node exited" >&2
    tail -n 40 "$STATE_DIR/node.log" >&2
    exit 1
  fi
  sleep 1
done
echo "hydradb: listening on $BOLT_HOST:$BOLT_PORT"

cd "$APP_DIR"
"$PYTHON" -m eval.restore_graph --all
exec "$PYTHON" -m uvicorn app.server:app --host 0.0.0.0 --port "${PORT:-7860}"
