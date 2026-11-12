# TIHULU Media Center — Local Stable-First source snapshot

This branch preserves **source-only evidence** from the owner's 12 November 2026
on-device TIHULU Media Center freeze. The running binary, private settings,
recordings, channel databases, model files and service secrets remain in the
owner's **local private v3 archive**, not in this public repository.

## What is here

- `source/installed-package/`: the TV/Radio AI and Media module code *as
  installed* in the `tihulu-tv-center` package, selected from a frozen archive.
- `source/worktrees/`: distinct local development checkout snapshots,
  including Kaffeine patches and uncommitted working-tree source changes.
- `manifest.json`: source provenance and reported executable hash.

These are **separate variants**, not a proven single coherent build. GitHub
feature branches/PRs must not silently replace the on-device snapshot.

## Critical status

This is NOT YET a one-line installer or tested stable release. The binary/source
match, packaging dependencies, live TV/DAB, Whisper/CUDA/Radio AI and complete
shutdown resource release require validation before publishing an installer.

Preserve upstream KDE Kaffeine attribution and GPL licensing. See original
project: https://github.com/KDE/kaffeine .

This snapshot intentionally excludes personal files, credentials, and models.
