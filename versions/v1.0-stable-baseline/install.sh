#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
# TIHULU Media Center v1.0-stable-baseline — one-line installer for THIS version.
#
# Public usage:
#   curl -fsSL https://raw.githubusercontent.com/Tihulu/tihulu-media-center/v1.0-stable-baseline/versions/v1.0-stable-baseline/install.sh | bash
#
# No AI models are downloaded. AI stays optional through the in-app market.
set -Eeuo pipefail

REPO_URL="${TIHULU_REPO_URL:-https://github.com/Tihulu/tihulu-media-center.git}"
REVISION="${TIHULU_REVISION:-v1.0-stable-baseline}"

command -v git >/dev/null 2>&1 || {
  echo "ERROR: git is required for the one-line installer" >&2
  exit 1
}

TMP="$(mktemp -d "${TMPDIR:-/tmp}/tihulu-install-version.XXXXXX")"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

# The installer only accepts an owner-writable checkout (0700).
umask 077
git clone --depth 1 --branch "$REVISION" "$REPO_URL" "$TMP/repo"
chmod 700 "$TMP/repo"
# The installer takes exactly one mode; keep it simple when none is given.
if [ "$#" -eq 0 ]; then set -- --install --no-ai; fi
exec bash "$TMP/repo/installer/media-stable-first.sh" "$@"
