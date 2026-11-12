# AGENT 02 — MEDIA-REAL-HARDWARE-ACCEPTANCE-13

**Repository:** Tihulu/tihulu-media-center
**Baseline:** Draft PR #11 exact commit 2f5699eeb47505468bf3327be4dbdd89fed3dff1
**Frozen installed-source snapshot:** 7821769eb7aed576dd426ec18ffce3696d93a00d
**Existing exact-baseline CI:** https://github.com/Tihulu/tihulu-media-center/actions/runs/43196547501 — 2/2 jobs SUCCESS, 151/151 executions PASS.
**This branch:** isolated acceptance documentation; no production source, original installer or owner device changes.
**Decision:** RELEASE HOLD. CI software behavior is not an RF/hardware acceptance result.

## 1. Scope and evidence taxonomy

Target owner-controlled environment is Pop!_OS 24.04 COSMIC/Wayland with Hauppauge WinTV-soloHD DVB-T2 USB tuner (observed USB ID 2040:8268, Silicon Labs Si2168 D60 frontend) and NooElec NESDR SMArt v5 RTL2832U/R820T-family stick (observed USB ID 0bda:2838). These identifiers and earlier reported reception are **historical operator information**, not this agent's current machine/device observations.

The preserved application is a pinned KDE Kaffeine v2.0.19 fork plus installed Python TV/Radio AI companions. Native Kaffeine owns DVB scanning, frontend, video/Teletext and native TV recording. The TV caption worker consumes a best-effort copy of the selected transport stream; it must never claim the frontend itself. The native Radio tab starts its own welle-cli for DAB+ and rtl_fm for analogue, with explicit device ownership transitions. Device inventory and owner inspection are distinct from claiming/tuning a receiver.

Evidence levels:
- **SOURCE:** review of a real frozen source symbol, UI contract or docs. No runtime proof.
- **CI-SYNTH:** deterministic fixture tests, fake TS/audio text, compiled C++ helper, headless Qt. No RF proof.
- **CI-INSTALLED:** clean disposable native build and GUI/entrypoint smoke; no physical USB.
- **OWNER-READONLY:** owner-approved physical host inventory, filesystem metadata or passive owner inspection. No stream or RF lock proof.
- **OWNER-RF:** explicit owner-approved live tune/scan/record/recovery on physical equipment with measured evidence.
- **OWNER-AI:** approved real model inference, translation and audible content comparison using locally installed weights.
- **BLOCKED:** test not executed, no permission, no service, missing model, unsupported environment, or failure that precludes a meaningful result.

A fixture PASS must never be copied into OWNER-RF or OWNER-AI columns. Acceptance status starts NOT RUN for all physical tests. A test without a broadcaster providing the needed service is BLOCKED/N/A (with evidence), never PASS.

## 2. Critical safety invariants and release gates

1. **No owner machine operations in this task.** No software installation, uninstall, scanning, USB enumeration, process inspection, services, recordings, files or model access has occurred. The instructions below are proposals only and must not be executed until the owner authorizes the individual stage.
2. **Existing working Media Center untouched.** Do not overwrite system Kaffeine, existing Media Center launcher, ~/.config, channels, database, recordings or models. Never reuse legacy source/installed-package/kaffeine_next/install.sh or its historical curl-pipe-shell instruction to conduct hardware QA.
3. **SEC09 release HOLD remains.** PR #11 limits selected writable-parent and race problems, but independent review identifies possible remaining hostile same-UID filesystem races and non-atomic path operations. Real host installation, even a preview, is not approved by this plan and must wait for a separate security/owner decision.
4. **No forced hardware takeover.** Never auto-stop readsb/tar1090, gqrx, welle.io, TV recorders, rtl_fm or unrelated processes. No sudo, systemctl changes, USB unbind/reset, rmmod/modprobe, udev changes, killall, force-kill, or forced physical unplug.
5. **No secret/data uploads.** Device serial numbers, home paths, QSettings, tokens, raw recordings, station account data, private model paths and personal viewing history stay local. Publish only a sanitized pass/fail transcript and non-sensitive measurements. Do not place recordings in GitHub Actions artifacts.
6. **No autonomous AI downloads or network use.** Optional model inference uses already installed models only with owner permission. Online lyrics lookup and remote translation are OFF unless separately consented. No real broadcaster sample should enter synthetic CI.
7. **Dedicated test ownership and privacy.** If approval is eventually given, use a reviewed, independently safe install alongside the working application, a private temporary XDG/HOME profile (0700), and a uniquely named temporary output folder. Verify isolation before any scan or recording. A separate spare machine/receiver is preferred. Existing channels/database must not be rewritten.
8. **Abort on any unowned device, active recording or unknown path.** A "busy" frontend/SDR is a refusal case, not a reason to seize hardware. If unexpected file changes or service ownership changes occur, stop only the test-created process via its normal UI, preserve evidence and switch to HOLD.
9. **Never claim real lip sync from a requested cache.** TV playback buffer and radio network caching settings are requests; verify actual stream timestamps separately. A 100% progress bar or synthetic word anchors do not measure DAC/PTS.
10. **No merge, release, tag or published one-line installer** from this QA plan.

Authorization tiers:
- **C0 / CI:** public frozen source, fixtures, installed disposable Ubuntu runner, no hardware or models: allowed now.
- **C1 / owner read-only:** after explicit agreement: platform/driver USB ID, DVB/SDR paths/permissions, passive fuser PID ownership, existing application version/settings-location metadata (not secrets). May expose private local information and thus needs consent.
- **C2 / owner RF:** separate explicit agreement: launch *reviewed isolated* app, acquire a free tuner, tuning, channel scan in preview profile, DAB/FM playback, bounded local recording. Precondition: no conflicting receiver/recording.
- **C3 / owner disruptive:** separate explicit agreement at the moment: controlled signal attenuation/disconnect, stopping one's own test receiver, intentional contention with a voluntarily launched test process, tuner reconnect, sleep/resume. Never interrupt original readsb or an active TV recording.
- **C4 / owner AI:** separate agreement for existing local CPU/CUDA model inference, translator packs and optionally licensed lyrics lookup. No implicit license/copyright rights.

## 3. What PR #11 CI has actually established

The exact-baseline workflow succeeded with 105 source/security/AI fixture executions and 46 installed clean-build/GUI/runtime fixture executions across two Ubuntu releases (151 total). This validates installed bytes, certain Kaffeine/Qt controls, safe preview packaging, simulated Teletext/ASR routing, native C++ Radio reading-hold algorithm and deterministic negative tests. It does **not** validate Pop!_OS COSMIC/XWayland, Hauppauge Si2168 frontend lock, actual DVB HEVC playback, live subtitle PID/PTS, NooElec SDR contention, welle-cli DAB RF, real FM RDS, native Radio playback/mute, live recordings or Whisper/CUDA inference. Full security and licensing approval remain separate requirements.

## 4. Acceptance sequence — never skip gates

**Phase A — independent no-hardware audit (C0):** Freeze PR #11 SHA, require successful CI and zero difference from frozen source/installed-package. Check planned file paths/launchers and enumerate device ownership risk from source. Record all physical rows NOT RUN. No preview install.

**Phase B — explicit owner preflight (C1):** Owner confirms stable application runs normally, takes a private baseline of its launch location/version and high-level channel counts without exporting data. With approval, read-only hardware inventory identifies both USB products, kernel driver/firmware/frontend node, permissions and potential processes holding device nodes. Observe whether SDR is occupied by readsb or other programs. A connected USB alone is NOT a TV/DAB lock. If conflict exists, abort C2 and preserve existing process.

**Phase C — optional isolated test release (C2, gated on security approval):** Prefer separate disposable Linux machine and spare sticks. If owner later chooses the same PC, review installer and exact SHA, provision an isolated nonshared HOME/XDG profile, verify all launchers and QSettings point to the preview and not the working application. Confirm no model download and background receivers OFF. Preview and stable must not claim the same tuner simultaneously. Baseline restoration must be possible without touching stable settings.

**Phase D — TV actual RF (C2):** Native DVB frontend recognizes the currently configured correct terrestrial source. Begin with an already known, currently receivable channel rather than a full scan. Show measured lock/quality and sustained HEVC picture+audio. With permission, native full scan writes *only* preview channels and records real discovered SID/TSID/PLP. Exercise manual Teletext subtitle PID/page and all five caption modes, language selection, Comfort Reading, channel change within/among multiplexes, recording, replay, SRT closure on switch, EPG and volume. Do not treat unavailable broadcast Teletext as a decoder pass.

**Phase E — FM/DAB ownership (C2):** Without affecting readsb or any external SDR process, acquire the free RTL-SDR explicitly, tune an actually receivable FM station (historically WDR 2 Köln 98.6 MHz) and DAB ensemble (historically 5C/11D). Validate audio, mute/volume, RDS/DLS/DLS+ when supplied, explicit welle-cli/rtl_fm ownership, all Radio UI modes and clean release before switching app modules. Journaline is explicitly not implemented in the preserved read-only DAB bridge; do not mark it PASS.

**Phase F — AI and lyric evidence (C4):** Only after basic RF stability. Enable one already-present supported Whisper backend; verify real spoken TV/radio words against audible input, not mock captions. Test Teletext→Whisper fallback on genuine mismatch/unusable Teletext without falsely labeling translations as ground truth. Test original/translated DE/EN/TR with confirmed local packs; recording unchanged on model failure. Test DLS delayed/incorrect song, stale catalog and karaoke Refresh separately from AI Caption Refresh. Word highlights require actual recognized/aligned evidence; no synthetic word clocks.

**Phase G — recoverability (C3):** With explicit fresh permission and no active owner recording, introduce controlled weak signal/antenna attenuation, DVB busy attempt and RTL-SDR busy attempt **using only owner-approved test processes**. Verify graceful errors, no stale/cross-service subtitles, no forced device stealing, normal re-acquisition after releasing only the test-owned resource. Never disconnect a device that another process owns. Restore antenna/device and validate the previously working stable app if approved.

**Phase H — closeout:** Stop only test-created streams and workers using normal UI. Validate owned-process termination, preview profile isolation, no original config/channel/recording differences, and preservation of old readsb/service status. Do not run a broad uninstall automatically. Report actual device IDs (redacted serials), version/hash, timestamp, permission tier, which broadcaster content was available, result/elapsed time, any regression, recovery outcome and exact artifact link. An unchecked item remains HOLD.

## 5. Expected pass criteria and decision rules

- **P0 noninterference:** stable Media Center, existing channels, private profiles, recordings and SDR services untouched. Any violation is P0 FAIL and stop.
- **P0 hardware exclusivity:** one tuner owner per physical device, no surprise service stop/restart, owned processes released on normal close; busy hardware is reported without takeover.
- **P0 DVB behavior:** valid lock/service ID/transport ID and playable TV video+audio on actual tuner; no stale caption after retune, bounded on/off behavior and no old subtitle leakage into new TV/SRT programme.
- **P0 radio behavior:** real audible FM and DAB when current RF coverage supports them; no forced sharing of NooElec with readsb; accurate receiver/provider labeling, mute and volume work, independent UI from TV.
- **P0 preservation:** bounded test recordings, exported subtitles and AI failures never overwrite/delete existing files or silently change saved channels.
- **P1 subtitles/lyrics:** actual Teletext and Whisper fallback with corroborated audio, correct human-readable pacing; Lyrics ASR matching needs three distinctive spoken/sung lexical tokens and must never display wrong-song lines as verified. Delayed DLS metadata is a hint, not proof.
- **P1 environments:** Pop!_OS 24.04 COSMIC Wayland/XWayland with Qt5 and libVLC, NVIDIA/Conda environment checked; no Qt plugin contamination or crash; real model loading tested only when consented.
- **No universal invented SNR threshold:** site/antenna vary. Record receiver-reported lock, C/N/SNR, continuity errors, five-minute playback observations, three deliberate programme switches and documented any decoding stalls. Choose objectively repeatable local targets after baseline inspection.
- **Release GO requires** independent security+licensing review, complete P0 owner-authorized real hardware acceptance, documented model/inference limitations, no outstanding data-safety or coexistence violations, and explicit owner promotion approval. A passing CI or absence of equipment cannot satisfy these gates.

The authoritative case-by-case matrix, expected observations and evidence field template are in MEDIA_REAL_HARDWARE_CHECKLIST_13.md.

## 6. Unresolved blockers / priority

| Severity | Blocker | Why HOLD |
|---|---|---|
| P0 | Independent SEC09 full-security decision still pending | PR #11 itself acknowledges hostile same-UID and non-atomic filesystem windows |
| P0 | Actual owner-side side-by-side execution not authorized | No safe basis to install or claim either tuner |
| P0 | Stable binary/private channel database/settings parity unavailable publicly | Source parity and CI do not prove user-visible equivalence |
| P0 | Hauppauge Si2168 lock, DVB source config, HEVC, Teletext and recording on Pop!_OS unverified | CI uses no physical RF or GPU decoder |
| P0 | RTL-SDR sharing with readsb/gqrx and welle-cli/rtl_fm release unverified | Wrong start/stop could disrupt Flight Radar |
| P1 | Real RDS/DLS/MOT availability and broadcaster truth unknown | Metadata depends on actual broadcasters; Journaline not implemented |
| P1 | Real Whisper CPU/CUDA, Argos language pairs, Qwen word timing and Karaoke UX unverified | Fixture tests do not load model weights or hear speakers |
| P1 | COSMIC/Wayland Qt5/XWayland/libVLC hardware rendering and latency unverified | No calibrated video/audio/DAC clocks |
| P1 | GPL/SPDX/assets and optional model/lyrics licensing review not final | Do not publish a release |

## 7. Progress accounting

- Baseline exact SHA and CI: VERIFIED (151/151 PASS at PR #11, not rerun on owner hardware).
- Frozen source identity: VERIFIED in prior GitHub comparison; no protected installed-package differences.
- Source path and threat-scope inventory: DOCUMENTED.
- Real RF/driver/GUI/model tests: **0 physical tests run by this agent**.
- Side-by-side install/uninstall, tuner access, processes/services and private files: **0 operations performed**.
- Release: **HOLD**. This is planning readiness, not hardware acceptance percentage.
