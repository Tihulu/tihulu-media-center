# MEDIA-INSTALL-SAFETY-P0 — isolated preview configuration and safe removal

**Scope:** independent review-only Draft PR, stacked on exact QA PR #4 head
abf8c99862a9ca9f4c3c6ff43b3281b9bf8f4ee6. Protected installer #2,
feature QA #3, independent QA #4, source snapshot 7821769eb7aed576dd426ec18ffce3696d93a00d,
main and TEXT CENTER development are not modified.

## Settings boundary (no implicit model/settings migration)

The experimental launcher retains its own binary and source tree. Crucially,
launching it now enters an independent **preview HOME**, not the owner's real
HOME; XDG_CONFIG_HOME, XDG_DATA_HOME, XDG_CACHE_HOME, XDG_STATE_HOME and KDEHOME
point inside this private preview profile. The native Kaffeine launcher also
enters a private D-Bus session so its KDBusService identity cannot claim an
already-running Kaffeine app in the real desktop session.

Private preview data resides under:
  ~/.local/opt/tihulu-media-stable/preview-home

Examples:
- Preview QSettings TIHULU/KaffeineRadio and
  TIHULU/KaffeineCaptionAppearance are under preview-home/.config/TIHULU;
  original ~/.config/TIHULU remains untouched.
- Preview tv_center/ai_settings.py resolves its JSON to
  preview-home/.config/tihulu-tv-center/ai-settings.json; original AI settings
  under the real HOME remain untouched.
- Preview Kaffeine channel/favorites data and recording defaults use a separate
  profile; original channel DBs and recordings are not auto-imported.
- Existing real-home local AI model directories, paths, settings and weights
  are not read/imported automatically or moved. Preview may show no installed
  models; explicit future setup requires a separate owner decision.

The source-only snapshot is unchanged byte-for-byte; no rewriting frozen C++
headers, lyrics timing, Teletext/Whisper modes, AI profiles or translation code.
Native/Qt GUI behavior with a private session bus and optional external DAB
backend needs manual validation; **do not assert behavioral parity** from a
headless smoke test.

## User-reviewed lifecycle (no published remote one-line command)

Run only in a disposable clone after inspecting the source:

  bash installer/media-stable-first.sh --dry-run --no-ai
  bash installer/media-stable-first.sh --check --no-ai
  bash installer/media-stable-first.sh --install --no-ai
  bash installer/media-stable-first.sh --rollback
  bash installer/media-stable-first.sh --uninstall

Uninstall is a **program removal**, not destruction of user files. Each release
has an installer-created .media-preview-release.json manifest recording every
installed path, file SHA-256 and symlink target. The application root has an
explicit marker. The uninstaller checks exact ownership, all root contents,
release file inventory, both symlinks, launcher and desktop bytes before any
deletion. Wrong ownership, added recordings, modified scripts, symlink escape,
unrecognized stage residue or a concurrent installer fails closed.

If an install is interrupted and leaves .work.* or .stage.* data, uninstall
reports HOLD and preserves the unverified files for safe manual triage instead
of erasing potentially private content. It never cleans device services,
other TIHULU app files, user-home models, system packages or remote resources.

Uninstall deletes only verified preview executable releases, active/previous
pointers, launcher and desktop entry. It **retains preview-home private
settings/data** and the installer ownership marker/lock so a future reviewed
re-install can safely re-use the profile. Running --uninstall twice is safe.
A full private-data purge is intentionally NOT available: ownership of settings,
recordings, downloaded models and later user-generated data cannot be proven by
an installer manifest and requires an independent, separately authorized action.

Legacy pre-marker installs must NOT be silently adopted. The new installer
fails closed if the preview root exists without an owned marker; do not
overwrite previous experimental content.

## Automated proof and remaining acceptance

- Synthetic: original 28 source/feature tests, strict new negative cases for
  modified/foreign files, symlink release/profile/pointer, interrupted
  installs, conflicting desktop/launcher, idempotent removal, owner sentinels.
- Native CI: disposable Ubuntu 24.04 build and Qt/Kaffeine Xvfb startup,
  installed module imports, QSettings path probe, two full installs, rollback,
  full owned binary uninstall, retained private preview profile, original
  user settings/channels/recordings sentinels unchanged.
- **Not proved:** actual Pop!_OS 24.04 / Debian packaging and KDE audio/GUI
  session behavior, live TV/DVB, DAB/FM, Teletext, Comfort Reading, Radio
  Lyrics/karaoke timing, Whisper CUDA/CPU inference, Argos/NLLB/MADLAD
  translation, original private settings and binary hash equivalence, legal
  license/SPDX review, or correct coexistence under real hardware usage.

**Decision:** source/synthetic/build CI may be GO within tested scope.
Full functional equivalence and public one-line release remain **HOLD**.
No hardware access, owner-machine installation, merge, release or model download.
