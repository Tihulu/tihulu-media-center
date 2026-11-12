# TV channel transitions while the TIHULU caption settings are open

The **native Kaffeine player is the only DVB tuner owner**. The separately
started Qt/Python subtitle settings app is non-modal and never tunes the
receiver. A normal settings window has keyboard focus, so the new
**Back to TV · keep captions running** button minimizes this panel to give
channel hotkeys and the channel list back to the Kaffeine window.
**Hide settings** leaves the caption process running; **Stop subtitles**
pauses ASR; **Exit caption service** terminates the companion.

## Channel handoff

1. Patched native `DvbLiveView::playChannel` writes a bounded owner-specific
   `$XDG_RUNTIME_DIR/tihulu-tv-tune-$PID.txt` using Qt `QSaveFile`.
   Its three integers are the tune generation, DVB service ID (SID) and
   transport-stream ID (TSID). On Idle/Stop it writes SID=TSID=0. No
   caption process ever opens or takes the DVB tuner.
2. The sidecar polls the private marker within ~0.15-0.45 s while also
   listening for real MPEG-TS. Each generation invalidates pending ASR
   clips, previous overlapping audio, subtitle-track discovery and former
   source status *even when the next TV stream has not produced a PAT*.
3. The copied TS must supply a PAT matching the newly selected SID **and**
   TSID. Old socket datagrams and same-SID but different-TSID programs are
   discarded. Older Kaffeine hosts without the marker still use PAT
   program-ID discovery, but cannot guarantee prompt reset before PAT.
4. The GUI observes the sidecar's `program_epoch` and immediately clears
   old on-video captions, pending words, native Teletext/audio PIDs, ASR
   timing estimates and translated text; the existing user-selected
   output languages, appearance and buffer preference are retained. An
   old manually selected Teletext page reverts to Auto.
5. Every caption and discovered-track event carries an epoch. Results
   from a previous channel are rejected even if the GPU finishes them
   *after* tuning. The live SRT recorder closes the previous program's
   subtitle files at the switch, rather than mixing programs.
6. A paired mobile session's previous HLS stream and caption history
   are invalidated, too; phone HLS must be restarted deliberately.

Auto language stays **Auto**. DVB audio and Teletext descriptors for the
newly tuned channel are used as hints, without permanently writing a
former broadcaster's language into the user's source control. Explicit
manual speech-language choices remain manual.

## Verification

Run `python3 -m unittest tests.test_tv_channel_epoch -v` and the
project's normal tests. CI additionally builds the patched pinned KDE
Kaffeine C++ executable and its local AI companion.

Passing CI does not prove successful physical channel retuning or accurate
audio/video PTS on the user's Pop!_OS / Hauppauge DVB-T2 receiver. A real
test should keep the caption settings window open, switch between different
DVB services and multiplexes, observe old captions vanish, verify the
new SID/TSID in settings, and ensure captions resume when the new stream
has valid audio/Teletext; repeat with the panel minimized and phone HLS
opted in. If tuner acquisition itself fails, inspect Kaffeine's DVB source
config and tuner diagnostics separately.
