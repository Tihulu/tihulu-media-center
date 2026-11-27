#!/usr/bin/env bash
# Native TV Center development installer for Debian-family Linux.
set -Ee -o pipefail
if [[ "$(uname)" != Linux || ! -f /etc/os-release ]]; then
  echo "Requires Debian/Ubuntu/Pop!_OS/Raspberry Pi OS." >&2; exit 1
fi
. /etc/os-release
case " $ID $ID_LIKE " in
  *debian*|*ubuntu*|*pop*|*raspbian*) ;;
  *) echo "Unsupported Linux distribution." >&2; exit 1 ;;
esac
mode="${1:-}"
if [[ -n "$mode" && "$mode" != "--local" && "$mode" != "--tv-only" ]]; then
  echo "Usage: bash tv_center/install.sh [--local|--tv-only]" >&2; exit 2
fi
root_cmd() { if (( EUID == 0 )); then "$@"; else sudo "$@"; fi; }
echo "Installing native DVB/MPV dependencies; existing TV scans are preserved."
root_cmd apt-get update
root_cmd apt-get install -y --no-install-recommends \
  ca-certificates git python3 python3-pyqt5 python3-venv python3-pip \
  cmake g++ make dvb-tools mpv ffmpeg psmisc dpkg
if apt-cache show w-scan-cpp >/dev/null 2>&1; then
  root_cmd apt-get install -y --no-install-recommends w-scan-cpp
else
  echo "Warning: w-scan-cpp unavailable. Automatic full-frequency scan will need a compatible package source."
fi
tempdir="$(mktemp -d)"
trap 'rm -rf "$tempdir"' EXIT
if [[ "$mode" == "--local" ]]; then
  source_root="$(cd "$(dirname "$BASH_SOURCE")/.." && pwd)"
else
  source_root="$tempdir/repo"
  git clone --quiet --depth 1 \
    --branch feature/tv-center-native-teletext-asr-2026-11-07 \
    https://github.com/Tihulu/TIHULU-TEXT-CENTER.git "$source_root"
fi
bash "$source_root/tv_center/packaging/build-deb.sh" "$tempdir"
pkg="$tempdir/tihulu-tv-center_0.1.0~dev1_all.deb"
test -s "$pkg"
root_cmd dpkg -i "$pkg"
if [[ "$mode" != "--tv-only" ]]; then
  echo "Installing the requested offline AI starter suite:"
  echo "  Whisper.cpp CPU runtime + multilingual Tiny (~78 MB),"
  echo "  Argos runtime + DE/EN/TR four translation directions."
  echo "  This downloads models and compiles locally; network and disk required."
  echo "  Models are removable in Settings → AI Model Market."
  # The GUI and DVB-TV remain installed if model provisioning fails.
  if ! tihulu-tv-center ai install; then
    echo "Warning: AI starter setup incomplete. TV works; retry through the Market or:" >&2
    echo "  tihulu-tv-center ai install" >&2
  fi
else
  echo "TV-only mode: offline AI engines and models can be added later in Settings."
fi
echo "Installed. Open TIHULU TV Center from the apps menu or run: tihulu-tv-center"
echo "Diagnostics: tihulu-tv-center doctor"
echo "For iPhone/Android, enable Local Wi-Fi + HLS in the desktop app."
echo "No TV receiver or RTL-SDR device was opened during installation."
