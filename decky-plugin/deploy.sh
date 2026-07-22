#!/usr/bin/env bash
# Build and deploy directly to Steam Deck's Decky plugin directory.
#
# Run this ON the Steam Deck (or via SSH) during development.
#
# Usage:
#   bash deploy.sh              # build + copy to homebrew + restart
#   bash deploy.sh --no-restart # build + copy only

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PLUGIN_NAME="retroarch-ai-translate"
DECKY_PLUGINS="${DECKY_PLUGINS:-$HOME/homebrew/plugins}"
TARGET="$DECKY_PLUGINS/$PLUGIN_NAME"
RESTART=true

if [ "${1:-}" = "--no-restart" ]; then
    RESTART=false
fi

echo "========================================="
echo " Deploying to $TARGET"
echo "========================================="

# ── Build ────────────────────────────────────────────────────
echo "[1/4] Syncing + deps + building"
bash sync-py-modules.sh
pip install --platform manylinux2014_x86_64 --python-version 311 --only-binary=:all: --target="$SCRIPT_DIR/py_modules" --upgrade "Pillow>=10.0.0" 2>&1
pnpm run build

# ── Copy ─────────────────────────────────────────────────────
echo ""
echo "[2/4] Copying to $TARGET"
mkdir -p "$TARGET"

# Required files
cp plugin.json      "$TARGET/"
cp package.json     "$TARGET/"
cp main.py          "$TARGET/"
cp requirements.txt "$TARGET/" 2>/dev/null || true

# Frontend
mkdir -p "$TARGET/dist"
cp dist/index.js    "$TARGET/dist/"

# Python modules (sync pycache first)
find "$TARGET/py_modules" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
rsync -a --delete py_modules/ "$TARGET/py_modules/"

# Assets
mkdir -p "$TARGET/assets" "$TARGET/defaults"
cp assets/icon.png        "$TARGET/assets/"  2>/dev/null || true
cp assets/wqy-zenhei.ttc  "$TARGET/assets/"  2>/dev/null || true
# Game config — synced from ../templates/ (canonical source)
cp ../templates/game_config.yaml "$TARGET/defaults/" 2>/dev/null || true

# Clean
find "$TARGET" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find "$TARGET" -type f -name .DS_Store -delete 2>/dev/null || true

echo "  ✓ Plugin files copied"

# ── Restart ──────────────────────────────────────────────────
if $RESTART; then
    echo ""
    echo "[3/4] Restarting plugin_loader"
    sudo systemctl restart plugin_loader
    echo "  ✓ Decky plugin loader restarted"
    echo ""
    echo "Check QAM menu → RetroArch AI Translate"
else
    echo ""
    echo "(skipped restart — --no-restart flag was set)"
    echo "To apply:  sudo systemctl restart plugin_loader"
fi
