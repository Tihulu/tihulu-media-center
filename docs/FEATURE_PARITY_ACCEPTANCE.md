# MEDIA-STABLE-FIRST-01 — feature parity and acceptance gates

This Draft PR preserves a source-only on-device snapshot. A **source match
does not certify live hardware, private preferences, model execution, or
equivalence with the owner's compiled binary**. All tests use only GitHub CI
runner/disposable synthetic data.

| Area | Frozen-source identity | Structural/synthetic CI | Installed parity | Remaining GO gate |
| --- | --- | --- | --- | --- |
| TV Teletext→Whisper auto fallback; Teletext-only; Whisper-only; manual page; off | Verify full frozen captions_overlay.py blob | Verify all five GUI options, fallback state and comfort/speech defaults | **HOLD** | Real DVB service, missing/mismatched Teletext, program switch, language/translation |
| TV Comfort reading, stable hold, speech priority, buffer/offset | Frozen caption_timing.py and overlay unchanged | Check comfort default ON, speech-priority OFF and buffer increase-only label | **HOLD** | Real stream, display pacing/anti-flash, offset and delayed words under load |
| AI profiles pi5, pi5_hat2, normal, performance, experimental | Frozen model/settings code unchanged | Parse profile definitions and check backends, translation, select/install distinction | **HOLD** | Real model inventory, no preview writes, explicit apply, CPU/CUDA fallback |
| Local video/audio whole-file preprocessing | Frozen native media header unchanged | Check user opt-in default false and separate local-media QSettings | **HOLD** | Real video/audio file pre-process, generated captions and playback handoff |
| Radio reading presets: Live, Comfort, Relaxed, TV-style Adaptive | Frozen native radio C++ header unchanged | Verify four GUI choices and saved default preset 3 | **HOLD** | Read-hold timing, no retune/buffer theft, user control persistence |
| Radio Lyrics provider/ASR synchronization and karaoke | Frozen radio AI, Lyrics and C++ headers unchanged | Pure no-hardware Qwen/Whisper fallback synthetic test | **HOLD** | Real DAB/recording, lyric evidence/threshold, tempo, language switch, Stop |
| FM/DAB, recording, native Kaffeine player/Teletext | Frozen decoder/native patch/header blobs unchanged | Source and Kaffeine C++ compile in CI; no device opened | **HOLD** | Independent live receiver, EPG, scan, recordings, frontend release |
| Private TV/Radio QSettings and custom installed models | Not contained in public source snapshot | Verify manifest explicitly excludes private settings/models | **HOLD** | Separately authorized local export/import with private checks, if wanted |
| Compiled binary identity | Only original binary SHA-256 reported in manifest | CI saves new build hash; no attempt to claim equality | **HOLD** | Secure binary/hash comparison only with owner's approval |

## Automated tests

Run: python3 -m unittest discover -s tests -p 'test_stable_first_*.py' -v

- test_stable_first_contract.py: pinned source, consent, no-write dry-run,
  shell syntax, temporary-home rollback.
- test_stable_first_mode_parity.py: frozen Git blob identities for 18 critical
  modules, TV mode/comfort/UI defaults, five AI profile definitions, Radio four
  presets/default, local preprocess opt-in, pure karaoke fallback, and explicit
  absence of private preferences in public snapshot.

## Hard source and runtime limits

All archived source variants retain provenance; do not mix experimental
source/worktrees changes or TEXT CENTER development branches. The initial
installer preview runs as a distinct user-owned application and does not
auto-start SDR, tune a DVB frontend, download AI weights or migrate preferences.

The dedicated preview launcher uses the same KDE application identity in the
native source. **Concurrent native instances and per-user KDE QSettings
separation require manual verification**; no claim is made that every runtime
GUI preference is isolated from the owner's current installed instance.
This is a blocker for installation on the owner's machine.

No root installation, hardware probe, merge, release, stable tag or generalized
one-line download command is authorized. Every currently unverified runtime
area remains HOLD until isolated clean-room and owner-approved acceptance.
