#!/usr/bin/env bash
mkdir -p "$STATE_DIR/store" "$STATE_DIR/cache"
if [[ ! -f "$STATE_DIR/auth-token" ]]; then
  printf '%s\n' "${BATON_HYDRADB_TOKEN:-local-development-token-32-bytes}" > "$STATE_DIR/auth-token"
fi
export CLOUD_PROVIDER=local
export LOCAL_PATH="$STATE_DIR/store"
export GRAPH_NAMESPACE=default
export GRAPH_ID=default
export GRAPH_CELL_ID=cell-0
export GRAPH_CELLS=cell-0
export GRAPH_NODE_ID=node-0
export GRAPH_BOLT_NODE_ADDRESSES="node-0=$BOLT_HOST:$BOLT_PORT"
export GRAPH_ADVERTISED_BOLT_ADDR="$BOLT_HOST:$BOLT_PORT"
export GRAPH_DATA_CACHE_DIR="$STATE_DIR/cache"
export GRAPH_AUTH_TOKEN_FILE="$STATE_DIR/auth-token"
export GRAPH_ALLOW_PLAINTEXT=true
export RUST_MIN_STACK=33554432
