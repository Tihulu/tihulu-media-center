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

git clone --depth 1 --branch "$REVISION" "$REPO_URL" "$TMP/repo"
exec bash "$TMP/repo/installer/media-stable-first.sh" --install --no-ai "$@"
