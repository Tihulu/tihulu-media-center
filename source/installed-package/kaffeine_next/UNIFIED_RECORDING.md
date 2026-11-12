# Unified recording · TIHULU Media Center (draft)

## Common player control

A persistent **● REC** button now lives in the bottom Kaffeine/libVLC
transport bar; when active it becomes **■ STOP REC**. The neighboring
**Recordings** button opens the saved-media library on every tab.

1. Open a playable local audio/video file, playlist item, direct Internet
   TV/IPTV stream, Internet radio station, verified DAB service, or native
   DVB-T2 TV station.
2. Click **● REC**. Choose a destination folder (default
   `~/Videos/TIHULU Recordings` when that is the system Movies folder),
   enable/disable **After recording, use local AI to generate subtitles**,
   select up to three translation languages, and optionally choose
   **Transcribe singing/music vocals too**. No AI is invoked before
   explicit confirmation.
3. Stop recording from the same bottom bar. The FFmpeg source capture is
   finalized with stdin `q` and an upper bounded shutdown fallback.
   Do not force-close the application until saving has completed.
4. Open **Recordings**. You can play saved audio/video or import another
   completed recording. Reopening will select the existing corresponding
   SRT sidecar automatically when available.
5. If you enabled AI, an offline `tihulu-tv-center media-captions` run
   starts AFTER the media has been saved. Existing AI Model Market
   Whisper/translator preferences are reused. It writes an SRT sidecar
   and an optional `-subtitled.mkv` containing a selectable subtitle
   track. If AI inference fails, the original recording remains intact.

## Recording capabilities and honest limitations

| Current source | Mechanism | Important limitation |
|---|---|---|
| Local video/audio file | Realtime FFmpeg copy of input from current player position into a new MKV | Captures **source timeline**, not on-screen overlays; pause/seek edits after starting do not affect capture |
| Playlist item | Current MediaSource URL tracked by Kaffeine | Only supported regular file or HTTP(S) URL types |
| Internet TV / IPTV | FFmpeg reads the currently selected HTTP(S) media URL | DRM/geo-restrictions/broken streams are not bypassed; only streams FFmpeg can decode/remux work |
| Internet radio | Same source-based FFmpeg capture | Saves audio in a MKV; speech and singing can later be processed with AI |
| DAB+ | Records already verified current local welle HTTP service URL | Never opens a second USB SDR; no guarantee if receiver service disappears |
| Analog FM / MW / LW | Bounded second localhost WAV/PCM stream subscriber; same `rtl_fm` samples as VLC | Requires a working RTL-SDR decoder and physical RF reception |
| DVB-T2 broadcast TV | Existing Kaffeine instant recording (native hardware ownership) | Kaffeine controls TV save location; after stopping use **Recordings → Import** to add the resulting video and optionally generate AI captions |
| DVD / optical disc / protected content | Explicitly unsupported via shared REC | No capture of DRM, libVLC menu compositions or decrypted disc content is claimed |

The shared record path records ORIGINAL source bytes/decodable input, **not**
the player's burned-in AI subtitle overlay. Offline SRT and selectable MKV
subtitle track preserve customization. Generating SRT does not invent
true word timing for models without word-level output.

The `-subtitled.mkv` is separately saved; existing output is never
overwritten. If it exists, only the SRT sidecar is retained. The app
keeps paths in per-user `TIHULU/UnifiedRecordings` settings and does not
copy/overwrite externally imported media.

On start, choose a destination with sufficient free disk space; recordings
can grow without bound until you press Stop or stream input ends. Network
records can differ from the decoded audio clock. Confirm legal rights to
record, retain and redistribute any broadcast or Internet content.

## Tests and release gate

- `tests/test_tv_unified_recorder.py`: central REC availability, DVB native
  ownership protection, source tracking, non-destructive output, analog
  fanout and reopenable record library checks.
- Native pinned Kaffeine and welle.io build CI validates C++ integration.
- Real USB receiver and local playback tests are still required,
  especially analog PCM fanout, stopped MKV integrity and DVB import.
- Keep PR #38 draft until real hardware validation. This is NOT an
  independent full-mix player screen recorder, universal DRM recorder, or
  network DVR with scheduled recording.
