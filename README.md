# TIHULU Media Center

Local-first TV, DAB+ radio and offline AI media center built on KDE Kaffeine.
Install with one line; no AI models are downloaded — AI stays optional and models
already on your machine are reused.

## Version in this branch

**v1.0-stable-baseline** — owner-quoted stable reference, kept for rollback.

```bash
curl -fsSL https://raw.githubusercontent.com/Tihulu/tihulu-media-center/v1.0-stable-baseline/versions/v1.0-stable-baseline/install.sh | bash
```

What it contains:

- The verified installed-package baseline plus the owner's earlier acceptance
  fixes: T2 terrestrial source default, Light/Dark appearance, software playback
  profile, radio/DAB integration, shared Record/Recordings bar, and the two
  fixes from the owner's quoted run (`json` import, `new_audio` reference).

## Other versions

All published versions, including the newer owner acceptance build, are listed in
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
