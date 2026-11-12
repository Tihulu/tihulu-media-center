#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
# Build the GPL-2+ welle-cli receiver with LOCALHOST-ONLY HTTP, to be
# controlled by the native Radio tab in TIHULU Kaffeine.
set -Eeuo pipefail
if [[ "$(uname -s)" != Linux ]] || (( EUID == 0 )); then
  echo "Run as an ordinary Linux desktop user, not root." >&2; exit 1
fi
if ! command -v apt-get >/dev/null 2>&1; then
  echo "Optional receiver build requires Debian/Ubuntu/Pop!_OS." >&2; exit 1
fi
echo "Installing welle-cli build prerequisites (no changes to GPU drivers)."
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  git ca-certificates cmake g++ make pkg-config python3 \
  libfaad-dev libmpg123-dev libfftw3-dev librtlsdr-dev \
  libusb-1.0-0-dev libmp3lame-dev libflac++-dev \
  libsoapysdr-dev libairspy-dev libasound2-dev
ROOT="$HOME/.local/share/tihulu-welle"
PREFIX="$HOME/.local/opt/tihulu-welle"
mkdir -p "$ROOT" "$PREFIX"
TEMPDIR="$(mktemp -d)"
trap 'rm -rf "$TEMPDIR"' EXIT
# Pin a real upstream welle.io revision; retain GPL copyright/attribution.
REVISION=512558d1f8ac4c524d3c63e97510ea36c1bd7a70
git clone --no-tags --depth 1 https://github.com/AlbrechtL/welle.io.git "$TEMPDIR/welle"
ACTUAL="$(git -C "$TEMPDIR/welle" rev-parse HEAD)"
if [[ "$ACTUAL" != "$REVISION" ]]; then
  # Fetch the historically pinned commit even after upstream master advances.
  git -C "$TEMPDIR/welle" fetch --depth 1 origin "$REVISION"
  git -C "$TEMPDIR/welle" checkout --detach "$REVISION"
fi
if [[ "$(git -C "$TEMPDIR/welle" rev-parse HEAD)" != "$REVISION" ]]; then
  echo "Pinned upstream source mismatch; refusing an unreviewed build." >&2; exit 1
fi
python3 - "$TEMPDIR/welle/src/various/Socket.cpp" <<'PY'
from pathlib import Path
import sys
file=Path(sys.argv[1])
code=file.read_text()
old="addr.sin_addr.s_addr = htons(INADDR_ANY);"
if code.count(old)!=1:
    raise SystemExit("Unexpected socket implementation: refusing insecure radio backend")
# welle upstream binds INADDR_ANY. Native Kaffeine must never start a
# publicly reachable unauthenticated tune/stream/receiver-control API.
code=code.replace(old,"addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);")
file.write_text(code)
PY
# Avoid mixing Pop!_OS system SDR/Qt libraries with an active Conda base
# environment (which may supply incompatible libstdc++, pkg-config or CMake).
SYSTEM_ENV=(env -i "HOME=$HOME" "USER=$(id -un)" "LANG=C.UTF-8"
  "PATH=/usr/bin:/bin:/usr/sbin:/sbin")
"${SYSTEM_ENV[@]}" /usr/bin/cmake -S "$TEMPDIR/welle" -B "$TEMPDIR/build" \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PREFIX" \
  -DBUILD_WELLE_IO=OFF -DBUILD_WELLE_CLI=ON \
  -DRTLSDR=ON -DSOAPYSDR=ON -DFLAC=ON -DAIRSPY=ON
"${SYSTEM_ENV[@]}" /usr/bin/cmake --build "$TEMPDIR/build" --parallel 2
"${SYSTEM_ENV[@]}" /usr/bin/cmake --install "$TEMPDIR/build"
test -x "$PREFIX/bin/welle-cli"
printf '%s\n' "$REVISION" > "$PREFIX/.tihulu-loopback-welle-revision"
chmod 644 "$PREFIX/.tihulu-loopback-welle-revision"
printf 'READY: %s\n' "$PREFIX/bin/welle-cli"
echo "Return to Kaffeine → Radio (DAB+) and press Start receiver."
echo "welle-cli HTTP access is patched to 127.0.0.1 only."
