# TIHULU Media — First Stable

**Version:** 2.0.19-tihulu-custom  
**Preservation Date:** 2026-11-13  
**Status:** FIRST STABLE (Verified Local Backup Ready)  
**Repository:** Tihulu/tihulu-media-center  
**Status:** Draft PR #2, branch `agent/media-stable-first-01` (unmerged)

## What Is This?

This directory contains the verified archival record of the **only** customized
TIHULU Media installation that has been built, tested, and confirmed working on
the owner's Pop!_OS workstation. It preserves:

- The exact original ELF binary (`kaffeine`) with all TIHULU custom components
- The launcher script (`tihulu-kaffeine`) with environment configuration
- All application resources, icons, desktop entries, locale files
- SHA256 manifests for full integrity verification
- Installation, verification, restore, and rollback scripts

**This is NOT a development branch. This is the frozen baseline.**

## Contents

| File | Purpose |
|------|---------|
| `VERSION` | Version string |
| `README.md` | This file |
| `original-identity.md` | Binary identity verification data |
| `source-provenance.md` | Build provenance analysis |
| `runtime-dependencies.md` | System library dependencies |
| `installation-layout.md` | File layout and paths |
| `manifest.sha256` | Quick manifest (full in archive) |
| `install.sh` | Install from archive to isolated prefix |
| `verify.sh` | Verify archive integrity |
| `restore.sh` | Restore from archive to target prefix |
| `rollback.md` | Rollback procedure documentation |
| `acceptance.md` | QA acceptance criteria and results |
| `release-checklist.md` | Pre-release checklist |

## Quick Verification

> **Tool status:** the scripts in this directory are **owner-side tools** for the
> private FIRST STABLE archive layout. They resolve the archive at
> `../../archive` relative to their own location. The GitHub copy of this
> package is documentation/reference only — the archive (binary + share) is
> **not published** and requires separate explicit authorization. Run the
> commands below only inside the owner's archive layout.

```bash
cd /path/to/this/directory
sha256sum -c manifest.sha256
bash verify.sh
```

## Install (Isolated)

```bash
# Install to a custom prefix (default: ~/.local/opt/tihulu-kaffeine-first-stable)
bash install.sh
```

This installs to an isolated prefix and does NOT touch the live installation. Requires the
private archive at `../../archive` (owner-side layout); `restore.sh` refuses the live
installation path unless `--live` is explicitly passed.

## Platform

- **OS:** Pop!_OS (Ubuntu 24.04 LTS base)
- **Architecture:** x86_64
- **Qt:** Qt 5.x
- **DE:** KDE Plasma / COSMIC with X11/XWayland
- **Not portable** to other architectures or non-Qt5 systems without rebasing.

## GitHub Status

- Base branch: `agent/media-stable-first-01` (Draft PR #2); frozen snapshot branch: `stable-first-local-2026-11-12`
- PR: [Draft PR #2](https://github.com/Tihulu/tihulu-media-center/pull/2) — source/native CI green; real feature parity HOLD
- Package Draft: [Draft PR #25](https://github.com/Tihulu/tihulu-media-center/pull/25) (branch `docs/first-stable-archive-evidence-20261120`, base Draft PR #2 `agent/media-stable-first-01`)
- Binary NOT uploaded — requires separate explicit authorization
- Source provenance: HOLD (see `source-provenance.md`)
- Repository is PUBLIC; no merge/tag/release/install action from this package

## Safety

- This archive is read-only documentation
- Install scripts use isolated prefixes by default
- No sudo required for installation
- No system services modified
- Live installation (`~/.local/opt/tihulu-kaffeine/`) is never touched
