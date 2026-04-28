#!/usr/bin/env bash
# Restore server.ts from .bak created by apply.py
set -euo pipefail
if [ $# -ne 1 ]; then
  echo "usage: $0 /path/to/telegram/server.ts" >&2
  exit 1
fi
target="$1"
if [ ! -f "$target.bak" ]; then
  echo "error: $target.bak not found" >&2
  exit 1
fi
cp "$target.bak" "$target"
echo "restored: $target"
