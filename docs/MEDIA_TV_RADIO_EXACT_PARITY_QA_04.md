# MEDIA-TV-RADIO-EXACT-PARITY-04 — Installed behavioral QA

## Immutable provenance

Repository: Tihulu/tihulu-media-center.

- Baseline: safety Draft PR #5, exact commit e772a7bde546de178339dfce4592b9a9ee743218.
- Frozen installed-source snapshot: 7821769eb7aed576dd426ec18ffce3696d93a00d.
- This stacked QA PR only adds tests, a CI workflow and this report. No edits to installed-package, installer, snapshot, owner HOME, running tuner, model files, or settings.
- CI uses the SHA-pinned standalone installer in a disposable Ubuntu 24.04 HOME, without models or RF.
- The synthetic decoder data is NOT an actual DVB transport stream: injected Teletext and Whisper text validate genuine installed control paths and do not establish acoustic or live TS behavior.

## Executable acceptance scope

The test module tests installed RELEASE/py modules, NOT checkout code. It exercises real production implementations for:

1. Five TV caption modes, Off OSD semantics, manual page 777 and PID, on-screen style, source/target language controls, independent playback delay and subtitle offset.
2. Strict Teletext, Whisper-only, Auto probe, missing Teletext ASR fallback and recovery shadow under mocked decoder outputs.
3. TeletextAudit matching, same-language checks, three mismatch threshold, two recovery probes, missing broadcaster captions and reset for channel changes.
4. CueQueue stable readable phrase holds, chronological output, overlapping deduplication, offset retiming and channel reset; original and two languages rendered.
5. LiveSentenceJoiner continuation and reset, with no stale cross-channel carry.
6. LiveLyricMatcher wrong-song rejection, delayed DLS metadata treated only as hint, real recognized-text matching, same-verse suppression, refresh reacquisition, ambiguous repeated chorus safety and verified ASR-word anchor timing.
7. MusicSpeechRouter safe return to Whisper after radio presenter speech, plus alignment language fallback.
8. Native Radio reading hold: compile and execute exact C++ method radioCaptionReadingHoldMs from installed header against Qt5, with Live, Comfort, Relaxed, TV-style Adaptive, backlog and inference lag fixtures.
9. Real installed PyQt caption settings controller under Xvfb, enumerating real five-mode selector, manual page spinbox and Comfort Reading checkbox with private dummy AF_UNIX socket; no tuner data.
10. Source audit of AI Caption Refresh versus Karaoke Lip-sync Refresh isolation, and opt-in full-file transcribe default OFF. Both still need live GUI/user-interaction acceptance.

Original standalone tests and installed Kaffeine native smoke run unchanged.

## Acceptance matrix

| Area | Proved by successful CI | Remaining state |
|---|---|---|
| Source integrity and installed provenance | Frozen blobs and installed release equality | PASS only if green |
| TV five modes and native PyQt controls | Actual instantiated GUI, installed Python production dispatch with deterministic decoder inputs | HOLD real DVB/Teletext/Whisper |
| Comfort Reading, styles and offsets | Live production cue and OSD algorithms | HOLD native video/PTS measurement |
| Teletext mismatch, recovery, channel reset | Production audit and queue behavior under fixed fixtures | HOLD real channel/tuner transitions |
| Radio four reading modes | Actual installed C++ method compiled and executed with Qt | HOLD complete in-app Radio tab and DAB |
| Lyrics, karaoke, delayed DLS | Installed production matching, routing and timing functions | HOLD real song/audio verification |
| Two Refresh controls | C++ handler isolation evidence, Python routing | HOLD interactive native timeline |
| Local video/audio and full-file transcription | Source contract, opt-in OFF by default | HOLD actual file playback and model inference |
| Kaffeine native startup | CI native build and headless GUI smoke from earlier acceptance | HOLD real Pop!_OS and physical receiver |
| CUDA, Whisper inference, private settings | Not executed | HOLD |

## CI and release gate

Workflow path: .github/workflows/media-tv-radio-exact-parity-04.yml
Target branch: agent/media-install-safety-p0-20261112
Exact-head CI result: to be filled only after a verified run.

The workflow provisions throwaway Ubuntu dependencies, executes --check --no-ai then --install --no-ai, launches original runtime acceptance and new behavioral tests under D-Bus/Xvfb, and runs owned-only --uninstall (also attempted via EXIT trap). It does not use the owner's machine, download weights, start receivers, merge, or publish a release.

A failing, missing or queued CI is HOLD, not PASS. Even a passing synthetic CI is only installed software/algorithm evidence: full native playback, RF/ASR truth, DAC sync, real song recognition, translator and device integration require independent hardware tests. Overall release decision remains HOLD.
