#!/usr/bin/env bash
# Sync Python source modules from ../src/ → py_modules/retroarch_ai/
#
# The canonical source lives in ../src/ (shared with standalone mode).
# This script copies the .py files into the Decky plugin's vendored
# package directory so the plugin is self-contained for distribution.
#
# Run this before `pnpm run build` or `pnpm run package`.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC_DIR="$SCRIPT_DIR/../src"
DEST_DIR="$SCRIPT_DIR/py_modules/retroarch_ai"

if [ ! -d "$SRC_DIR" ]; then
    echo "ERROR: source directory not found: $SRC_DIR" >&2
    exit 1
fi

echo "Syncing Python modules: $SRC_DIR → $DEST_DIR"
mkdir -p "$DEST_DIR"

# Copy all .py files from src/ to py_modules/retroarch_ai/
# Skip __init__.py (decky plugin has its own)
copied=0
for src_file in "$SRC_DIR"/*.py; do
    name=$(basename "$src_file")
    if [ "$name" = "__init__.py" ]; then
        continue  # keep decky-specific __init__.py
    fi
    cp "$src_file" "$DEST_DIR/$name"
    echo "  $name"
    copied=$((copied + 1))
done

echo "Synced $copied modules."
