#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
# Build a portable TIHULU Media Center AppDir/AppImage.
#
# The AI model market is intentionally not bundled. The app starts without AI;
# users install optional local models from the in-app market or reuse installed
# models through TIHULU_ASSET_HOME.
set -Eeuo pipefail
umask 022

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
SOURCE="$ROOT/source/installed-package"
UPSTREAM_URL="${TIHULU_KAFFEINE_UPSTREAM:-https://github.com/KDE/kaffeine.git}"
UPSTREAM_TAG="${TIHULU_KAFFEINE_TAG:-v2.0.19}"
UPSTREAM_REV="e7ea15b86dafed3b20b151cbcb080578ab8e2d5c"
OUTPUT="$PWD/tihulu-media-center.AppImage"
BINARY=""
UPSTREAM=""
BUNDLE_LIBS=0

usage() {
  cat <<'HELP'
Usage: packaging/appimage/build-appimage.sh [options]

Options:
  --binary PATH     Use an already built native kaffeine executable
  --upstream PATH   Existing pinned Kaffeine source tree
  --output PATH     Output .AppImage or .AppDir.tar path
  --bundle-libs     Copy non-base shared libraries into the AppDir
  --help, -h        Show this help

Environment:
  TIHULU_KAFFEINE_UPSTREAM   Default https://github.com/KDE/kaffeine.git
  TIHULU_KAFFEINE_TAG        Default v2.0.19
HELP
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --binary) BINARY="$2"; shift 2 ;;
    --upstream) UPSTREAM="$2"; shift 2 ;;
    --output) OUTPUT="$2"; shift 2 ;;
    --bundle-libs) BUNDLE_LIBS=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) printf 'ERROR: unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -d "$SOURCE/kaffeine_next" && -d "$SOURCE/tv_center" && -d "$SOURCE/textcenter" ]] ||
  { echo "ERROR: source/installed-package is incomplete" >&2; exit 1; }

OUT_ABS="$(cd -- "$(dirname -- "$OUTPUT")" && pwd -P)/$(basename -- "$OUTPUT")"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/tihulu-appimage.XXXXXX")"
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

APPDIR="$WORK/AppDir"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/tihulu-tv-center" \
         "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/scalable/apps"

if [[ -n "$BINARY" ]]; then
  [[ -x "$BINARY" ]] || { echo "ERROR: --binary is not executable" >&2; exit 1; }
  install -m 0755 "$BINARY" "$APPDIR/usr/bin/tihulu-media-center"
else
  [[ -n "$UPSTREAM" ]] || UPSTREAM="$WORK/kaffeine-upstream"
  if [[ ! -d "$UPSTREAM" ]]; then
    git clone --depth 1 --branch "$UPSTREAM_TAG" "$UPSTREAM_URL" "$UPSTREAM"
  fi
  ACTUAL_REV="$(git -C "$UPSTREAM" rev-parse HEAD)"
  [[ "$ACTUAL_REV" == "$UPSTREAM_REV" ]] ||
    { echo "ERROR: pinned Kaffeine revision mismatch: $ACTUAL_REV" >&2; exit 1; }
  python3 "$SOURCE/kaffeine_next/patch_upstream.py" "$UPSTREAM" >/dev/null
  cmake -S "$UPSTREAM" -B "$WORK/build" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF \
    -DCMAKE_INSTALL_PREFIX="$APPDIR/usr" >/dev/null
  cmake --build "$WORK/build" --parallel "$(nproc)" >/dev/null
  cmake --install "$WORK/build" >/dev/null
  [[ -x "$APPDIR/usr/bin/kaffeine" ]] ||
    { echo "ERROR: native build did not produce kaffeine executable" >&2; exit 1; }
  install -m 0755 "$APPDIR/usr/bin/kaffeine" "$APPDIR/usr/bin/tihulu-media-center"
fi

cp -a "$SOURCE/kaffeine_next" "$SOURCE/tv_center" "$SOURCE/textcenter" \
      "$APPDIR/usr/share/tihulu-tv-center/"
find "$APPDIR/usr/share/tihulu-tv-center" -name '__pycache__' -type d -prune -exec rm -rf {} +

cat > "$APPDIR/usr/bin/tihulu-tv-center" <<'SHIM'
#!/bin/sh
set -eu
HERE="$(cd -- "$(dirname -- "$0")/../.." && pwd -P)"
export PYTHONPATH="$HERE/usr/share/tihulu-tv-center${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python3 -m tv_center "$@"
SHIM
chmod 0755 "$APPDIR/usr/bin/tihulu-tv-center"

cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
# AppImage entry point. AI services are optional and never block startup.
set -eu
HERE="$(cd -- "$(dirname -- "$0")" && pwd -P)"
export PATH="$HERE/usr/bin:$PATH"
export PYTHONPATH="$HERE/usr/share/tihulu-tv-center${PYTHONPATH:+:$PYTHONPATH}"
export TIHULU_ASSET_HOME="${TIHULU_ASSET_HOME:-$HOME}"
if [ -n "${WAYLAND_DISPLAY:-}" ]; then
  QT_QPA_PLATFORM=xcb
  export QT_QPA_PLATFORM
fi
if [ -d "$HERE/usr/lib" ]; then
  LD_LIBRARY_PATH="$HERE/usr/lib:${LD_LIBRARY_PATH:-}"
  export LD_LIBRARY_PATH
fi
if [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ] && command -v dbus-run-session >/dev/null 2>&1; then
  exec dbus-run-session -- "$HERE/usr/bin/tihulu-media-center" "$@"
fi
exec "$HERE/usr/bin/tihulu-media-center" "$@"
APPRUN
chmod 0755 "$APPDIR/AppRun"

cat > "$APPDIR/usr/share/applications/tihulu-media-center.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=TIHULU Media Center
GenericName=TV, Radio, Media and Offline AI
Comment=TIHULU Media Center: TV, DAB+ radio, local media and optional offline AI
Exec=tihulu-media-center %F
Icon=tihulu-media-center
Terminal=false
Categories=AudioVideo;Video;Player;TV;
MimeType=video/mp4;video/x-matroska;audio/mpeg;audio/flac;video/mpeg;video/mp2t;
StartupNotify=true
DESKTOP

install -m 0644 "$SOURCE/kaffeine_next/assets/tihulu-media-center.svg" \
  "$APPDIR/usr/share/icons/hicolor/scalable/apps/tihulu-media-center.svg"

# appimagetool looks for the desktop entry and the icon in the AppDir ROOT.
install -m 0644 "$APPDIR/usr/share/applications/tihulu-media-center.desktop" \
  "$APPDIR/tihulu-media-center.desktop"
install -m 0644 "$SOURCE/kaffeine_next/assets/tihulu-media-center.svg" \
  "$APPDIR/.DirIcon"

if [[ "$BUNDLE_LIBS" -eq 1 ]]; then
  mkdir -p "$APPDIR/usr/lib"
  # Copy direct and transitive libraries, except the base glibc runtime.
  ( ldd "$APPDIR/usr/bin/tihulu-media-center" || true ) | awk '
    /=>/ {print $3}
    /^\// {print $1}
  ' | sort -u | while read -r lib; do
    [[ -n "$lib" && -f "$lib" ]] || continue
    base="$(basename -- "$lib")"
    case "$base" in
      libc.so|libc.so.*|libm.so|libm.so.*|libdl.so|libdl.so.*|librt.so|librt.so.*|libpthread.so|libpthread.so.*|libgcc_s.so|libgcc_s.so.*|ld-linux-x86-64.so|ld-linux-x86-64.so.*) continue ;;
    esac
    install -m 0755 "$lib" "$APPDIR/usr/lib/$base" 2>/dev/null || true
  done
fi

if command -v appimagetool >/dev/null 2>&1; then
  appimagetool "$APPDIR" "$OUT_ABS"
  echo "Created AppImage: $OUT_ABS"
else
  case "$OUT_ABS" in
    *.AppImage) OUT_TAR="${OUT_ABS%.AppImage}.AppDir.tar" ;;
    *.AppDir.tar) OUT_TAR="$OUT_ABS" ;;
    *) OUT_TAR="$OUT_ABS.AppDir.tar" ;;
  esac
  rm -f "$OUT_TAR"
  tar -C "$WORK" -czf "$OUT_TAR" AppDir
  echo "appimagetool not found; created portable AppDir archive: $OUT_TAR"
  echo "Install appimagetool and rerun with --output to produce a single-file AppImage."
fi
