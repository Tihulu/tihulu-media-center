#!/bin/bash
# TIHULU Media First Stable — Install Script
# Installs preserved FIRST STABLE binary to target prefix
# Usage: bash install.sh [--dry-run] [--target PREFIX]

set -euo pipefail
# Archive is at ../../archive relative to this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARCHIVE_DIR="$(cd "${SCRIPT_DIR}/../../.." && pwd)/archive"
TARGET="${2:-$HOME/.local/opt/tihulu-kaffeine-first-stable}"
DRY_RUN=false

if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=true
fi

if [ "${2:-}" = "--target" ]; then
    TARGET="${3:-$HOME/.local/opt/tihulu-kaffeine-first-stable}"
fi

echo "=== TIHULU Media First Stable — Install ==="
echo "Archive: ${ARCHIVE_DIR}"
echo "Target:  ${TARGET}"

# Verify archive integrity before install
echo ""
echo "--- Verifying archive integrity ---"
cd "${ARCHIVE_DIR}"
if command -v sha256sum &>/dev/null; then
    if sha256sum -c manifest-verified.sha256 2>&1 | grep -q "FAILED"; then
        echo "ERROR: Archive integrity check FAILED"
        exit 1
    fi
    echo "Archive integrity: OK"
fi

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

mkdir -p "${TARGET}"

# Install files
echo ""
echo "--- Installing files ---"

# Bin directory
mkdir -p "${TARGET}/bin"
cp "${ARCHIVE_DIR}/bin/kaffeine" "${TARGET}/bin/kaffeine"
ln -sf kaffeine "${TARGET}/bin/tihulu-media-center"
chmod 755 "${TARGET}/bin/kaffeine"
echo "  Installed: ${TARGET}/bin/kaffeine"
echo "  Symlink: ${TARGET}/bin/tihulu-media-center -> kaffeine"

# Share directory
if [ -d "${ARCHIVE_DIR}/share" ]; then
    mkdir -p "${TARGET}/share"
    cp -a "${ARCHIVE_DIR}/share/"* "${TARGET}/share/" 2>/dev/null || true
    echo "  Installed: ${TARGET}/share/*"
fi

# Launcher script
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
