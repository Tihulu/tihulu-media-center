#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
# Standalone, consent-gated preview installer. No system/service/tuner writes.
set -Eeuo pipefail
umask 077

SNAPSHOT=7821769eb7aed576dd426ec18ffce3696d93a00d
SNAPSHOT_TREE=d471b3aa4e546e8d790512df37fad763254023c6
KAFFEINE=e7ea15b86dafed3b20b151cbcb080578ab8e2d5c
KAFFEINE_TAG=v2.0.19
MODE=""
NO_AI=0
ALLOW_APT=0
APPROOT="${HOME}/.local/opt/tihulu-media-stable"
LAUNCHER="${HOME}/.local/bin/tihulu-media-stable"
PACKAGES=(git ca-certificates cmake g++ make pkg-config extra-cmake-modules
  qtbase5-dev libqt5x11extras5-dev libkf5coreaddons-dev
  libkf5dbusaddons-dev libkf5i18n-dev libkf5kio-dev libkf5solid-dev
  libkf5widgetsaddons-dev libkf5windowsystem-dev libkf5xmlgui-dev
  libvlc-dev libx11-dev libxss-dev libdvbv5-dev libudev-dev
  libqt5sql5-sqlite vlc python3 python3-pyqt5 ffmpeg mpv dvb-tools psmisc dbus-bin)

usage() {
  cat <<'HELP'
Usage: bash installer/media-stable-first.sh MODE [--no-ai] [--allow-apt]
Modes:
  --check      Read-only pinned-source, OS and dependency preflight
  --dry-run    Read-only operation plan (does not install anything)
  --install    Build KDE Kaffeine and the pinned AI companion in HOME only
  --rollback   Atomically restore prior TIHULU stable launcher (or deactivate)
  --uninstall  Fail-closed removal of installer-owned binaries/launchers; keeps private settings
Options:
  --no-ai      No model installation; AI source modules remain available
  --allow-apt  Opt in to INTERACTIVE sudo/apt approval if dependencies missing
No mode downloads AI models. Existing Kaffeine, apps, models, settings, recordings,
channels, tuners and background services are never modified by this script.
HELP
}
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
log() { printf 'TIHULU stable-first: %s\n' "$*"; }
for arg in "$@"; do
  case "$arg" in
    --check|--dry-run|--install|--rollback|--uninstall)
      [[ -z "$MODE" ]] || die 'Select exactly one mode'; MODE="$arg" ;;
    --no-ai) NO_AI=1 ;;
    --allow-apt) ALLOW_APT=1 ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; die "Unknown argument: $arg" ;;
  esac
done
[[ -n "$MODE" ]] || { usage >&2; exit 2; }
(( EUID != 0 )) || die 'Run as an ordinary desktop user, never root'
[[ "$HOME" == /* && "$HOME" != / ]] || die 'HOME must be an absolute user path'

# Serialize the entire operation (including dependency approval, build and
# promotion) with one O_NOFOLLOW, ownership-checked lock *outside* APPROOT.
# A child cannot fake the guard by setting an environment variable alone:
# verify-guard also checks the inherited, open locked file descriptor.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ "$MODE" == --install || "$MODE" == --rollback || "$MODE" == --uninstall ]]; then
  if [[ -z "${TIHULU_MEDIA_GUARD_FD:-}" ]]; then
    exec python3 "$SCRIPT_DIR/preview_safety.py" guarded-exec "$SCRIPT_DIR/media-stable-first.sh" "$@"
  fi
  python3 "$SCRIPT_DIR/preview_safety.py" verify-guard "$TIHULU_MEDIA_GUARD_FD" ||
    die 'Missing owned operation lock; cannot mutate this installation'
fi

atomic_link() {
  local target="$1" link="$2" tmp="${2}.new.$$"
  [[ ! -e "$link" || -L "$link" ]] || die "Refusing to replace non-symlink: $link"
  [[ ! -e "$tmp" && ! -L "$tmp" ]] || die "Temporary link exists: $tmp"
  ln -s -- "$target" "$tmp"
  mv -Tf -- "$tmp" "$link"
}
lock_owned() {
  # The Python guard owns the single sibling flock for the ENTIRE operation.
  # Do not open root/.install.lock with unsafe shell >> redirection.
  [[ -n "${TIHULU_MEDIA_GUARD_FD:-}" ]] || die 'Missing guarded operation descriptor'
  python3 "$SCRIPT_DIR/preview_safety.py" verify-guard "$TIHULU_MEDIA_GUARD_FD" ||
    die 'Concurrent or unowned operation lock'
}

# A release pointer must be one direct, owned release directory.  A glob match
# alone accepts releases/../preview-home and can redirect the native launcher.
valid_release() {
  local target="$1" leaf=""
  [[ "$target" == "$APPROOT/releases/"* ]] || return 1
  leaf="${target#"$APPROOT/releases/"}"
  [[ "$leaf" =~ ^r-[0-9a-f]{12}-[0-9]{8}T[0-9]{6}-[0-9]+$ ]] || return 1
  [[ "$target" == "$APPROOT/releases/$leaf" && -d "$target" && ! -L "$target" ]] || return 1
  [[ "$(stat -c '%u' -- "$target")" == "$EUID" ]] || return 1
  # The directory name and ownership alone are not enough: interrupted or
  # tampered releases must never become the active native executable.
  local checker
  checker="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/preview_safety.py" || return 1
  python3 "$checker" verify-release "$target" >/dev/null 2>&1 || return 1
}
rollback() {
  # Rollback must enforce the same root/ancestor ownership as installation and
  # uninstall, before acquiring a lock or changing any symlink.
  local parent marker="$APPROOT/.media-preview-owner-v1"
  for parent in "$HOME/.local" "$HOME/.local/opt"; do
    [[ -d "$parent" && ! -L "$parent" &&
       "$(stat -c '%u' -- "$parent")" == "$EUID" ]] ||
      die "Unsafe rollback parent: $parent"
  done
  [[ -d "$APPROOT" && ! -L "$APPROOT" &&
     "$(stat -c '%u' -- "$APPROOT")" == "$EUID" ]] ||
    die 'No installer-owned stable installation directory'
  [[ -f "$marker" && ! -L "$marker" &&
     "$(stat -c '%u' -- "$marker")" == "$EUID" &&
     "$(<"$marker")" == 'TIHULU_MEDIA_PREVIEW_OWNED_V1' ]] ||
    die 'Rollback blocked: missing or foreign installer ownership marker'
  [[ -d "$APPROOT/releases" && ! -L "$APPROOT/releases" &&
     "$(stat -c '%u' -- "$APPROOT/releases")" == "$EUID" ]] ||
    die 'Unsafe release directory'
  lock_owned
  local current="$APPROOT/current" previous="$APPROOT/previous" old=""
  [[ -L "$current" ]] || die 'No active stable release to roll back'
  old="$(readlink "$current")"
  valid_release "$old" || die 'Invalid current release pointer'
  if [[ -L "$previous" ]]; then
    local target
    target="$(readlink "$previous")"
    valid_release "$target" || die 'Invalid rollback target'
    atomic_link "$target" "$current"
    atomic_link "$old" "$previous"
    log "Restored previous release: $target; previous active release kept for reactivation"
  else
    [[ ! -e "$previous" ]] || die 'Foreign non-symlink previous release slot'
    rm -- "$current" # Owned symlink only; never delete installed releases.
    log 'First release deactivated; existing user data and release files preserved'
  fi
}
if [[ "$MODE" == --rollback ]]; then rollback; exit 0; fi
if [[ "$MODE" == --uninstall ]]; then
  SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
  exec python3 "$SCRIPT_DIR/preview_safety.py" uninstall
fi

[[ "$(uname -s)" == Linux && -r /etc/os-release ]] || die 'Linux/Debian-family only'
# shellcheck disable=SC1091
. /etc/os-release
case " ${ID:-} ${ID_LIKE:-} " in
  *debian*|*ubuntu*|*pop*|*raspbian*) ;;
  *) die "Unsupported OS: ${ID:-unknown}; no apt action attempted" ;;
esac
for command in git dpkg-query python3 sha256sum; do
  command -v "$command" >/dev/null || die "Required read-only checker missing: $command"
done
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null)" || die 'Run from a Git checkout (not an unreviewed internet pipe)'
[[ -f "$REPO/manifest.json" ]] || die 'Snapshot manifest not found'
git -C "$REPO" cat-file -e "${SNAPSHOT}^{commit}" || die 'Pinned snapshot commit missing; fetch it explicitly before installing'
actual_tree="$(git -C "$REPO" rev-parse "${SNAPSHOT}^{tree}")"
[[ "$actual_tree" == "$SNAPSHOT_TREE" ]] || die "Snapshot tree differs: $actual_tree"
for path in \
  source/installed-package/tv_center/__main__.py \
  source/installed-package/textcenter/__main__.py \
  source/installed-package/kaffeine_next/patch_upstream.py \
  source/installed-package/kaffeine_next/native_radio_tab.h \
  source/installed-package/kaffeine_next/native_unified_recorder.h; do
  git -C "$REPO" cat-file -e "$SNAPSHOT:$path" || die "Pinned source missing: $path"
done
# Never allow a source symlink to resolve into unapproved local directories.
if git -C "$REPO" ls-tree -r "$SNAPSHOT" -- source/installed-package/ |
    grep -q '^120000 blob '; then
  die 'Pinned source contains symbolic links; refusing extraction'
fi
log "Source commit: $SNAPSHOT"
log "Source tree:   $SNAPSHOT_TREE"
log "KDE Kaffeine:  $KAFFEINE ($KAFFEINE_TAG)"
log 'Sole application source variant: source/installed-package/{tv_center,textcenter,kaffeine_next}'
log 'No legacy install.sh and no TEXT-CENTER development branch will execute'

missing=()
for package in "${PACKAGES[@]}"; do
  if [[ "$(dpkg-query -W -f='${Status}' "$package" 2>/dev/null || true)" != 'install ok installed' ]]; then
    missing+=("$package")
  fi
done
if (("${#missing[@]}" > 0)); then
  printf 'Missing APT build/runtime packages (%d): %s\n' "${#missing[@]}" "${missing[*]}" >&2
else
  log 'APT dependency inventory complete'
fi
if [[ "$MODE" == --dry-run ]]; then
  log 'DRY RUN ONLY: would verify upstream pinned SHA, stage modules, patch/build Kaffeine'
  log "DRY RUN ONLY: would stage to $APPROOT/releases/ and atomically select current"
  log "DRY RUN ONLY: would create dedicated launcher $LAUNCHER and desktop entry"
  log "DRY RUN ONLY: AI models/downloads=OFF (no-ai=$NO_AI); sudo/apt only with separate confirmation"
  log 'DRY RUN ONLY: rollback exchanges owned symlinks, never deletes user files'
  log 'DRY RUN ONLY: uninstall audits every owned file and retains preview private data'
  exit 0
fi
if [[ "$MODE" == --check ]]; then
  (("${#missing[@]}" == 0)) || { log 'CHECK HOLD: missing dependencies; no changes made'; exit 3; }
  log 'CHECK PASS: source provenance and dependencies; native build and hardware NOT verified'
  exit 0
fi

if (("${#missing[@]}" > 0)); then
  (( ALLOW_APT == 1 )) || die 'Install blocked: missing dependencies. Re-run with --allow-apt for an interactive approval, or install them separately.'
  [[ -t 0 && -t 1 ]] || die 'APT approval requires an interactive terminal'
  printf 'APT packages to install: %s\n' "${missing[*]}"
  read -r -p 'Type INSTALL APT to approve sudo apt-get update/install: ' approval
  [[ "$approval" == 'INSTALL APT' ]] || die 'APT permission not granted'
  sudo apt-get update
  sudo apt-get install --no-install-recommends -- "${missing[@]}"
  for package in "${missing[@]}"; do
    [[ "$(dpkg-query -W -f='${Status}' "$package" 2>/dev/null || true)" == 'install ok installed' ]] || die "Package still missing: $package"
  done
fi
for command in cmake c++ make tar mktemp mv ln; do
  command -v "$command" >/dev/null || die "Build dependency executable missing: $command"
done
[[ ! -L "$APPROOT" ]] || die 'Application root must not be a symlink'
for parent in "$HOME/.local" "$HOME/.local/opt" "$HOME/.local/bin" "$HOME/.local/share" "$HOME/.local/share/applications"; do
  [[ ! -L "$parent" ]] || die "Symlinked install parent is not accepted: $parent"
done
if [[ -d "$APPROOT" ]]; then
  [[ -f "$APPROOT/.media-preview-owner-v1" && ! -L "$APPROOT/.media-preview-owner-v1" ]] ||
    die 'Existing application root lacks installer-owned marker (legacy installs require independent migration)'
  [[ "$(<"$APPROOT/.media-preview-owner-v1")" == 'TIHULU_MEDIA_PREVIEW_OWNED_V1' ]] ||
    die 'Existing application root has invalid ownership marker'
elif [[ -e "$APPROOT" ]]; then
  die 'Application root is not a real directory'
fi
# Verify entire launcher/desktop bytes, UID, hardlink count and root marker.
# Never accept a matching line in a foreign or modified entrypoint.
python3 "$SCRIPT_DIR/preview_safety.py" preflight-install ||
  die 'Refusing ambiguous or modified existing Media preview entrypoints'
command -v flock >/dev/null || die 'flock is required for safe installation'
mkdir -p -- "$APPROOT/releases" "$HOME/.local/bin" "$HOME/.local/share/applications"
if [[ ! -e "$APPROOT/.media-preview-owner-v1" ]]; then
  printf 'TIHULU_MEDIA_PREVIEW_OWNED_V1\n' > "$APPROOT/.media-preview-owner-v1"
fi
[[ ! -L "$APPROOT/releases" ]] || die 'Symlinked release directory is forbidden'
profile="$APPROOT/preview-home"
[[ ! -L "$profile" ]] || die 'Symlinked preview private home is forbidden'
mkdir -p -- "$profile/.config" "$profile/.local/share" "$profile/.cache" "$profile/.local/state"
for p in "$profile" "$profile/.config" "$profile/.local" "$profile/.local/share" "$profile/.cache" "$profile/.local/state"; do
  [[ -d "$p" && ! -L "$p" ]] || die "Invalid preview private directory: $p"
done
lock_owned
work="$(mktemp -d "$APPROOT/.work.XXXXXXXX")"
stage="$(mktemp -d "$APPROOT/.stage.XXXXXXXX")"
cleanup() {
  if [[ -n "${work:-}" && -d "$work" ]]; then rm -rf -- "$work"; fi
  if [[ -n "${stage:-}" && -d "$stage" ]]; then rm -rf -- "$stage"; fi
}
trap cleanup EXIT
mkdir -p "$stage/py" "$stage/bin" "$stage/native" "$work/snapshot"
git -C "$REPO" archive "$SNAPSHOT" -- source/installed-package | tar -x -C "$work/snapshot"
for module in tv_center textcenter kaffeine_next; do
  cp -a -- "$work/snapshot/source/installed-package/$module" "$stage/py/$module"
done
# Keep provenance and source mapping next to the user-level release.
printf 'snapshot_commit=%s\nsnapshot_tree=%s\nsource_variant=installed-package\nkaffeine_commit=%s\nkaffeine_tag=%s\nno_automatic_models=true\n' \
  "$SNAPSHOT" "$SNAPSHOT_TREE" "$KAFFEINE" "$KAFFEINE_TAG" > "$stage/SOURCE-PROVENANCE.txt"
git -C "$REPO" show "$SNAPSHOT:manifest.json" > "$stage/original-manifest.json"
log 'Cloning only KDE Kaffeine v2.0.19; verifying exact revision before modification'
git clone --quiet --depth 1 --single-branch --branch "$KAFFEINE_TAG" https://github.com/KDE/kaffeine.git "$work/upstream"
actual_kaffeine="$(git -C "$work/upstream" rev-parse HEAD)"
[[ "$actual_kaffeine" == "$KAFFEINE" ]] || die "Upstream KDE commit mismatch: $actual_kaffeine"
PYTHONDONTWRITEBYTECODE=1 python3 "$stage/py/kaffeine_next/patch_upstream.py" "$work/upstream"
grep -Fq 'std::prev(container.constEnd())' "$work/upstream/src/sqlinterface.h" || die 'Native SQL iterator patch missing'
! grep -Fq 'std::prev(container.constEnd(), -1)' "$work/upstream/src/sqlinterface.h" || die 'Unsafe SQL iterator remains'
git -C "$work/upstream" diff --check
python3 -m compileall -q "$stage/py"
# Distro Qt/KF5 only: avoid Conda and mismatched custom Qt plugin search paths.
final="$APPROOT/releases/r-${SNAPSHOT:0:12}-$(date -u +%Y%m%dT%H%M%S)-$$"
[[ ! -e "$final" ]] || die 'Chosen release destination already exists'
build_env=(env -i "HOME=$HOME" "USER=$(id -un)" "PATH=/usr/bin:/bin:/usr/sbin:/sbin" "LANG=C.UTF-8")
"${build_env[@]}" cmake -S "$work/upstream" -B "$work/build" -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF -DCMAKE_INSTALL_PREFIX="$final/native"
"${build_env[@]}" cmake --build "$work/build" --parallel 2
# DESTDIR catches even upstream absolute paths inside isolated staging.
# Configure with final prefix so compiled paths agree after release promotion.
mkdir -p "$stage/DESTDIR"
"${build_env[@]}" "DESTDIR=$stage/DESTDIR" cmake --install "$work/build"
installed="$stage/DESTDIR$final/native"
[[ -d "$installed" ]] || die 'Native staging prefix missing after CMake install'
rmdir "$stage/native"
mv -T -- "$installed" "$stage/native"
[[ -x "$stage/native/bin/kaffeine" ]] || die 'Native Kaffeine binary missing after build'
ln -s kaffeine "$stage/native/bin/tihulu-media-center"
cat > "$stage/bin/tihulu-preview-env" <<'PREVIEWENV'
#!/bin/sh
# Shared by native and Python; PRIVATE HOME forces Qt QSettings and AI JSON
# into the preview container without copying existing user models/settings.
owner_home="${TIHULU_MEDIA_OWNER_HOME:-$HOME}"
preview="$owner_home/.local/opt/tihulu-media-stable/preview-home"
if [ "$HOME" != "$owner_home" ] && [ "$HOME" != "$preview" ]; then
  echo 'Refusing inconsistent preview HOME' >&2; exit 72
fi
for dir in "$preview" "$preview/.config" "$preview/.local" "$preview/.local/share" "$preview/.cache" "$preview/.local/state"; do
  if [ ! -d "$dir" ] || [ -L "$dir" ]; then
    echo "Missing or symlinked isolated preview profile: $dir" >&2; exit 72
  fi
done
TIHULU_MEDIA_OWNER_HOME="$owner_home"
HOME="$preview"
XDG_CONFIG_HOME="$preview/.config"
XDG_DATA_HOME="$preview/.local/share"
XDG_CACHE_HOME="$preview/.cache"
XDG_STATE_HOME="$preview/.local/state"
KDEHOME="$preview/.kde"
PYTHONDONTWRITEBYTECODE=1
export TIHULU_MEDIA_OWNER_HOME HOME XDG_CONFIG_HOME XDG_DATA_HOME XDG_CACHE_HOME XDG_STATE_HOME KDEHOME PYTHONDONTWRITEBYTECODE
# Do not override XDG_RUNTIME_DIR: existing PID-scoped pipes need same runtime.
# Do not import the original HOME's QSettings, models, recordings or channels.
PREVIEWENV
cat > "$stage/bin/tihulu-tv-center" <<'PYLAUNCH'
#!/bin/sh
set -eu
release="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)"
. "$release/bin/tihulu-preview-env"
export PYTHONPATH="$release/py"
if [ -n "${WAYLAND_DISPLAY:-}" ]; then QT_QPA_PLATFORM=xcb; export QT_QPA_PLATFORM; fi
case "${1:-}" in
  ''|tv|watch)
    if [ "$#" -gt 0 ]; then shift; fi
    exec "$release/bin/tihulu-kaffeine" "$@" ;;
esac
exec /usr/bin/python3 -m tv_center "$@"
PYLAUNCH
cat > "$stage/bin/tihulu-kaffeine" <<'NATIVELAUNCH'
#!/bin/sh
set -eu
release="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)"
. "$release/bin/tihulu-preview-env"
export PATH="$release/bin:$PATH"
export PYTHONPATH="$release/py"
# A private session bus prevents KDBusService from activating the existing
# system/user Kaffeine instance under a shared desktop session.
if [ "${TIHULU_MEDIA_PRIVATE_DBUS:-0}" != 1 ]; then
  command -v dbus-run-session >/dev/null 2>&1 || { echo 'dbus-run-session required' >&2; exit 73; }
  TIHULU_MEDIA_PRIVATE_DBUS=1
  export TIHULU_MEDIA_PRIVATE_DBUS
  exec dbus-run-session -- "$release/bin/tihulu-kaffeine" "$@"
fi
if [ -n "${WAYLAND_DISPLAY:-}" ]; then QT_QPA_PLATFORM=xcb; export QT_QPA_PLATFORM; fi
if [ -z "${TIHULU_VLC_PROFILE:-}" ]; then
  if [ -n "${WAYLAND_DISPLAY:-}" ] && [ -r /proc/driver/nvidia/version ]; then
    TIHULU_VLC_PROFILE=software
  else
    TIHULU_VLC_PROFILE=auto
  fi
fi
export TIHULU_VLC_PROFILE
exec env -u LD_LIBRARY_PATH -u LD_PRELOAD -u QT_PLUGIN_PATH -u QT_QPA_PLATFORM_PLUGIN_PATH \
  -u QML2_IMPORT_PATH -u QML_IMPORT_PATH "$release/native/bin/tihulu-media-center" "$@"
NATIVELAUNCH
chmod 755 "$stage/bin/tihulu-tv-center" "$stage/bin/tihulu-kaffeine"
cat > "$stage/bin/tihulu-media-stable" <<'STABLELAUNCH'
#!/bin/sh
set -eu
exec "$HOME/.local/opt/tihulu-media-stable/current/bin/tihulu-kaffeine" "$@"
STABLELAUNCH
chmod 755 "$stage/bin/tihulu-media-stable"
sha256sum "$stage/native/bin/kaffeine" > "$stage/NATIVE-BINARY-SHA256.txt"
python3 "$SCRIPT_DIR/preview_safety.py" prepare-release "$stage"
# Publish complete release BEFORE changing the stable symlink.
mv -T -- "$stage" "$final"
stage=""
old=""
if [[ -L "$APPROOT/current" ]]; then
  old="$(readlink "$APPROOT/current")"
  valid_release "$old" || die 'Current release symlink is not a direct, owned release'
elif [[ -e "$APPROOT/current" ]]; then
  die 'Current release slot is not owned symlink'
fi
# Exclusive O_CREAT|O_EXCL + O_NOFOLLOW file creation; never write into a
# pre-existing owner launcher/desktop, even after a checked pathname races.
python3 "$SCRIPT_DIR/preview_safety.py" publish-entrypoints ||
  die 'Could not safely publish owned launcher and desktop entries'
if [[ -n "$old" ]]; then atomic_link "$old" "$APPROOT/previous"; fi
atomic_link "$final" "$APPROOT/current"
log "Preview installed (user-only): $final"
log "Start on demand: $LAUNCHER"
log "Revert: bash $SCRIPT_DIR/media-stable-first.sh --rollback"
log 'Hardware, system Kaffeine, user models, recordings and existing settings have not been intentionally opened or edited'
log 'Install does NOT prove hardware/runtime equivalence; acceptance remains HOLD'
log 'Preview QSettings/AI JSON use isolated HOME/XDG_CONFIG_HOME; no private settings import'
log 'Uninstall binaries safely with --uninstall; preview user settings remain private'
