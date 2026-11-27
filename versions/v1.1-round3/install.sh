#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
# TIHULU Media Center v1.1-round3 — one-line installer for THIS version.
#
# Public usage:
#   curl -fsSL https://raw.githubusercontent.com/Tihulu/tihulu-media-center/v1.1-round3/versions/v1.1-round3/install.sh | bash
#
# No AI models are downloaded. AI stays optional through the in-app market.
set -Eeuo pipefail

REPO_URL="${TIHULU_REPO_URL:-https://github.com/Tihulu/tihulu-media-center.git}"
REVISION="${TIHULU_REVISION:-v1.1-round3}"

command -v git >/dev/null 2>&1 || {
  echo "ERROR: git is required for the one-line installer" >&2
  exit 1
}

TMP="$(mktemp -d "${TMPDIR:-/tmp}/tihulu-install-version.XXXXXX")"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

# The installer requires owner-writable directories and 0644 legal notices;
# 022 is the mode set that satisfies both (no group/other write).
umask 022
git clone --depth 1 --branch "$REVISION" "$REPO_URL" "$TMP/repo"
chmod 700 "$TMP/repo"
# The installer takes exactly one mode; keep it simple when none is given.
if [ "$#" -eq 0 ]; then set -- --install --no-ai; fi
exec bash "$TMP/repo/installer/media-stable-first.sh" "$@"
