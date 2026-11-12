#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="${1:-$ROOT/dist}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$OUT" "$TMP/DEBIAN" "$TMP/usr/share/tihulu-tv-center" \
  "$TMP/usr/bin" "$TMP/usr/share/applications"
cp -a "$ROOT/tv_center" "$ROOT/textcenter" "$ROOT/kaffeine_next" "$TMP/usr/share/tihulu-tv-center/"
find "$TMP/usr/share/tihulu-tv-center" -type d -name __pycache__ -prune -exec rm -rf '{}' +
cat > "$TMP/DEBIAN/control" <<'CONTROL'
Package: tihulu-tv-center
Version: 0.1.0~dev1
Section: video
Priority: optional
Architecture: all
Maintainer: Tihulu Project <noreply@github.com>
Depends: python3 (>= 3.11), python3-pyqt5, dvb-tools, mpv, ffmpeg, psmisc
Description: TIHULU television AI caption and translation tools
 Provides offline Whisper, Argos and Teletext tools for native Kaffeine
 television. A standalone experimental player remains for debugging only.
CONTROL
cat > "$TMP/usr/bin/tihulu-tv-center" <<'LAUNCH'
#!/bin/sh
cd /usr/share/tihulu-tv-center || exit 1
if [ -n "${WAYLAND_DISPLAY:-}" ]; then
  export QT_QPA_PLATFORM=xcb
fi
if [ "${1:-}" = "remove-runtime" ]; then
  exec /usr/bin/python3 -m tv_center.runtime remove
fi
PYTHON="/usr/bin/python3"
AI_ENV="$HOME/.local/share/tihulu-tv-center/ai-runtime"
if [ -f "$AI_ENV/.tihulu-owned-ai-runtime" ] && [ -x "$AI_ENV/bin/python3" ]; then
  PYTHON="$AI_ENV/bin/python3"
fi
exec "$PYTHON" -m tv_center "$@"
LAUNCH
chmod 755 "$TMP/usr/bin/tihulu-tv-center"
# With the Kaffeine core active, publish only its native TV launcher.
# No second TV player appears in the desktop app list.
if [[ "${TIHULU_KAFFEINE_PRIMARY:-0}" == "1" ]]; then
  cat > "$TMP/usr/share/applications/tihulu-tv-center.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=TIHULU AI Companion (Kaffeine)
Comment=Optional Whisper and Translator tools for native Kaffeine
Exec=tihulu-tv-center ai-market
Icon=kaffeine
NoDisplay=true
Terminal=false
Categories=AudioVideo;Video;TV;
DESKTOP
else
  cat > "$TMP/usr/share/applications/tihulu-tv-center.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=TIHULU TV Center (legacy preview)
Comment=Standalone experimental DVB client, not Kaffeine
Exec=tihulu-tv-center legacy-player
Icon=video-display
Terminal=false
Categories=AudioVideo;Video;TV;
DESKTOP
fi
dpkg-deb --build --root-owner-group "$TMP" "$OUT/tihulu-tv-center_0.1.0~dev1_all.deb"
echo "Built package at $OUT/tihulu-tv-center_0.1.0~dev1_all.deb"
