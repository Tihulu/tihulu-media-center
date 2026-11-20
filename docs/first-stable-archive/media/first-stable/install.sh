#!/bin/bash
# TIHULU Media First Stable — Install Script
#
# OWNER-SIDE TOOL — READ FIRST:
# This script requires the locally hosted private archive at ../../archive
# relative to its own location. The published GitHub package intentionally
# does NOT include the archive (no binary publication authorization), so this
# script is documentation/reference outside the owner's archive layout.
#
# Installs the preserved FIRST STABLE binary to a TARGET prefix.
# Usage: bash install.sh [--dry-run] [--target PREFIX]
# The default target is an ISOLATED prefix. The live installation is never a
# target of this script.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARCHIVE_DIR="$(cd "${SCRIPT_DIR}/../../.." && pwd)/archive"
TARGET=""
DRY_RUN=false

usage() { echo "Usage: bash install.sh [--dry-run] [--target PREFIX]" >&2; }

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=true; shift ;;
        --target)  TARGET="${2:?--target requires PREFIX}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "ERROR: unknown argument: $1" >&2; usage; exit 2 ;;
    esac
done

# No positional fallback: a non-default target must be explicit.
if [ -z "${TARGET}" ]; then
    TARGET="$HOME/.local/opt/tihulu-kaffeine-first-stable"
fi

# Path normalization + destination safety pre-checks before any write.
TARGET_NORM="$(realpath -m -- "${TARGET}")"
LIVE_NORM="$(realpath -m -- "$HOME/.local/opt/tihulu-kaffeine")"
if [ "${TARGET_NORM}" = "${LIVE_NORM}" ]; then
    echo "ERROR: refusing to target the LIVE installation." >&2
    exit 3
fi
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

echo "=== TIHULU Media First Stable — Install ==="
echo "Archive: ${ARCHIVE_DIR}"
echo "Target:  ${TARGET}"

# Verify archive integrity before install
echo ""
echo "--- Verifying archive integrity ---"
cd "${ARCHIVE_DIR}"
if grep -q '^/' manifest-verified.sha256; then
    echo "ERROR: manifest contains absolute paths; refusing." >&2
    exit 1
fi
if sha256sum -c manifest-verified.sha256 2>&1 | grep -q "FAILED"; then
    echo "ERROR: Archive integrity check FAILED"
    exit 1
fi
echo "Archive integrity: OK"

# Verify critical binary
echo ""
echo "--- Verifying critical binary ---"
EXPECTED_HASH="1211bd5f8e16267d4b7f7b537f2b2c5c218b204d786c85fa6119a0f8ffa0d502"
ACTUAL_HASH=$(sha256sum "${ARCHIVE_DIR}/bin/kaffeine" 2>/dev/null | awk '{print $1}')
if [ "${ACTUAL_HASH}" != "${EXPECTED_HASH}" ]; then
    echo "ERROR: Binary hash mismatch!"
    echo "  Expected: ${EXPECTED_HASH}"
    echo "  Actual:   ${ACTUAL_HASH}"
    exit 1
fi
echo "Binary hash: OK"

# Create target directory
if ${DRY_RUN}; then
    echo "[DRY-RUN] Would create target: ${TARGET}"
    exit 0
fi

install -d -m 755 "${TARGET}/bin" "${TARGET}/share"

# Install files (no-dereference copy; destination symlinks already refused)
echo ""
echo "--- Installing files ---"
cp "${ARCHIVE_DIR}/bin/kaffeine" "${TARGET}/bin/kaffeine"
ln -sf kaffeine "${TARGET}/bin/tihulu-media-center"
chmod 755 "${TARGET}/bin/kaffeine"
echo "  Installed: ${TARGET}/bin/kaffeine"
echo "  Symlink: ${TARGET}/bin/tihulu-media-center -> kaffeine"

if [ -d "${ARCHIVE_DIR}/share" ]; then
    cp -a --no-dereference "${ARCHIVE_DIR}/share/." "${TARGET}/share/"
    echo "  Installed: ${TARGET}/share/*"
fi

cp "${ARCHIVE_DIR}/tihulu-kaffeine" "${TARGET}/tihulu-kaffeine"
chmod 755 "${TARGET}/tihulu-kaffeine"
echo "  Installed: ${TARGET}/tihulu-kaffeine (launcher)"

echo ""
echo "=== Installation Complete ==="
echo ""
echo "To use this installation:"
echo "  1. Create symlink: ln -sf ${TARGET}/tihulu-kaffeine \$HOME/.local/bin/tihulu-media-fs"
echo "  2. Or run directly: ${TARGET}/tihulu-kaffeine"
echo ""
echo "WARNING: This does NOT replace the live installation."
echo "Live path: ~/.local/opt/tihulu-kaffeine/"
echo "Installed: ${TARGET}/"
