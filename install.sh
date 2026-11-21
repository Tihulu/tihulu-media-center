#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
# One-line bootstrap for TIHULU Media Center.
#
# Public usage:
#   curl -fsSL https://raw.githubusercontent.com/Tihulu/tihulu-media-center/fix/media-acceptance-record-playback/install.sh | bash
#
# This does not install AI models. AI remains optional through the in-app market.
set -Eeuo pipefail

REPO_URL="${TIHULU_REPO_URL:-https://github.com/Tihulu/tihulu-media-center.git}"
BRANCH="${TIHULU_BRANCH:-fix/media-acceptance-record-playback}"
ALLOW_APT="${TIHULU_ALLOW_APT:-0}"

command -v git >/dev/null 2>&1 || {
  echo "ERROR: git is required for the one-line installer" >&2
  exit 1
}

TMP="$(mktemp -d "${TMPDIR:-/tmp}/tihulu-install.XXXXXX")"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$TMP/repo"

ARGS=(--install --no-ai)
if [[ "$ALLOW_APT" == "1" ]]; then
  ARGS+=(--allow-apt)
fi

exec bash "$TMP/repo/installer/media-stable-first.sh" ${ARGS[@]+"${ARGS[@]}"} "$@"
