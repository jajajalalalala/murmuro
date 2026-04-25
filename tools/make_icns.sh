#!/usr/bin/env bash
# Convert assets/icon.png into assets/icon.icns using macOS's iconutil.
# Generates the standard iconset (16/32/128/256/512 @1x and @2x).
set -euo pipefail

SRC="${1:-assets/icon.png}"
OUT="${2:-assets/icon.icns}"

if [[ ! -f "$SRC" ]]; then
    echo "missing source PNG: $SRC" >&2
    exit 1
fi

if ! command -v iconutil >/dev/null 2>&1; then
    echo "iconutil not found — this script only runs on macOS." >&2
    exit 2
fi

if ! command -v sips >/dev/null 2>&1; then
    echo "sips not found — this script only runs on macOS." >&2
    exit 2
fi

WORK="$(mktemp -d)"
ICONSET="$WORK/icon.iconset"
mkdir -p "$ICONSET"

declare -a SIZES=(16 32 128 256 512)
for s in "${SIZES[@]}"; do
    sips -z "$s" "$s" "$SRC" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
    s2=$((s * 2))
    sips -z "$s2" "$s2" "$SRC" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done

iconutil -c icns "$ICONSET" -o "$OUT"
rm -rf "$WORK"
echo "wrote $OUT"
