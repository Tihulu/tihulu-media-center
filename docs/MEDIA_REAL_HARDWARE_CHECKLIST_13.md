# AGENT 02 — MEDIA REAL-HARDWARE ACCEPTANCE CHECKLIST 13

**Immutable source baseline:** PR #11 at 2f5699eeb47505468bf3327be4dbdd89fed3dff1
**Frozen package:** 7821769eb7aed576dd426ec18ffce3696d93a00d
**Owner environment (unverified by this agent):** Pop!_OS 24.04 COSMIC Wayland; Hauppauge WinTV-soloHD 2040:8268 (Si2168-D60), NooElec NESDR SMArt v5 0bda:2838
**Status:** RELEASE HOLD. Baseline historical CI: 151/151 PASS; **zero owner-hardware cases executed**.
**Companion plan:** MEDIA_REAL_HARDWARE_ACCEPTANCE_13.md

## Checklist rules

Statuses must be one of NOT RUN, PASS, FAIL, BLOCKED, N/A. The owner or independent hardware tester records a fresh status and evidence only after the relevant authorization. Never mark PASS from file presence, test doubles, source text, historical signal reception or absent failure messages. N/A must give a reason and still cannot satisfy a mandatory P0 gate. Preserve originals; only use approved temporary test profile/output paths.

A failure in any P0 preservation/ownership case immediately stops all active tests and blocks release. A busy original tuner, live readsb SDR owner, or ongoing recording is **BLOCKED**, not permission to force-stop it. Never run physical device tests from GitHub Actions. No automated full scans or RF tuning before explicit owner approval.

## Phase gates (must be checked in sequence)

- [ ] Gate G0 — independent security review of PR #11 concludes private preview can be safely staged; exact commit and license constraints reviewed.
- [ ] Gate G1 — owner explicitly approves C1 passive device inventory (not inference, processes or live streaming by default).
- [ ] Gate G2 — owner explicitly approves reviewed isolated C2 preview setup; stable program/launcher/config/channel database protected.
- [ ] Gate G3 — separate owner confirmation for each physical tuner claim/scan/recording; no conflicting receiver or TV recorder.
- [ ] Gate G4 — separately approve C3 disruptive tests; no original live session or device can be unplugged, stopped or seized.
- [ ] Gate G5 — separately approve C4 real AI model inference and optionally legally licensed lyrics/network lookup.
- [ ] Gate G6 — complete final privacy/restoration review; owner authorizes any future promotion separately.

## Test matrix — evidence and exact expected behavior

Legend: C0=offline disposable CI, C1=owner-approved passive inspection, C2=owner-approved RF operation, C3=owner-approved disruptive recovery, C4=owner-approved real AI. All real hardware rows below start NOT RUN.

| ID | Tier | Priority | Procedure and expected observation | Initial status |
|---|---|---|---|---|
| CI-01 | C0 | P0 | Compare frozen commit to selected installed-package tree; exact zero changed source blobs | PRIOR CI PASS |
| CI-02 | C0 | P0 | Run pinned PR #11 Ubuntu 24.04 safety/native fixture workflow; 105 + 46 executions, 2/2 jobs; no hardware claims | PRIOR CI PASS |
| CI-03 | C0 | P0 | Verify security TODO list and source/installer origin SHA; unresolved same-UID TOCTOU risk is recorded as HOLD | HOLD |
| PRE-01 | C1 | P0 | Identify launch/version of working stable app *without modifying it*; private baseline includes count of channel/favorites/recording files, not contents | NOT RUN |
| PRE-02 | C1 | P0 | Verify host release, COSMIC Wayland/XWayland, Qt5, libVLC, runtime library conflicts, installed preview paths; no interference with stable app | NOT RUN |
| PRE-03 | C1 | P0 | Passive USB inventory: 2040:8268 and 0bda:2838 if connected; distinguish USB presence, /dev/dvb frontend registration, claimed owner, and RF lock | NOT RUN |
| PRE-04 | C1 | P0 | Passive ownership: optional fuser for frontend/SDR, inspect readsb/gqrx/welle owners without stopping anything; record busy/unknown as BLOCKED | NOT RUN |
| TV-01 | C2 | P0 | Explicitly launch reviewed side-by-side preview; no background tuner/model on startup; existing stable UI/settings untouched | NOT RUN |
| TV-02 | C2 | P0 | Native Kaffeine TV Source matches terrestrial DVB-T2; no mistaken DVB-C or No Source; preview channel database only | NOT RUN |
| TV-03 | C2 | P0 | Tune known live service first; actual frontend LOCK and consistent SID/TSID from current TS; no synthetic channel row | NOT RUN |
| TV-04 | C2 | P0 | Live video/audio (including broadcast HEVC where applicable) plays for ≥5 minutes; log audio/video stutters, continuity errors, C/N/SNR measured by receiver if available | NOT RUN |
| TV-05 | C2 | P0 | Explicit native full antenna scan, not Python/WebUSB scanner, finds live service tables; record actual found frequencies, channels, PLP and no silent writes to old DB | NOT RUN |
| TV-06 | C2 | P1 | Native channel list, favorites, EPG and selected service survive preview restart; original channel/favorites DB unchanged | NOT RUN |
| TV-07 | C2 | P0 | With broadcaster subtitle service available, use correct Teletext PID and page; original output visibly corresponds to tuned programme and language | NOT RUN |
| TV-08 | C2 | P0 | Five modes Off, Teletext Hard, Whisper only, Teletext→Whisper Auto and manual Teletext page; Off makes no caption output or ASR work; no fabricated teletext | NOT RUN |
| TV-09 | C2+C4 | P0 | Actual Teletext/audio disagreement or missing text triggers genuine ASR only when permitted; repeated conflicts then recovery; no unrelated old subtitle retained | NOT RUN |
| TV-10 | C2 | P0 | Switch three times, including within one multiplex and across different TSIDs; stale caption/translated words/PIDs reset, no old-channel SRT continuation | NOT RUN |
| TV-11 | C2 | P0 | Start a bounded 60s native DVB recording in a new unique preview folder, stop normally, verify nonzero playable file and A/V; never overwrite existing media | NOT RUN |
| TV-12 | C2 | P0 | While recording, TV stop/release/scan must protect active recording rather than forcibly take frontend; no truncation or unexpected retune | NOT RUN |
| TV-13 | C2 | P1 | Caption appearance and positive/negative offsets change only subtitles, not tuner/audio; requested vs actual buffer and lip sync explicitly separated | NOT RUN |
| RAD-01 | C2 | P0 | FM station on free RTL-SDR (historically Köln 98.6 MHz; select actually receivable station), audio audible and correct selected frequency label | NOT RUN |
| RAD-02 | C2 | P0 | FM volume and mute across native Radio UI, spectrum/VU label honest (PCM VU is not RF SNR), no phantom sound after STOP | NOT RUN |
| RAD-03 | C2 | P1 | Broadcast FM RDS/RadioText/RadioText+ fields when transmitted; label provenance, do not fabricate missing text | NOT RUN |
| RAD-04 | C2 | P0 | Start authorized welle-cli DAB on available ensemble (historically 5C/11D); decoded service IDs and audio correctly match selected channel | NOT RUN |
| RAD-05 | C2 | P1 | DAB DLS/DLS+ and MOT slideshow, when available, show correct station and acquisition age; Journaline remains unsupported in preserved bridge | NOT RUN |
| RAD-06 | C2 | P0 | Native Radio DAB/Internet/analog selection works without relaunching TV or hidden receiver; playback mute, station/source label and favorites stable | NOT RUN |
| RAD-07 | C2 | P0 | Explicit FM↔DAB switching releases prior TIHULU-owned RTL-SDR worker before next starts; never starts two USB owners for one stick | NOT RUN |
| RAD-08 | C2 | P0 | TV↔Radio transitions do not steal active DVB or RTL-SDR; active TV recording veto honored and no unrelated readsb/tar1090 changes | NOT RUN |
| RAD-09 | C2 | P1 | Four Radio reading presets Live, Comfort, Relaxed, Adaptive have recognizable stable phrase holds and responsive mode switching under real speech | NOT RUN |
| RAD-10 | C2 | P0 | Bounded approved FM/DAB source recording captures actual program and reopens cleanly; no recording of stale/wrong station | NOT RUN |
| RAD-11 | C2 | P0 | STOP/Exit returns owned receiver to idle; no zombie welle-cli, rtl_fm or orphan audio; reopening a free device works without reboot | NOT RUN |
| AI-01 | C4 | P0 | Already-present local Whisper CPU backend loads and transcribes audible TV/radio speech accurately enough to confirm source; missing model is explicit BLOCKED | NOT RUN |
| AI-02 | C4 | P1 | CUDA on NVIDIA is tested only when compatible installed runtime/weights exist; compare actual word/timing results, no fallback claimed as GPU success | NOT RUN |
| AI-03 | C4 | P1 | Installed local translation packs for DE/EN/TR produce nonempty language-appropriate outputs and preserve original words if translation unavailable | NOT RUN |
| AI-04 | C4 | P1 | Comfort Reading resists 150–300ms flashing and preserves complete phrases on real 6s chunk boundaries, including rapid channel changes | NOT RUN |
| AI-05 | C4 | P1 | DLS delayed/incorrect song or wrong catalog does not verify lyrics; right song requires heard recognizer evidence; repeated verses not blindly seeked | NOT RUN |
| AI-06 | C4 | P1 | Karaoke word anchors require actual ASR/aligner words; AI Caption Refresh alters speech timing only, Karaoke Refresh affects lyric track only, no fake PTS | NOT RUN |
| NEG-01 | C3 | P0 | Deliberate weaker TV signal/controlled attenuation after normal recording stop: no crash or cross-program captions, clear no-lock and recoverable retry | NOT RUN |
| NEG-02 | C3 | P0 | Deliberately busy DVB with a voluntarily owned test process: preview refuses claim; no killing/retuning foreign owner; retry succeeds after test release | NOT RUN |
| NEG-03 | C3 | P0 | Deliberately busy RTL-SDR with voluntarily owned test process (or observe existing readsb without disrupting it): DAB/FM fails closed, existing service remains unchanged | NOT RUN |
| NEG-04 | C3 | P0 | Controlled antenna disconnect/reconnect or approved removal of idle test-only SDR: no worker crash cascade, accurate state and manual reacquisition | NOT RUN |
| NEG-05 | C3 | P1 | Stop only test-owned welle-cli during an idle test session; UI reports local receiver unavailable, no fabricated DAB data; explicit restart recovers | NOT RUN |
| END-01 | C1+C2 | P0 | Exit test app via its own UI; verify only preview workers ended and readsb, stable Kaffeine, saved services/settings/recordings not changed | NOT RUN |
| END-02 | C1 | P0 | Written owner-reviewed privacy cleanup and restoration evidence; do not uninstall automatically, delete models or remove anyone else's files | NOT RUN |

**Count:** 41 owner-action test rows PRE-01–04, TV-01–13, RAD-01–11, AI-01–06, NEG-01–05 and END-01–02. **Verified by this agent: 0/41.** C0 history is independently verified from GitHub but not evidence of owner hardware acceptance.

## Proposed exact operator procedure (NOT executed or authorized)

### Preflight (C1, read-only only, after owner approval)

1. Close no processes automatically. Ask the owner whether the stable application is actively playing/recording and whether readsb/tar1090/gqrx is currently using the NooElec stick. If so, reserve an independent time or spare receiver rather than stopping it.
2. Record date/time, display session, driver and USB product identity. Example passive commands that the owner may run after approval:

       cat /etc/os-release
       echo "$XDG_SESSION_TYPE"
       lsusb -d 2040:8268
       lsusb -d 0bda:2838
       ls -l /dev/dvb/adapter*/frontend* 2>/dev/null

   The shell expands /dev/dvb only if nodes exist. No device RF lock is implied.
3. Separate additional owner authorization is needed to inspect process owners:

       fuser -v -- /dev/dvb/adapter0/frontend0

   Device node may differ. SDR USB node path must be discovered from *that* host; do not guess or run privileged global scans.
4. Do not call the old install.sh or any curl|bash command. Review and approve any proposed preview build, explicit temporary HOME/XDG and launch path before running even a dry-run. No generated command here is permission to install.

### First physical TV session (C2, only after the full security/install gate)

1. Launch only the signed-off side-by-side preview entrypoint; ensure no tuner claimed just by opening Start/Hardware. Check read-only source/device/status first.
2. Select one already stored TV service in preview, check Source matches DVB-T2 and actual lock, record real displayed SID/TSID and frontend quality. Observe for five minutes. Capture statistics in private notes; do not upload raw transport data.
3. Only with explicit permission, perform a **native scan in preview** using current regional source (historical tests included 538/586/626 MHz, which are neither a guarantee nor a universal regional plan). Verify native channel list, never silently import into real stable list.
4. If and only if the broadcaster transmits a subtitle page, exercise real Teletext Hard and manual page; then already-authorized ASR in Auto/Whisper and the human-readable hold. Switch services three times and observe stale captions cleared.
5. Record a new 60-second sample under a uniquely named preview destination; use native DVB recording path, finalize normally and play locally. Do not remove it automatically. Test scan/stop prevention during recording.
6. End TV with native Stop/Release when no recording is active, verify frontend ownership is released to idle. Only then consider Radio.

### First physical Radio session (C2, only with free NooElec receiver)

1. Start in Radio on a real station with prior operator-tested FM/DAB values as suggestions only; if readsb/gqrx currently owns RTL-SDR, do not start it. Confirm owner clearly labeled TIHULU and no competing worker.
2. Validate FM audio/mute and RDS when broadcast. Stop and release only the owned FM worker. Start DAB on a currently receivable ensemble and validate actual DLS metadata, audio, slideshow only if supplied.
3. Switch between FM/DAB/Internet, note recording state, ensure former local worker exits before next. Compare all four reading presets with *heard* speech; distinguish cached/estimated latency from speaker output.
4. Only with C4 authorization, test local Whisper/translation and lyric song-match verification. Never assume DLS artist/title is acoustic evidence.
5. Stop owned welle-cli/rtl_fm through app UI and check no leftover test-owned devices. Do not stop preexisting readsb/tar1090.

### Disruptive fault session (C3, fresh authorization)

1. Use a harmless attenuator/reposition **only when no recording**; avoid USB hot-unplug as the first fault. Observe real lock loss, interrupted service/UI status and restoration on returning a good antenna.
2. Use only voluntarily created, clearly owned disposable conflict processes. Record whether the preview correctly refuses a busy tuner without stopping the holder. Never use sudo, killall, systemctl stop, rmmod or bus unbind.
3. Only if the owner explicitly authorizes a physical unplug/replug of an **idle, test-owned** SDR, repeat. Its appearance and recovery must be unambiguous; a missing USB device isn't a failed antenna reception.
4. Check native channel switch and cue reset after recovery. No previous broadcaster caption may appear as current, and old SRT cannot silently continue into new programme.
5. Restore hardware and antenna. Reconfirm stable application state only with the owner's permission.

## Acceptance observation record

Fill for every executed test; omit private content from GitHub:

    TEST_ID:
    Date/time and timezone:
    Operator approval tier (C1/C2/C3/C4):
    Exact preview commit and verified launcher:
    Pop!_OS / kernel / display protocol:
    Device model and VID:PID (serial REDACTED):
    Frontend/SID/TSID or SDR decoder and station (if authorized):
    Baseline state and owner PID disclosure policy:
    RF/signal and decoder metric (measured, not estimated):
    Expected vs actual:
    Timings (capture/ASR/render; DAC clock UNMEASURED if unavailable):
    Evidence links (sanitized logs only; no private media):
    Test-created files/processes:
    Restore result and original stable app untouched check:
    Verdict (PASS/FAIL/BLOCKED/N/A):
    Blocker/issue number:
    Reviewer and owner signoff:

## Final acceptance and stop controls

- [ ] Every required P0 physical row PASS on actual target host or documented equivalent owner-approved representative equipment; N/A is not a P0 pass.
- [ ] No original Media Center or private settings/channel/recording data modified; no unapproved tuner/service interruption.
- [ ] Native TV scan/play/record and FM/DAB play/stop are reproducible after restarting only the preview.
- [ ] Teletext/Whisper and Lyrics/Karaoke claims are backed by actual broadcasts and existing approved models, not fixture transcripts.
- [ ] Every deliberate fault test has an observed recovery path and accurate no-signal/busy status; no unsafe privilege escalation.
- [ ] Independent security, licensing and owner release approval are separately complete.
- [ ] No residual P0 bug; full real-hardware acceptance report reviewed.

**Current verdict: HARDWARE HOLD / RELEASE HOLD.** The only preexisting PASS evidence is the pinned synthetic and installed CI, not physical acceptance.
