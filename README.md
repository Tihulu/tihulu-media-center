# TIHULU Media Center

Local-first TV, DAB+ radio and offline AI media center built on KDE Kaffeine.
Install with one line; no AI models are downloaded — AI stays optional and models
already on your machine are reused.

## Latest version

**v1.1-round3** — owner acceptance build.

```bash
curl -fsSL https://raw.githubusercontent.com/Tihulu/tihulu-media-center/v1.1-round3/versions/v1.1-round3/install.sh | bash
```

What it adds over the first stable baseline:

- **Playback uses the real AI services**: video files open the full TV caption
  window (Appearance, Source sync, Diagnostics, reading modes, speaker labels,
  model market, SRT recording), audio files get the radio karaoke/lyrics tools,
  and the existing whole-file transcribe is kept (batched, VRAM-bounded).
- **Video default**: embedded SRT (`.mkv` copy, selectable track); the covering
  caption band stays optional.
- **Stop** releases AI in every mode; every AI window has an explicit
  **Stop & Exit**.
- **Recording output formats**: MKV / `.m2t` / audio `.mka` / radio on a black
  video canvas, with subtitle generation after saving.
- **VLC surface**: embedded (default) or separate window, plus
  “Re-embed video surface”; optional **mpv** playback for local files.
- Market changes always refresh “Ready modes”, stale generated caption caches
  are pruned automatically, and Light/Dark appearance covers the new panels.

Full verification checklist: [versions/v1.1-round3/README.md](versions/v1.1-round3/README.md).

## Other versions

All published versions, including the rollback reference, are listed in
[versions/INDEX.md](versions/INDEX.md).

## About this repository

This branch preserves **source-only evidence** from the owner's on-device
TIHULU Media Center freeze. The running binary, private settings, recordings,
channel databases, model files and service secrets remain in the owner's local
private v3 archive, not in this public repository.

- `source/installed-package/`: TV/Radio AI and Media module code as installed.
- `source/worktrees/`: development checkout snapshots, including the Kaffeine
  patches.
- `manifest.json`: source provenance and reported executable hash.
- `versions/`: per-version installers and notes.

These are separate variants, not a proven single coherent build. Feature
branches/PRs must not silently replace the on-device snapshot.

Kaffeine remains KDE Kaffeine (GPL-2.0-or-later); attribution is kept in the
NOTICE/LICENSES files. Original project: https://github.com/KDE/kaffeine .
