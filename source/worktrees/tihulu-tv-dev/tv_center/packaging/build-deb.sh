#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="${1:-$ROOT/dist}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$OUT" "$TMP/DEBIAN" "$TMP/usr/share/tihulu-tv-center" \
  "$TMP/usr/bin" "$TMP/usr/share/applications"
cp -a "$ROOT/tv_center" "$ROOT/textcenter" "$TMP/usr/share/tihulu-tv-center/"
find "$TMP/usr/share/tihulu-tv-center" -type d -name __pycache__ -prune -exec rm -rf '{}' +
cat > "$TMP/DEBIAN/control" <<'CONTROL'
Package: tihulu-tv-center
Version: 0.1.0~dev1
Section: video
Priority: optional
Architecture: all
Maintainer: Tihulu Project <noreply@github.com>
Depends: python3 (>= 3.11), python3-pyqt5, dvb-tools, mpv, ffmpeg, psmisc
Description: Native DVB television, Teletext and optional offline subtitles
 Experimental Linux TV client for compatible DVB-T2 adapters. Model packs
 and whisper.cpp are optional owner-installed dependencies.
CONTROL
cat > "$TMP/usr/bin/tihulu-tv-center" <<'LAUNCH'
#!/bin/sh
cd /usr/share/tihulu-tv-center || exit 1
if [ -n "${WAYLAND_DISPLAY:-}" ]; then
  export QT_QPA_PLATFORM=xcb
fi
exec /usr/bin/python3 -m tv_center "$@"
LAUNCH
chmod 755 "$TMP/usr/bin/tihulu-tv-center"
cat > "$TMP/usr/share/applications/tihulu-tv-center.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=TIHULU TV Center
Comment=Native DVB TV, subtitles and interactive Teletext
Exec=tihulu-tv-center
Icon=video-display
Terminal=false
Categories=AudioVideo;Video;TV;
DESKTOP
dpkg-deb --build --root-owner-group "$TMP" "$OUT/tihulu-tv-center_0.1.0~dev1_all.deb"
echo "Built package at $OUT/tihulu-tv-center_0.1.0~dev1_all.deb"
