# AI subtitle dropouts, real measurements and safe model optimization

## What 'Waiting for next live phrase' means

A TV caption starts with real MPEG-TS data, captures approximately six seconds
of speech, runs Whisper, optionally joins incomplete sentences and then
performs the selected translations. A natural sentence without punctuation
may be held for one additional clip (12 seconds maximum), rather than shown
as a false complete sentence. This is distinct from:
* **DVB continuity/audio PID gaps**: actual samples lost before Whisper.
* **Caption capture queue overflow**: raw clips could not be queued because
  the current decoder/translator cannot keep up with a sustained live feed.
* **Native video buffer confirmation missing**: decoded captions are now kept
  in a bounded 48-result pending queue until confirmed, instead of being
  thrown away on the first missing ACK. An extended absent ACK can still
  overflow or make a cue too late to display; no missing RF samples can
  be reconstructed from silence or a longer playback delay.
* **Whisper suppression, unsupported language or unavailable translator**:
  preserve original and display the real diagnostic rather than invent text.

EN+TR is **two** target-language translations after transcription, and may
cost much more with NLLB than with local Argos. For live ASR, translations
are now generated **once after full sentence assembly**, not once on each
raw partial clip and again after joining. Broadcaster Teletext translation
is not deferred. The source-language selector starts at Auto detect with
an English *interface preference*; this is not proof that unknown speech is
English. Actual language identification comes from the current broadcast's
DVB audio/Teletext descriptors or from Whisper.

## Test without changing settings

Under *TIHULU AI → Live Teletext / Whisper subtitles → Diagnostics & network*:

1. **Measure current live subtitle pipeline · 4 clips** listens to the
   existing local worker and measures actual compute, queue wait, dropped
   capture clips and native DVB TS discontinuities. Does **not** start a
   competing tuner, perform extra inference or change any AI/TV setting.
   Four six-second clips normally require ongoing live reception; if no
   real clips complete, the test says so instead of asserting success.
2. **Test installed AI models on a local audio sample…** requests your
   explicit consent and a **local** audio/video file of at least 6 seconds
   containing clearly audible speech. Its first six seconds are extracted
   privately with ffmpeg. Only installed verified CPU GGML and managed GPU
   model candidates are tried; Argos and an installed NLLB are timed
   independently for the DE→EN and DE→TR translations. Each subprocess
   is bounded by a timeout. No model downloads, web calls, SDR access
   or automatic changes; working NLLB weights are not assumed solely from
   the installed marker.
3. Review the actual measurements and an **editable** backend/model,
   translator and TV-buffer proposal. Click **Apply these settings (user
   approved)** to save chosen options. Cancel leaves original preferences
   untouched. An idle or speech-free sample cannot justify recommending a
   model; select a real speech sample instead. Background auto-sync never
   lowers the existing TV buffer.

## Offline command-line benchmark

The same user-approved benchmark is available without the GUI:

```bash
/usr/bin/python3 -m tv_center.performance_lab --audio "$HOME/Videos/sample.ts" --buffer-ms 14500
```

Use the `tihulu-tv-center` package's installed Python import path.
The report is printed as JSON to the terminal. It contains file/model paths
and timing data, so decide before sharing it. The benchmark **never**
applies proposed changes from this CLI.

The separate **Output languages** dropdown shows destinations provided by
locally installed Argos language packs and NLLB weights. The menu allows
multi-checking and refresh; package presence is not a promise that the
specific source→target translation succeeds. An explicit free-form advanced
language-code field remains available for users with custom packs.

## Known hardware limits

No CI runner can measure the user's installed RTX 5080 model timings, real
Hauppauge DVB-T2 RF losses, playback DAC timestamps, or continuous lip
synchronization. A successful six-second offline benchmark helps rank
candidates but is not an end-to-end TV guarantee. Installed AI backends
cannot be changed without explicit user approval. TV buffer changes alone
cannot repair dropped MPEG-TS packets, lost captures, or hallucinated speech.
