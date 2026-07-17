#!/usr/bin/env bash
# Build the Decky plugin into a clean distributable ZIP.
#
# Usage:
#   pnpm run package          # build + create .zip
#   bash package.sh           # same, directly
#
# Output:
#   retroarch-ai-translation.zip   ← install via Decky debug mode
#
# Decky Debug Mode Install:
#   1. Copy the zip to your Steam Deck
#   2. In Decky settings → Developer → Install Plugin from ZIP file
#   3. Select the zip, confirm, then restart plugin_loader
#
# Or manually extract to:
#   ~/homebrew/plugins/retroarch-ai-translation/
#   Then:  systemctl restart plugin_loader.service

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PLUGIN_NAME="retroarch-ai-translation"
BUILD_DIR="dist-pkg"
STAGING="$BUILD_DIR/$PLUGIN_NAME"
ZIP_FILE="$PLUGIN_NAME.zip"

echo "========================================="
echo " Packaging Decky Plugin: $PLUGIN_NAME"
echo "========================================="

# ── Step 1: Sync Python modules ──────────────────────────────
echo ""
echo "[1/5] Syncing Python modules from ../src/"
bash sync-py-modules.sh

# ── Step 2: Vendor Python dependencies ─────────────────────────
echo ""
echo "[2/5] Vendoring Python deps (manylinux_x86_64)"
# Install Pillow as a pre-built wheel compatible with Steam Deck (x86_64 Linux)
pip install \
  --platform manylinux2014_x86_64 \
  --python-version 311 \
  --only-binary=:all: \
  --target="$SCRIPT_DIR/py_modules" \
  --upgrade \
  Pillow>=10.0.0 2>&1
echo "  ✓ Pillow vendored"

# ── Step 3: Build frontend ────────────────────────────────────
echo ""
echo "[3/5] Building frontend (rollup)"
pnpm run build

# ── Step 4: Assemble staging directory ────────────────────────
echo ""
echo "[4/5] Assembling $STAGING"
rm -rf "$STAGING" "$ZIP_FILE"
mkdir -p "$STAGING"

# Required Decky files
cp plugin.json     "$STAGING/"
cp package.json    "$STAGING/"
cp main.py         "$STAGING/"
cp requirements.txt "$STAGING/" 2>/dev/null || true

# Frontend bundle (required)
mkdir -p "$STAGING/dist"
cp dist/index.js   "$STAGING/dist/"

# Vendored Python modules
cp -r py_modules   "$STAGING/"

# Bundled assets (font + defaults)
mkdir -p "$STAGING/assets" "$STAGING/defaults"
cp assets/icon.png        "$STAGING/assets/"  2>/dev/null || true
cp assets/wqy-zenhei.ttc  "$STAGING/assets/"  2>/dev/null || true
if [ -f assets/wqy-zenhei.ttc ]; then
    FONT_SIZE=$(du -h assets/wqy-zenhei.ttc | cut -f1)
    echo "  ✓ CJK font bundled ($FONT_SIZE)"
else
    echo "  ⚠ CJK font NOT bundled — overlay text may fail"
    echo "    Run: bash download-font.sh"
fi
# Game config — synced from ../templates/ (canonical source)
cp ../templates/game_config.yaml "$STAGING/defaults/" 2>/dev/null || true

# Clean up pycache
find "$STAGING" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find "$STAGING" -type f -name .DS_Store -delete 2>/dev/null || true

echo ""
echo "  Staging contents:"
find "$STAGING" -type f | sed "s|$STAGING/|    |" | sort

# ── Step 4: Create ZIP ───────────────────────────────────────
echo ""
echo "[5/5] Creating $ZIP_FILE"
rm -f "$ZIP_FILE"
cd "$BUILD_DIR"
zip -r "../$ZIP_FILE" "$PLUGIN_NAME" -x "*.pyc" -x "__pycache__/*" -x ".DS_Store"
cd "$SCRIPT_DIR"

ZIP_SIZE=$(du -h "$ZIP_FILE" | cut -f1)
echo ""
echo "========================================="
echo " ✅  $ZIP_FILE  ($ZIP_SIZE)"
echo "========================================="
echo ""
echo "Install on Steam Deck (debug mode):"
echo "  Decky → Settings → Developer → Install Plugin from ZIP"
echo "  Then:  sudo systemctl restart plugin_loader"
echo ""
echo "Or manually:"
echo "  unzip $ZIP_FILE -d ~/homebrew/plugins/"
echo "  sudo systemctl restart plugin_loader"
