# TIHULU Media Center v1.1-round3

Latest owner acceptance build: TV/radio AI captions, karaoke, recording with
output formats, local-file captions that reuse the real TV/Radio services,
VRAM-aware AI lifecycle and Light/Dark appearance.

## One-line install

```bash
curl -fsSL https://raw.githubusercontent.com/Tihulu/tihulu-media-center/v1.1-round3/versions/v1.1-round3/install.sh | bash
```

No AI models are downloaded; AI stays optional via the in-app market and your
already installed models are reused in place.

## What is in this version

- Playback: **full TV caption service** for video files, **radio karaoke/lyrics**
  for audio files, plus the existing whole-file transcribe (batched,
  VRAM-bounded).
- Video default delivery: embedded SRT (`.mkv` copy, selectable track); the
  covering caption band stays optional.
- **Stop** releases AI in every mode; every AI window has an explicit
  **Stop & Exit**.
- Recording output formats: MKV / `.m2t` / audio `.mka` / radio on a black
  video canvas; subtitles generated after saving.
- VLC surface: embedded (default) or separate window, plus
  “Re-embed video surface”; optional **mpv** playback for local files.
- Market changes always refresh “Ready modes”; stale generated caption caches
  are pruned automatically.

## Portable AppImage (optional)

CI builds a single-file AppImage on every push of this branch. Download the
`tihulu-media-center-portable` artifact from the latest successful run, extract
`tihulu-media-center.AppImage`, then:

```bash
chmod +x tihulu-media-center.AppImage
./tihulu-media-center.AppImage            # no installation needed
TIHULU_ASSET_HOME="$HOME" ./tihulu-media-center.AppImage   # reuse installed models
```

No AI models are bundled; the app starts without them and offers the in-app
market.

## Source of truth

Tag `v1.1-round3` in https://github.com/Tihulu/tihulu-media-center .

See the repository `versions/INDEX.md` for all published versions.
