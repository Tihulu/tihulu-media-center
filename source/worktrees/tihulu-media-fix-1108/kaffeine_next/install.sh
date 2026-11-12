#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
# Install TIHULU's Kaffeine-based TV application alongside system Kaffeine.
set -Eeuo pipefail
if [[ "$(uname -s)" != Linux || ! -f /etc/os-release ]]; then
  echo "Native Kaffeine DVB requires Linux." >&2; exit 1
fi
. /etc/os-release
case " $ID $ID_LIKE " in
  *debian*|*ubuntu*|*pop*|*raspbian*) ;;
  *) echo "Requires Debian/Ubuntu/Pop!_OS/Raspberry Pi OS with APT." >&2; exit 1 ;;
esac
if (( EUID == 0 )); then
  echo "Run as your desktop user. Only APT system dependencies use sudo." >&2
  exit 1
fi
# Explicit opt out for users who only want Kaffeine's DVB reception.
MODE=default
WITH_DAB=0
WITH_ANALOG=0
for argument in "$@"; do
  case "$argument" in
    --no-ai) MODE=--no-ai ;;
    --with-dab) WITH_DAB=1 ;;
    --with-analog) WITH_ANALOG=1 ;;
    *) echo "Usage: bash install.sh [--no-ai] [--with-dab] [--with-analog]" >&2; exit 2 ;;
  esac
done
echo "Building a separate GPL-compatible Kaffeine v2.0.19 fork."
echo "This preserves system Kaffeine, channel lists, other SDR programs and AI models."
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
 git ca-certificates cmake g++ make pkg-config extra-cmake-modules \
 qtbase5-dev libqt5x11extras5-dev libkf5coreaddons-dev \
 libkf5dbusaddons-dev libkf5i18n-dev libkf5kio-dev \
 libkf5solid-dev libkf5widgetsaddons-dev libkf5windowsystem-dev \
 libkf5xmlgui-dev libvlc-dev libx11-dev libxss-dev \
 libdvbv5-dev libudev-dev libqt5sql5-sqlite vlc \
 python3 python3-venv python3-pip python3-pyqt5 ffmpeg \
 dvb-tools psmisc
if (( WITH_ANALOG == 1 )); then
  echo "Installing optional local RTL-SDR analogue tools and ALSA PCM output."
  sudo apt-get install -y --no-install-recommends rtl-sdr alsa-utils
fi

APPROOT="$HOME/.local/share/tihulu-kaffeine"
SOURCE="$APPROOT/upstream-v2.0.19"
PREFIX="$HOME/.local/opt/tihulu-kaffeine"
BUILD="$APPROOT/build-system-qt5"
LOGDIR="$APPROOT/logs"
mkdir -p "$APPROOT" "$LOGDIR" "$HOME/.local/bin" "$HOME/.local/share/applications"
# Migrate existing tuner/channel definitions ONCE into a distinct TIHULU
# data directory. Never alter the system Kaffeine instance's own files.
LEGACY_DATA="$HOME/.local/share/kaffeine"
TIHULU_DATA="$HOME/.local/share/tihulu-media-center"
if [[ -d "$LEGACY_DATA" && ! -e "$TIHULU_DATA" && ! -L "$LEGACY_DATA" ]]; then
  mkdir -p "$TIHULU_DATA"
  # Copy settings/channels, not user-owned recordings/videos or unknown links.
  find "$LEGACY_DATA" -maxdepth 1 -type f \
    \( -name 'config.dvb' -o -name '*.db' -o -name '*.sqlite' \) \
    -exec cp -n -- {} "$TIHULU_DATA/" \;
  echo "Imported existing Kaffeine channel database/config as independent TIHULU copies."
fi
mkdir -p "$HOME/.config"
if [[ -f "$HOME/.config/kaffeinerc" &&
      ! -e "$HOME/.config/tihulu-media-centerrc" ]]; then
  cp -n -- "$HOME/.config/kaffeinerc" "$HOME/.config/tihulu-media-centerrc"
fi

# A running Conda/Miniconda "base" shell can inject another Qt5 at link time.
# CMake's path search, pkg-config and the ELF linker must all use the same
# distro Qt5 / KF5 libraries. A clean environment also bypasses stale
# LD_LIBRARY_PATH, CMAKE_PREFIX_PATH and QT_PLUGIN_PATH settings.
SYSTEM_BUILD_ENV=(env -i "HOME=$HOME" "USER=$(id -un)"
  "PATH=/usr/bin:/bin:/usr/sbin:/sbin" "LANG=C.UTF-8")
if [[ -n "${CONDA_PREFIX:-}" || -n "${LD_LIBRARY_PATH:-}" ||
      -n "${CMAKE_PREFIX_PATH:-}" || -n "${QT_PLUGIN_PATH:-}" ]]; then
  echo "Conda/custom Qt environment detected; build will use only system Qt5."
fi

qt_link_diagnostics() {
  echo "=== Qt5 link diagnostics (read-only) ===" >&2
  dpkg-query -W -f='${binary:Package} ${Version}\n' \
    libqt5core5a libqt5gui5 libqt5waylandclient5 qtbase5-dev 2>/dev/null || true
  local qtlib
  qtlib="$(/sbin/ldconfig -p 2>/dev/null | awk '$1=="libQt5WaylandClient.so.5" {print $NF; exit}')"
  if [[ -n "$qtlib" ]]; then
    echo "Checking $qtlib against distro Qt5Gui:" >&2
    "${SYSTEM_BUILD_ENV[@]}" /usr/bin/ldd -r "$qtlib" 2>&1 |
      grep -E 'undefined symbol|not found' | head -30 || true
  fi
  echo "If symbols remain unresolved, system Qt5Gui and Qt5WaylandClient" >&2
  echo "may come from incompatible repositories or installed versions." >&2
  echo "Check apt-cache policy libqt5gui5 libqt5waylandclient5." >&2
}
temp="$(mktemp -d)"
BUILDSRC=""
cleanup() {
  if [[ -n "$BUILDSRC" && -e "$BUILDSRC/.git" && -d "$SOURCE/.git" ]]; then
    git -C "$SOURCE" worktree remove --force "$BUILDSRC" >/dev/null 2>&1 || true
  fi
  rm -rf "$temp"
}
trap cleanup EXIT

# Read the matching feature branch during this standalone preview.
# Override only when installing a release from another compatible branch.
TIHULU_SOURCE_BRANCH="${TIHULU_SOURCE_BRANCH:-fix/tihulu-media-radio-dvb-2026-11-08}"
git clone --depth 1 --single-branch --branch "$TIHULU_SOURCE_BRANCH" \
  https://github.com/Tihulu/TIHULU-TEXT-CENTER.git "$temp/tihulu"
if [[ ! -d "$SOURCE/.git" ]]; then
  git clone --depth 1 --branch v2.0.19 \
    https://github.com/KDE/kaffeine.git "$SOURCE"
fi
UPSTREAM_SHA=e7ea15b86dafed3b20b151cbcb080578ab8e2d5c
CURRENT_SHA="$(git -C "$SOURCE" rev-parse HEAD)"
if [[ "$CURRENT_SHA" != "$UPSTREAM_SHA" ]]; then
  echo "Unexpected upstream revision: $CURRENT_SHA (expected $UPSTREAM_SHA)" >&2
  exit 1
fi
# Never patch a previously modified Kaffeine source tree in-place.
# Users may already have the older patch, and a second patch could
# duplicate scan menus or produce a partially working build.
# Detached worktrees provide a fresh, reproducible upstream checkout
# while preserving local edits and existing user configuration.
BUILDSRC="$temp/kaffeine-source"
git -C "$SOURCE" worktree add --detach "$BUILDSRC" "$UPSTREAM_SHA"
python3 "$temp/tihulu/kaffeine_next/patch_upstream.py" "$BUILDSRC"
# Refuse to ship Kaffeine 2.0.19 with the known channel-import crash
# (KDE #503740 / Debian #1110405). The wrong -1 to std::prev(end)
# reads past the QMap end while several scanned channels are inserted.
SQL_HEADER="$BUILDSRC/src/sqlinterface.h"
if grep -Fq 'std::prev(container.constEnd(), -1)' "$SQL_HEADER" ||
   ! grep -Fq 'std::prev(container.constEnd())' "$SQL_HEADER"; then
  echo "FATAL: DVB scan channel-import SQL iterator fix missing." >&2
  exit 1
fi
echo "Verified Kaffeine DVB channel-import SQL iterator fix (no past-end iterator)."
git -C "$BUILDSRC" diff --check
# Keep the user-approved, loopback-only welle.io backend installer on disk
# instead of trying to run an untrusted internet pipe from the native GUI.
cp "$temp/tihulu/kaffeine_next/install_welle.sh" "$APPROOT/install_welle.sh"
chmod 755 "$APPROOT/install_welle.sh"
# Read-only frontend ownership check, accessible in the TV menu or CLI.
cp "$temp/tihulu/kaffeine_next/dvb_diagnostics.sh" "$APPROOT/dvb_diagnostics.sh"
chmod 755 "$APPROOT/dvb_diagnostics.sh"

echo "Configuring clean Kaffeine native DVB scanner with isolated system Qt5"
if ! "${SYSTEM_BUILD_ENV[@]}" /usr/bin/cmake --fresh -S "$BUILDSRC" -B "$BUILD" \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF \
  -DCMAKE_INSTALL_PREFIX="$PREFIX" 2>&1 | tee "$LOGDIR/configure.log"; then
  qt_link_diagnostics
  echo "CMake configuration failed; see $LOGDIR/configure.log" >&2
  exit 1
fi
if ! "${SYSTEM_BUILD_ENV[@]}" /usr/bin/cmake --build "$BUILD" --parallel 2 \
    2>&1 | tee "$LOGDIR/build.log"; then
  qt_link_diagnostics
  echo "Kaffeine build failed; see $LOGDIR/build.log" >&2
  echo "The launcher is deliberately not installed until the build succeeds." >&2
  exit 1
fi
"${SYSTEM_BUILD_ENV[@]}" /usr/bin/cmake --install "$BUILD"
test -x "$PREFIX/bin/kaffeine"
# The compiled executable remains attributed to upstream KDE Kaffeine,
# but a standalone installed filename and its QApplication identity
# distinguish TIHULU from /usr/bin/kaffeine.
ln -sfn kaffeine "$PREFIX/bin/tihulu-media-center"
mkdir -p "$HOME/.local/share/icons/hicolor/scalable/apps"
cp "$temp/tihulu/kaffeine_next/assets/tihulu-media-center.svg" \
  "$HOME/.local/share/icons/hicolor/scalable/apps/tihulu-media-center.svg"

# The standalone PLAY-button player SVG is the new default. The user's
# earlier, unmodified portrait PNG is preserved but is NOT implicitly reused
# on every upgrade. An explicitly provided TIHULU_CUSTOM_LOGO chooses PNG
# for this installation; TIHULU_USE_LEGACY_LOGO=1 restores the saved portrait
# at runtime without modifying its bytes.
DESKTOP_ICON="$HOME/.local/share/icons/hicolor/scalable/apps/tihulu-media-center.svg"
if [[ -n "${TIHULU_CUSTOM_LOGO:-}" ]]; then
  if [[ ! -f "$TIHULU_CUSTOM_LOGO" || -L "$TIHULU_CUSTOM_LOGO" ]]; then
    echo "Custom logo must be a readable regular PNG file." >&2
    exit 1
  fi
  if ! python3 -c 'import pathlib,sys; b=pathlib.Path(sys.argv[1]).read_bytes(); sys.exit(0 if len(b)<4194304 and b.startswith(bytes((137,80,78,71,13,10,26,10))) else 1)' "$TIHULU_CUSTOM_LOGO"; then
    echo "Custom logo failed PNG signature / 4 MiB safety check." >&2
    exit 1
  fi
  mkdir -p "$HOME/.local/share/icons/hicolor/64x64/apps"
  cp -- "$TIHULU_CUSTOM_LOGO" "$HOME/.local/share/icons/hicolor/64x64/apps/tihulu-media-center.png"
  DESKTOP_ICON="$HOME/.local/share/icons/hicolor/64x64/apps/tihulu-media-center.png"
fi
if [[ -f "$HOME/.local/share/icons/hicolor/64x64/apps/tihulu-media-center.png" &&
      -z "${TIHULU_CUSTOM_LOGO:-}" ]]; then
  echo "Kept legacy user portrait PNG unchanged; player SVG is now the default icon."
  echo "To use the portrait again: TIHULU_USE_LEGACY_LOGO=1 tihulu-media-center"
fi

TIHULU_KAFFEINE_PRIMARY=1 bash "$temp/tihulu/tv_center/packaging/build-deb.sh" "$temp/debs"
# The AI sidecar may already be installed at the same preview version.
# Force reinstall so the previously visible legacy player is hidden.
sudo apt-get install -y --reinstall "$temp/debs/tihulu-tv-center_0.1.0~dev1_all.deb"

cat > "$HOME/.local/bin/tihulu-kaffeine" <<'LAUNCH'
#!/bin/sh
# XWayland avoids the broken NVIDIA / COSMIC embedded surface path.
if [ -n "${WAYLAND_DISPLAY:-}" ]; then export QT_QPA_PLATFORM=xcb; fi
# Native DVB playback uses Kaffeine/libVLC. On the known NVIDIA + Wayland
# combination, safely use software HEVC decoding first; never force this
# CPU-intensive profile on Pi 5 or systems without NVIDIA.
if [ -z "${TIHULU_VLC_PROFILE:-}" ]; then
  if [ -n "${WAYLAND_DISPLAY:-}" ] && [ -r /proc/driver/nvidia/version ]; then
    TIHULU_VLC_PROFILE=software
  else
    TIHULU_VLC_PROFILE=auto
  fi
fi
# Explicit per-session overrides for isolating decoder vs AAC audio faults.
case "${1:-}" in
  --diagnose-tuner) shift; exec /bin/bash "$HOME/.local/share/tihulu-kaffeine/dvb_diagnostics.sh" "$@" ;;
  --software-video) TIHULU_VLC_PROFILE=software; shift ;;
  --auto-video) TIHULU_VLC_PROFILE=auto; shift ;;
  --diagnose-no-audio) TIHULU_VLC_PROFILE=software-no-audio; shift ;;
esac
export TIHULU_VLC_PROFILE
if [ "$#" -eq 0 ]; then
  set -- --lastchannel
fi
# Do not launch two TIHULU instances that fight for the same frontend.
# The exclusive lock is inherited by the player process and released on exit;
# it never locks /dev/dvb or interferes with system Kaffeine.
if command -v flock >/dev/null 2>&1; then
  mkdir -p "$HOME/.cache"
  exec 9>"$HOME/.cache/tihulu-media-center.lock"
  if ! flock -n 9; then
    echo "TIHULU Media Center is already running. Focus or close that window first." >&2
    exit 2
  fi
fi
# Avoid mixing native system libVLC/Qt5 with the user's Conda installation.
exec env -u LD_LIBRARY_PATH -u LD_PRELOAD -u QT_PLUGIN_PATH \
  -u QT_QPA_PLATFORM_PLUGIN_PATH -u QML2_IMPORT_PATH -u QML_IMPORT_PATH \
  "$HOME/.local/opt/tihulu-kaffeine/bin/tihulu-media-center" "$@"
LAUNCH
chmod 755 "$HOME/.local/bin/tihulu-kaffeine"
ln -sfn tihulu-kaffeine "$HOME/.local/bin/tihulu-media-center"
cat > "$HOME/.local/share/applications/tihulu-kaffeine.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=TIHULU Media Center
GenericName=TV · DAB+ Radio · Local Video/Audio · AI Subtitles
Comment=Standalone native TV and radio player with offline AI, based on KDE Kaffeine
Exec=$HOME/.local/bin/tihulu-media-center
TryExec=$HOME/.local/bin/tihulu-media-center
Icon=$DESKTOP_ICON
StartupWMClass=tihulu-media-center
Terminal=false
Categories=AudioVideo;Video;TV;Audio;Player;
DESKTOP

if [[ "$MODE" != --no-ai ]]; then
  echo "Installing requested offline Whisper Tiny and DE/EN/TR Argos starter."
  if ! tihulu-tv-center ai install; then
    echo "AI setup incomplete; TV itself is installed. Retry from AI Model Market." >&2
  fi
fi
echo "Open TIHULU Media Center (separate app, icon and channel database):"
echo "  $HOME/.local/bin/tihulu-media-center"
echo "Use TV -> TIHULU AI for Model Market and live subtitles."
echo "Only one DVB frontend owner at a time. Inspect with:"
echo "  $HOME/.local/bin/tihulu-media-center --diagnose-tuner"
echo "Set DVB-T2 Source in Configure Television before the first channel scan."
echo "FM/MW/LW requires a suitable SDR; optional tools: bash install.sh --with-analog"
echo "DAB+ Radio is a native tab. Optional welle.io backend (separate SDR):"
echo "  bash $APPROOT/install_welle.sh"
if (( WITH_DAB == 1 )); then
  echo "User explicitly selected --with-dab: building pinned localhost-only welle-cli."
  bash "$APPROOT/install_welle.sh"
fi
