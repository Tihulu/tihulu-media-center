# TIHULU Media Center — published versions

Every version below is installable with its own one-line installer. The latest
version is also shown in the repository README. Older versions remain available
for rollback.

| Version | Tag | Status | One-line install |
|---|---|---|---|
| v1.1-round3 | `v1.1-round3` | Latest | `curl -fsSL https://raw.githubusercontent.com/Tihulu/tihulu-media-center/v1.1-round3/versions/v1.1-round3/install.sh \| bash` |
| v1.0-stable-baseline | `v1.0-stable-baseline` | Rollback reference (owner-quoted) | `curl -fsSL https://raw.githubusercontent.com/Tihulu/tihulu-media-center/v1.0-stable-baseline/versions/v1.0-stable-baseline/install.sh \| bash` |

## Notes

- No version downloads AI models; AI stays optional via the in-app market and
  reuses models already installed on the machine.
- Each version pins its own tag, so installing an older version does not change
  what a newer version installs.
- Kaffeine remains KDE Kaffeine (GPL-2.0-or-later); attribution is kept in the
  repository NOTICE/LICENSES files.
