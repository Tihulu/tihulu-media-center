# Round-3 owner feature guide

Round-3 keeps the earlier stable baseline and adds the owner's requested
behaviour. Every item below is implemented in the candidate preview:

```
"/home/horseman/tihulu apps open code/media stable first/acceptance-owner-round3/start-fixed"
```

## Local files use the real caption services

| File type | What you get | How to verify |
|---|---|---|
| Video | The **full TV caption window** (Appearance, Source sync, Diagnostics, reading modes, speaker labels, model market, SRT recording, translation failover) | Drop/open a video -> panel shows "TV caption service" -> press **AI captions panel** |
| Audio | The **radio caption settings** plus a **Karaoke / lyrics** action (time-coded lyrics from a local `.lrc` beside the file, or an explicit LRCLOU lookup) | Open an audio file -> panel shows "Radio caption service" -> press **Karaoke / lyrics** |
| Either | **Whole-file transcribe** as before, with real progress (read -> translate -> save) | Press **Transcribe file** |

- Video default delivery: `<name>-subtitled.mkv` (original untouched, SRT as a
  selectable track). The covering caption band stays optional.
- **Live buffer** (2-20 s) controls the audio window the speech model sees.
- Settings popup keeps running when closed; only **Turn off subtitles & exit**
  releases the AI work.

## Stop really stops the AI

The player **Stop** (toolbar, Backspace, playback end, playlist next) now:

1. stops recognition,
2. clears the caption queue,
3. closes resident Whisper/translator workers (VRAM is released),
4. reports exactly what was released in the panel.

Every AI window has an explicit **Stop & Exit**.

## Recording

Record dialog output formats: **MKV (default)**, broadcast **`.m2t`**, audio-only
**`.mka`**, and **video on a black canvas** for radio (so radio can be recorded
like TV with subtitles). After saving you can generate subtitles in the chosen
IN/OUT languages and local model, and the result is embedded as a selectable
track. Recordings (all formats) are listed under **Recordings**, and importing
also offers `.mka`.

Playing a recording attaches its sidecar `<name>.srt` and selects our generated
subtitle track automatically.

## Video surface (VLC)

Settings -> **Video surface**: `Embedded in window · default` or
`Separate window · VLC creates its own`. If a stray VLC window ever appears,
Video menu -> **Re-embed video surface** rebinds it.

## Optional mpv for local files

Settings/panel -> **Play local files with mpv (external player)**. Local
video/audio then opens in mpv with its subtitles; TV, radio and streams keep the
built-in VLC engine.

## Market and defaults

- Installing or removing a model/pack always refreshes the **Ready modes** page.
- Radio captions use an already installed local speech model in memory (no
  download, no settings write) and only ask for the AI Market when nothing is
  installed.
- Stale generated SRT caches are pruned on every caption session (14 days);
  your own files beside the media are never touched.

## Memory behaviour

- Mode/channel change and player Stop release models; nothing idles on VRAM.
- Whole-file translation releases accelerator memory every 25 cues and prefers
  the CPU translator when free VRAM is below 3 GiB (meaning is never split).

## Appearance

The local AI panel, caption band and radio captions follow the selected
Light/Dark theme.
