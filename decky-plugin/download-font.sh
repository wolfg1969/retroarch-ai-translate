#!/usr/bin/env bash
# Download wqy-zenhei CJK font for bundling with the Decky plugin.
# Run this script before building the plugin package.
#
# The font is ~15 MB and is NOT committed to the repository.
#
# Alternative: install the font system-wide on Steam Deck with:
#   sudo pacman -S wqy-zenhei
# The plugin will auto-detect the system font if installed.

set -euo pipefail

ASSETS_DIR="$(cd "$(dirname "$0")" && pwd)/assets"
FONT_FILE="$ASSETS_DIR/wqy-zenhei.ttc"

if [ -f "$FONT_FILE" ]; then
    echo "Font already bundled: $FONT_FILE ($(du -h "$FONT_FILE" | cut -f1))"
    exit 0
fi

echo "Downloading WQY ZenHei CJK font..."

# Try multiple sources
URLS=(
    "https://mirrors.ustc.edu.cn/debian/pool/main/f/fonts-wqy-zenhei/fonts-wqy-zenhei_0.9.45-6_all.deb"
    "https://mirrors.aliyun.com/debian/pool/main/f/fonts-wqy-zenhei/fonts-wqy-zenhei_0.9.45-6_all.deb"
    "https://deb.debian.org/debian/pool/main/f/fonts-wqy-zenhei/fonts-wqy-zenhei_0.9.45-6_all.deb"
)

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

for URL in "${URLS[@]}"; do
    echo "Trying: $URL"
    if curl -fsSL "$URL" -o "$TMPDIR/font.deb" 2>/dev/null; then
        SIZE=$(wc -c < "$TMPDIR/font.deb")
        if [ "$SIZE" -lt 10000 ]; then
            echo "  Too small ($SIZE bytes), likely a redirect page. Skipping."
            continue
        fi
        echo "  Downloaded $SIZE bytes. Extracting..."
        cd "$TMPDIR"
        ar x font.deb data.tar.xz 2>/dev/null || ar x font.deb data.tar.gz 2>/dev/null || continue
        tar xf data.tar.* 2>/dev/null || continue
        FOUND=$(find . -name "wqy-zenhei.ttc" 2>/dev/null | head -1)
        if [ -n "$FOUND" ]; then
            mkdir -p "$ASSETS_DIR"
            cp "$FOUND" "$FONT_FILE"
            echo "Font bundled successfully: $FONT_FILE ($(du -h "$FONT_FILE" | cut -f1))"
            exit 0
        fi
    fi
done

echo ""
echo "ERROR: Could not download the font automatically."
echo ""
echo "Manual options:"
echo "  1. Install on your Steam Deck:  sudo pacman -S wqy-zenhei"
echo "     (The plugin detects system-installed fonts automatically)"
echo ""
echo "  2. Download wqy-zenhei.ttc manually and place it at:"
echo "     $FONT_FILE"
echo ""
echo "  3. Use any other CJK .ttc font and set cjk_font_path in plugin settings."
exit 1
