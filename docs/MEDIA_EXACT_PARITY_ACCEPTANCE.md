# MEDIA-EXACT-PARITY-QA — release acceptance (Draft / HOLD)

**Owner goal:** a future one-line installer should reconstruct the **same TV/Radio
features, selectable modes, and observable behavior** as the privately archived
on-device TIHULU Media Center on 2026-11-12. A compilation success, source
checksum match, or screenshot is **not** enough. The word "stable-first" is
an archival label, **not** a declaration of production stability.

**Scope:** this QA branch adds only acceptance tests and documentation.
It must not change the frozen snapshot (`7821769eb7aed576dd426ec18ffce3696d93a00d`),
the separate installer Draft PR, main, live installation, ongoing TEXT-CENTER
development, models, settings, tuners, or services. No merge or release.

## What is already provable without hardware

- Source identity: preserve the complete `source/installed-package/` directory,
  compared byte-for-byte through Git against the pinned original snapshot.
  The installer extracts exactly that tree and patches pinned KDE Kaffeine
  `e7ea15b86dafed3b20b151cbcb080578ab8e2d5c` only in a temporary
  build tree. A different development worktree must never replace it.
- TV selectable subtitle sources: Teletext -> Whisper automatic fallback,
  broadcaster Teletext hard-only, Whisper live-only, manual Teletext page,
  off. Comfort reading and stable subtitle holding; language/output controls;
  spoken dialogue/music priority; real buffer and offset controls.
- Radio: LRCLIB/optional lyrics sources, ASR-evidence line matching (no
  fake lyrics times), independent Karaoke and AI Lip-sync Refresh, Qwen
  forced-aligner only for eligible languages, Whisper fallback for Turkish,
  four reading presets (Live, Comfort, Relaxed, TV-style Adaptive).
- AI Model Market: explicit optional model selection, saved common TV/Radio
  settings, CPU fallback, GPU selection, NLLB/MADLAD/Argos, five defined
  hardware profiles with preview separate from selection.
- Local file: transcribe/translate entire local video/audio before playback
  only when that user-selected mode is active.
- The QA contract in `tests/test_stable_first_feature_parity.py` checks code
  presence, source integrity and selected no-hardware behavior. It is NOT
  a substitute for GUI, actual broadcast, inference, or personal data checks.

## Acceptance gates — ALL must pass before promoting a one-line installer

| Gate | Evidence needed | Current release status |
| --- | --- | --- |
| Frozen source identity | Exact Git snapshot tree + installed modules + patch provenance | QA source check added; run and review on PR |
| Native UI / start / stop | Clean Pop!_OS 24.04 VM, Kaffeine, standalone launcher, independent system Kaffeine | HOLD |
| TV reception | DVB-T2 tune and channel changes with native receiver, no regression | HOLD |
| TV Teletext / Whisper | Hard/auto/ASR/manual/off; real mismatch/recovery, timing, no stale captions after channel change | HOLD |
| TV reading | Comfort reading stable phrases, readable holds, subtitle style/display, buffer and offset controls | HOLD |
| Radio FM/DAB | Real antenna/receiver, correct ownership, DLS metadata, audio continuity | HOLD |
| Lyrics / Karaoke | Actual song/station, consented provider, audio-matched lyrics, false-positive rejection, sync refresh, timing, reading presets | HOLD |
| AI speech | CPU Whisper and managed Faster-Whisper CUDA actual inference, chosen active engine and fallback correctly reported | HOLD |
| Translation | Installed Argos packs and NLLB/MADLAD test with genuine outputs, not model files alone | HOLD |
| Local file | Audio/video import, entire-file preprocess mode, native playback, subtitles, exports, no overwrite | HOLD |
| Recording | DVB/Radio recording, AI sidecars, export, cancellation, safe non-destructive rollback | HOLD |
| Personal preferences | Privately compare caption reading settings, Qt QSettings, channel DB, locale, selected model paths, recording folders | HOLD |
| Lifecycle | Quit/Stop releases only app-owned workers; readsb, other SDR tools, model weights and recordings untouched | HOLD |
| Reproducible rebuild | Same source behavior across clean repeat installs; record compiler/dependency identities; binary hash comparison to private original where feasible | HOLD |
| Compliance | Kaffeine/Qt/GPL/SPDX and separately licensed model provenance | HOLD |

**AI models and private settings are NOT included in the public GitHub source
archive.** A clean machine cannot have identical AI operation just because its
app source builds: model weights, runtime dependencies, language packs, GPU
drivers, optional `welle-cli`/hardware and user-specific configuration must be
provisioned separately with consent. A source-preserving installer may offer a
read-only compatibility check and an explicit, local-only settings migration
plan; it must never upload, delete, replace, relocate or silently download
these assets. Preserve custom/external SSD paths and app ownership.

**Binary identity vs functional identity:** owner-reported local native binary
SHA-256 is recorded in the original `manifest.json`. Rebuilding source
with a different compiler/library/build environment can produce a different
checksum even when behavior is the same. Do not claim "bit-for-bit identical"
without an independent reproducible-build demonstration and exact matching
digests; *behavioral parity* needs recorded real TV/Radio acceptance evidence.

## Safe review procedure

1. Leave the owner's existing program and services running unchanged.
   Execute all installer/rollback tests in a disposable VM or isolated
   CI user HOME, never the owner PC.
2. Run the static source gate from the QA branch:
   `python3 -m unittest discover -s tests -p 'test_stable_first_*.py' -v`.
3. Test `--check` and `--dry-run` read-only. Review exact source SHA,
   upstream Kaffeine SHA, source-copy tree and packaged entrypoints.
4. Only on a disposable test machine, perform explicit install, functional
   tests and rollback. Verify that source and destination settings/recordings
   are unaffected; inspect stderr and logs without secrets.
5. Compare personal UI preferences and model path **locally**, on an
   explicitly authorized test. Keep private exports encrypted/off GitHub,
   report only a redacted pass/fail matrix publicly.
6. Require the owner's explicit GO before merging, tagging, making a release,
   sharing a one-line install command or modifying any current installation.

## Unresolved installation-specific gaps

- Installer PR currently selects a **separate preview launcher**
  (`tihulu-media-stable`) intentionally, not an in-place replacement of
  the existing `tihulu-media-center`. This separation is desirable for
  safety, but means it has NOT demonstrated an identical desktop environment.
- Source snapshot includes references to legacy TEXT CENTER paths; prove
  all call sites resolve within the staged release or to explicitly supported
  borrowed dependencies. A green C++ build does not prove ASR is functional.
- No automatic model/runtime or optional external DAB backend provisioning:
  distinguish "source is present" from "fresh installation works".
- No private local QSettings/profile export or model runtime parity validation
  has been completed. Do not assume fresh-install defaults equal the owner's
  custom choices.
- Native build + rollback CI green is an important engineering milestone, but
  does not validate physical receiver, CUDA model inference or original binary
  parity.

**Decision: HOLD** — do not advertise an identical one-line install yet.
