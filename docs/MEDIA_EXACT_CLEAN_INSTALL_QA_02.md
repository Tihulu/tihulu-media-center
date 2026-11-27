# MEDIA-EXACT-PARITY-QA-02 — independent clean-install acceptance

**Status: HOLD; isolated QA only.** This document accompanies a new stacked QA
Draft PR. No changes to production source, installer, protected PR heads,
frozen snapshot, personal computer, TEXT CENTER, models or devices.

## Frozen exact inputs (2026-11-12)

| Provenance | SHA | Finding |
|---|---|---|
| Owner archived snapshot | 7821769eb7aed576dd426ec18ffce3696d93a00d | Immutable; stable-first is an archival label, not a release |
| Frozen Git tree | d471b3aa4e546e8d790512df37fad763254023c6 | Pin checked by installer |
| Installer Draft #2 | 0d99c126ba3e694378faa672424253d1793d95a2 | Exactly 9 commits ahead of frozen snapshot; merge-base equals snapshot |
| QA Draft #3 | 4c4d4cb96a6fccd2d19d7f901b46c3120cc5e6d0 | Exactly 3 commits ahead of installer; QA-only changes |
| Upstream KDE Kaffeine | e7ea15b86dafed3b20b151cbcb080578ab8e2d5c | Tag checkout SHA verified before patch |
| Owner reported installed binary | SHA-256 1211bd5f8e16267d4b7f7b537f2b2c5c218b204d786c85fa6119a0f8ffa0d502 | Private binary unavailable, no equivalence claim |

The installer uses a Git archive of **only** frozen
source/installed-package/{tv_center,textcenter,kaffeine_next}. It does not
substitute source/worktrees, current development PRs or legacy installers that
fetch unrelated repositories. The new tests verify every staged installed-package
file byte-for-byte in the actual versioned release; existing source-only tests
verify only selected critical source objects.

## CI before QA-02

- Installer #2 exact head: https://github.com/Tihulu/tihulu-media-center/actions/runs/43172480837
  source-and-syntax PASS; native-disposable-build PASS. Existing report:
  15 source/synthetic assertions; user-level install and first-release rollback
  in temporary HOME. No interactive TV or AI inference proof.
- QA #3 exact head: https://github.com/Tihulu/tihulu-media-center/actions/runs/43173175295
  frozen-feature-parity PASS. Source/synthetic tests only.
- Git ancestry: snapshot->#2 merge-base=snapshot; #2->#3 merge-base=#2.
  No source/installed-package changes in either later diff.
- QA-02 independent native/reinstall workflow results must be attached at
  their exact head. Earlier green jobs cannot establish QA-02 pass in advance.

## QA-02 workflow procedure (do not claim PASS before its run)

1. Run ALL unchanged test_stable_first_*.py tests plus Bash syntax and safe
   dry-run. Do not weaken earlier assertions to make CI green.
2. Install distro Qt5/KF5, VLC, DVB libraries, Python and Xvfb **on CI only**.
   Create an independent private CI HOME/XDG tree, with unrelated sentinel
   AI/channel/recording files and preservation checks.
3. Run --check then actual --install --no-ai in that disposable HOME. Check
   installed release manifest and EVERY frozen installed-package file's bytes.
4. Exercise installed Python imports from release/py, not from checkout; query
   installed tihulu-tv-center ai-radio-languages and ai-pairs commands.
   Model inventory may show NO MODELS. Presence is NOT inference proof.
5. Invoke installed native Kaffeine --version and a short Xvfb+D-Bus
   startup/stop smoke. This is not interactive sound/Teletext proof.
6. Run a second --install --no-ai, recheck runtime/bytes, assert distinct
   owned current/previous releases; --rollback to the earlier release.
   Preserve both releases and unrelated sentinel files.
7. Confirm --uninstall is unsupported and fails closed. Rollback alone
   does NOT meet full uninstall acceptance.

The checks do not touch a private computer, real DVB/SDR, readsb/tar1090,
firmware, model weights or an external SSD.

## Evidence and GO/HOLD matrix

| Gate | Current evidence | Verdict |
|---|---|---|
| Source provenance | Exact Git ancestry, archive pin, prior tests | Source provenance GO; installed bytes pending QA-02 |
| Native launcher and Python subprocess paths | #2 native build/install, QA-02 installed CLI/Xvfb checks pending | Installed process-launch PENDING; full GUI HOLD |
| TV Teletext->Whisper automatic fallback, broadcaster hard-only, Whisper-only, manual page, Off | Frozen source and synthetic checks | **HOLD** live mismatch, recovery, GUI |
| TV Comfort Reading, stable holds, languages, buffer, offsets and local-file preprocessing | Frozen source checks | **HOLD** actual audio synchronization/playback |
| Radio Lyrics, karaoke, independent synchronization, translations | Frozen code and pure lyric matching | **HOLD** heard ASR evidence, timing, re-sync, no false lyrics |
| Radio reading Live, Comfort, Relaxed, TV-style Adaptive | Four source presets | **HOLD** runtime display, timing, preferences |
| Five AI profiles: pi5, pi5_hat2, normal, performance, experimental | Profile declarations and selection code | **HOLD** applied models and active runtime |
| Whisper CPU/CUDA and Faster-Whisper | Staged modules, CUDA unprovisioned | **HOLD** actual inference and GPU identity |
| MADLAD, NLLB, Argos | Staged code, no model weights | **HOLD** real offline output and fallback |
| Settings / app identity isolation | Shared Qt names and default AI JSON path in frozen source | **HOLD** confirmed collision risk |
| DVB-T2, Teletext, FM/DAB, tuner ownership, recording and Stop | No real equipment | **HOLD** hardware and cleanup |
| Repeat install and rollback | QA-02 workflow pending | **PENDING** prior #2 only tested first-release rollback |
| Full uninstall | No --uninstall mode; only rollback | **HOLD** missing implementation |
| Exact Pop!_OS 24.04 / Debian native | Ubuntu runner is not either exact environment | **HOLD** separate disposable testing |
| Binary and private settings parity | Owner binary/settings/models not available | **HOLD** private owner-authorized verification |
| SPDX, GPL and third-party asset licensing | Some attribution identified; full audit incomplete | **HOLD** |

## Confirmed cross-app settings risk

A separately named tihulu-media-stable launcher is NOT a separate settings
profile. Native Radio QSettings uses organization TIHULU / app KaffeineRadio.
The caption app uses TIHULU / KaffeineCaptionAppearance. The Python TV/Radio
AISettings default is ~/.config/tihulu-tv-center/ai-settings.json. Native
Kaffeine also retains the upstream application identity and may encounter
an existing Kaffeine configuration. Thus a preview in the owner's existing
HOME could read or write the preferences of another installed application.
Separate application paths, QSettings namespaces and migration policy must
be validated without silently modifying the archived source.

## Hardware- or owner-only gates after separate explicit approval

- Fresh independent Pop!_OS 24.04 and Debian/Ubuntu homes/VMs with native
  install, GUI lifecycle, real rollback and safe uninstall.
- DVB-T2 scan, service switch, Teletext page/PTS mismatch, automatic transition
  to real Whisper, recovery, Comfort Reading stable hold, languages and buffer
  alignment against actual sound.
- FM/RDS and DAB/DLS, live decoded sound and Lyrics; no lyrics without heard
  Whisper evidence; Karaoke and AI Lip-sync Refresh stay independent; validate
  all four Radio reading presets and settings persistence.
- Local audio/video whole-file preprocess opt-in, independent timeline, saved
  subtitles, exports and unchanged source.
- Five AI profiles: verify actual selected engine and outputs, Whisper CPU,
  Faster-Whisper CUDA, GPU device, MADLAD/NLLB/Argos translation and model roots
  including external SSD. Model-file presence is never a pass for inference.
- Cross-app DVB/SDR process ownership and safe shutdown. No driver unbinding,
  global readsb shutdown or unsolicited tuner takeover.
- Private owner-approved local comparison of reported binary SHA, settings,
  channels, models, favorite lists, recorded media and UI preferences.
  Never upload private files or model weights to public CI.
- Complete KDE/Qt/GPL/SPDX and assets audit prior to any release.

**Final release decision: HOLD** until every behavioral gate is demonstrated
on installed runtime and the owner separately authorizes a release. Green CI
can promote only the exact gate it actually exercises.
