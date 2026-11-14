#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <hf-user>/<space-name>" >&2
  exit 2
fi
SPACE="$1"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

git -C "$ROOT" archive HEAD | tar -x -C "$STAGE"
rm -rf "$STAGE/docs" "$STAGE/tests"
{
  printf -- '---\ntitle: Baton\nemoji: 🪄\ncolorFrom: blue\ncolorTo: gray\nsdk: docker\napp_port: 7860\npinned: false\n---\n\n'
  cat "$ROOT/README.md"
} > "$STAGE/README.md"

uvx --from huggingface_hub hf repos create "$SPACE" --repo-type space --space-sdk docker --exist-ok
uvx --from huggingface_hub hf upload "$SPACE" "$STAGE" . --repo-type space --commit-message "Deploy $(git -C "$ROOT" rev-parse --short HEAD)"
echo "https://huggingface.co/spaces/$SPACE"
