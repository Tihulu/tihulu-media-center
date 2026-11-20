#!/bin/bash
# TIHULU Media First Stable — Restore Script
#
# OWNER-SIDE TOOL — READ FIRST:
# This script requires the locally hosted private archive at ../../archive
# relative to its own location. The published GitHub package intentionally
# does NOT include the archive (no binary publication authorization), so this
# script is documentation/reference outside the owner's archive layout.
#
# Restores the preserved FIRST STABLE files to a TARGET prefix.
# SAFE DEFAULT: isolated prefix (~/.local/opt/tihulu-kaffeine-first-stable).
# The LIVE installation (~/.local/opt/tihulu-kaffeine) is never touched unless
# the caller explicitly passes --live.

# Known limitation: a same-UID writer can race the destination pre-checks (TOCTOU
# window); use only on trusted single-user systems.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARCHIVE_DIR="$(cd "${SCRIPT_DIR}/../../.." && pwd)/archive"
LIVE_INSTALL="$HOME/.local/opt/tihulu-kaffeine"
TARGET="$HOME/.local/opt/tihulu-kaffeine-first-stable"
DRY_RUN=false
ALLOW_LIVE=false

usage() { echo "Usage: bash restore.sh [--target PREFIX] [--dry-run] [--live]" >&2; }

while [ $# -gt 0 ]; do
    case "$1" in
        --live)    ALLOW_LIVE=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --target)  TARGET="${2:?--target requires PREFIX}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "ERROR: unknown argument: $1" >&2; usage; exit 2 ;;
    esac
done

# Path normalization: strip trailing slashes and resolve symlinks so that
# trailing-slash, relative-path and symlink variants cannot bypass the guard.
TARGET_NORM="$(realpath -m -- "${TARGET}")"
LIVE_NORM="$(realpath -m -- "${LIVE_INSTALL}")"
if [ "${TARGET_NORM}" = "${LIVE_NORM}" ] && [ "${ALLOW_LIVE}" != true ]; then
    echo "ERROR: refusing to overwrite the LIVE installation (${LIVE_INSTALL})." >&2
    echo "The live installation is preserved. To force it, re-run with --live" >&2
    echo "after taking your own backup." >&2
    exit 3
fi

# Destination safety pre-checks before any filesystem write.
if [ -L "${TARGET}" ]; then
    echo "ERROR: TARGET must be a real directory, not a symlink: ${TARGET}" >&2
    exit 2
fi
if [ -e "${TARGET}" ] && [ ! -d "${TARGET}" ]; then
    echo "ERROR: TARGET exists and is not a directory: ${TARGET}" >&2
    exit 2
fi
if [ -e "${TARGET}" ] && [ ! -O "${TARGET}" ] && [ "$(id -u)" != "0" ]; then
    echo "ERROR: TARGET is not owned by the current user: ${TARGET}" >&2
    exit 2
fi
if [ -d "${TARGET}" ] && find "${TARGET}" -type l | grep -q .; then
    echo "ERROR: TARGET contains symlinks; refusing to write through them." >&2
    exit 2
fi

echo "=== TIHULU Media First Stable — Restore ==="
echo "Archive: ${ARCHIVE_DIR}"
echo "Target:  ${TARGET}"

# Verify archive integrity first
echo ""
echo "--- Verifying archive integrity ---"
cd "${ARCHIVE_DIR}"
if grep -q '^/' manifest-verified.sha256; then
    echo "ERROR: manifest contains absolute paths; refusing." >&2
    exit 1
fi
if sha256sum -c manifest-verified.sha256 2>&1 | grep -q "FAILED"; then
    echo "ERROR: Archive integrity check FAILED. Aborting."
    exit 1
fi
echo "Archive integrity: OK"

# Critical hash verification
EXPECTED="1211bd5f8e16267d4b7f7b537f2b2c5c218b204d786c85fa6119a0f8ffa0d502"
ACTUAL=$(sha256sum "${ARCHIVE_DIR}/bin/kaffeine" | awk '{print $1}')
if [ "${ACTUAL}" != "${EXPECTED}" ]; then
    echo "ERROR: Binary hash mismatch! This is NOT the original binary."
    exit 1
fi
echo "Critical binary hash: OK"

if ${DRY_RUN}; then
    echo "[DRY-RUN] Would restore into: ${TARGET}"
    exit 0
fi

# Optional backup of the target directory (never the live install unless --live)
if [ -d "${TARGET}" ]; then
    BACKUP_DIR="${TARGET}.restore-backup-$(date +%Y%m%d-%H%M%S)"
    echo ""
    echo "--- Backing up existing target ---"
    mkdir -p "${BACKUP_DIR}"
    cp -a "${TARGET}"/* "${BACKUP_DIR}/" 2>/dev/null || true
    echo "Existing target backed up to: ${BACKUP_DIR}"
fi

# Restore files (no-dereference copy; destination symlinks already refused)
echo ""
echo "--- Restoring files ---"
install -d -m 755 "${TARGET}/bin" "${TARGET}/share"
cp "${ARCHIVE_DIR}/bin/kaffeine" "${TARGET}/bin/kaffeine"
ln -sf kaffeine "${TARGET}/bin/tihulu-media-center"
chmod 755 "${TARGET}/bin/kaffeine"
echo "  Restored: ${TARGET}/bin/kaffeine"
echo "  Symlink: ${TARGET}/bin/tihulu-media-center -> kaffeine"

if [ -d "${ARCHIVE_DIR}/share" ]; then
    cp -a --no-dereference "${ARCHIVE_DIR}/share/." "${TARGET}/share/"
    echo "  Restored: ${TARGET}/share/*"
fi

if [ -f "${ARCHIVE_DIR}/tihulu-kaffeine" ]; then
    cp "${ARCHIVE_DIR}/tihulu-kaffeine" "${TARGET}/tihulu-kaffeine"
    chmod 755 "${TARGET}/tihulu-kaffeine"
    echo "  Restored: ${TARGET}/tihulu-kaffeine (launcher)"
fi

echo ""
echo "=== Restore Complete ==="
echo "Live installation (${LIVE_INSTALL}) was not modified unless --live was given."
