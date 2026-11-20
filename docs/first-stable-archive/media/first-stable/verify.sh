#!/bin/bash
# TIHULU Media First Stable — Verify Script
# Verifies archive integrity against known hashes

set -euo pipefail
# Archive is at ../../archive relative to this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARCHIVE_DIR="$(cd "${SCRIPT_DIR}/../../.." && pwd)/archive"
PASS=0
FAIL=0

echo "=== TIHULU Media First Stable — Verify ==="
echo "Archive: ${ARCHIVE_DIR}"
echo ""

# Check archive directory exists
if [ ! -d "${ARCHIVE_DIR}" ]; then
    echo "FAIL: Archive directory not found: ${ARCHIVE_DIR}"
    exit 1
fi

# Critical binary check
echo "--- Critical Binary ---"
CRITICAL_HASH="1211bd5f8e16267d4b7f7b537f2b2c5c218b204d786c85fa6119a0f8ffa0d502"
LAUNCHER_HASH="85553f66f51ace8850950692a8648205bfee4b9416541ae45b60e8ac431ea2bf"

if [ -f "${ARCHIVE_DIR}/bin/kaffeine" ]; then
    ACTUAL=$(sha256sum "${ARCHIVE_DIR}/bin/kaffeine" | awk '{print $1}')
    if [ "${ACTUAL}" = "${CRITICAL_HASH}" ]; then
        echo "PASS: bin/kaffeine hash matches"
        PASS=$((PASS+1))
    else
        echo "FAIL: bin/kaffeine hash mismatch (got ${ACTUAL})"
        FAIL=$((FAIL+1))
    fi
else
    echo "FAIL: bin/kaffeine not found"
    FAIL=$((FAIL+1))
fi

# Symlink check
if [ -L "${ARCHIVE_DIR}/bin/tihulu-media-center" ]; then
    TARGET=$(readlink "${ARCHIVE_DIR}/bin/tihulu-media-center")
    if [ "${TARGET}" = "kaffeine" ]; then
        echo "PASS: tihulu-media-center symlink -> kaffeine"
        PASS=$((PASS+1))
    else
        echo "FAIL: tihulu-media-center symlink points to ${TARGET}"
        FAIL=$((FAIL+1))
    fi
else
    echo "FAIL: tihulu-media-center is not a symlink"
    FAIL=$((FAIL+1))
fi

# Build ID check
echo ""
echo "--- Build ID ---"
if command -v readelf &>/dev/null; then
    BUILD_ID=$(readelf -n "${ARCHIVE_DIR}/bin/kaffeine" 2>/dev/null | grep "Build ID" | grep -o '[0-9a-f]\{40\}')
    EXPECTED_BI="f148596245a60e39b83e8dfb248641830b93ead3"
    if [ "${BUILD_ID}" = "${EXPECTED_BI}" ]; then
        echo "PASS: Build ID matches (${BUILD_ID})"
        PASS=$((PASS+1))
    else
        echo "FAIL: Build ID mismatch (got ${BUILD_ID})"
        FAIL=$((FAIL+1))
    fi
fi

# Full manifest check
echo ""
echo "--- Full Archive Manifest ---"
cd "${ARCHIVE_DIR}"
if [ -f "manifest-verified.sha256" ]; then
    RESULTS=$(sha256sum -c manifest-verified.sha256 2>&1)
    OK_COUNT=$(echo "${RESULTS}" | grep -c ": OK" || true)
    FAIL_COUNT=$(echo "${RESULTS}" | grep -c ": FAILED" || true)
    echo "PASS: ${OK_COUNT} files verified OK"
    PASS=$((PASS+1))
    if [ "${FAIL_COUNT}" -gt 0 ]; then
        echo "FAIL: ${FAIL_COUNT} files FAILED verification"
        FAIL=$((FAIL+1))
        echo "${RESULTS}" | grep FAILED
    fi
else
    echo "FAIL: manifest-verified.sha256 not found"
    FAIL=$((FAIL+1))
fi

# Launcher check
echo ""
echo "--- Launcher ---"
if [ -f "${ARCHIVE_DIR}/tihulu-kaffeine" ]; then
    ACTUAL=$(sha256sum "${ARCHIVE_DIR}/tihulu-kaffeine" | awk '{print $1}')
    if [ "${ACTUAL}" = "${LAUNCHER_HASH}" ]; then
        echo "PASS: tihulu-kaffeine hash matches"
        PASS=$((PASS+1))
    else
        echo "FAIL: tihulu-kaffeine hash mismatch"
        FAIL=$((FAIL+1))
    fi
else
    echo "FAIL: tihulu-kaffeine not found"
    FAIL=$((FAIL+1))
fi

echo ""
echo "=== Summary ==="
echo "PASSED: ${PASS}"
echo "FAILED: ${FAIL}"
echo ""

if [ ${FAIL} -eq 0 ]; then
    echo "RESULT: ALL CHECKS PASSED"
    exit 0
else
    echo "RESULT: ${FAIL} CHECKS FAILED"
    exit 1
fi