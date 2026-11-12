# MEDIA-STABLE-FIRST-01 — auditable source installer (Draft only)

> **HOLD:** Source review candidate, not an authorized release or owner-machine
> installation. Never pipe an internet script into a shell. See Issue #1 and
> obtain approval after disposable install, rollback and RF acceptance.

## Exact source selection

| Component | Selected source | Identity |
| --- | --- | --- |
| TV AI, Radio AI, Whisper CPU/CUDA, translation, Teletext helpers | source/installed-package/tv_center | Pinned snapshot |
| FM/RDS, DAB, Radio/Text integration | source/installed-package/textcenter | Pinned snapshot |
| Native Media/Radio/recording Kaffeine patch and subtitles | source/installed-package/kaffeine_next | Pinned snapshot |
| KDE Kaffeine C++ base | KDE/kaffeine v2.0.19 | e7ea15b86dafed3b20b151cbcb080578ab8e2d5c |

Frozen snapshot commit: **7821769eb7aed576dd426ec18ffce3696d93a00d**.
Frozen snapshot tree: **d471b3aa4e546e8d790512df37fad763254023c6**.
Reported on-device binary SHA-256:
**1211bd5f8e16267d4b7f7b537f2b2c5c218b204d786c85fa6119a0f8ffa0d502**.

A successful reconstruction is NOT evidence of binary identity to that reported
private executable. Original manifest is kept with each staged release. Worktree
snapshots and historic install scripts are never used as source or executed.
KDE Kaffeine is cloned by tag but its exact commit is checked before any
transformation, and its upstream source is patched only in a disposable tree.

## Review and safe one-line invocation

After checking out the **Draft PR head** in an isolated review clone, inspect
the script and run dry-run or read-only check. A single local command is:

~~~bash
bash installer/media-stable-first.sh --dry-run --no-ai
~~~

The first real install command, **ONLY after independent approval on a
disposable test host**, is:

~~~bash
bash installer/media-stable-first.sh --install --no-ai
~~~

Do not run either on the owner's existing PC during this issue. A new checkout
can be prepared by GitHub's PR checkout UI, or through these review steps:

~~~bash
git clone https://github.com/Tihulu/tihulu-media-center.git /tmp/tihulu-media-review
cd /tmp/tihulu-media-review
git fetch origin refs/pull/PR_NUMBER/head:refs/heads/review-media-stable-first
git checkout review-media-stable-first
sed -n '1,300p' installer/media-stable-first.sh
bash installer/media-stable-first.sh --dry-run --no-ai
bash installer/media-stable-first.sh --check --no-ai
~~~

PR_NUMBER is intentionally not populated until the Draft PR exists.
Before a public one-line release command is promoted, publish an immutable,
owner-approved tag/commit and verify the installer and upstream digests.
**No curl-pipe-shell installer is approved.**

## Dependency, installation and rollback rules

- Linux Debian/Ubuntu/Pop!_OS only for the preview. The installer is never
  invoked as root. Check and dry-run only examine Git objects, OS and dpkg.
- The snapshot Git commit and full tree MUST match the declared hashes.
  A Git archive of only the installed-package variant is staged into a private
  temporary directory. No other TIHULU TEXT CENTER branch is downloaded.
- Missing Qt5, KF5, libVLC, DVB, ffmpeg and Python runtime/build packages
  block installation. APT may run only with explicit --allow-apt and a
  terminal confirmation requiring the literal INSTALL APT. It is not needed
  in read-only modes and never acts non-interactively.
- Native C++ compile uses distro Qt/KF5 under a sanitized environment. Python
  modules retain their snapshot identity. No automatic AI model download,
  Argos/Whisper provisioning, GPU/CUDA install, firmware, or welle.io build.
- A successful build is installed at:
  HOME/.local/opt/tihulu-media-stable/releases/VERSION/
  and a release-local binary SHA-256 plus provenance are saved.
- The existing system Kaffeine, ~/.config/kaffeinerc, DVB databases,
  frequencies, favorites, recordings, models, SDR services, and existing
  tihulu-media-center launchers are **not modified by the installer**.
  The isolated new launcher is HOME/.local/bin/tihulu-media-stable.
  The separately named desktop entry is tihulu-media-stable.desktop.
- Previous versions are kept. The owned current/previous symlinks are switched
  atomically with a user-owned flock. Rollback uses:

~~~bash
bash installer/media-stable-first.sh --rollback
~~~

- A first-install rollback deactivates only the owned current symlink. It
  does not erase releases or user content. System dependencies installed with
  explicit approval are NOT removed by rollback. No migration is performed.
- Runtime equivalence is unverified until installed tests. Kaffeine and
  companion process ownership require explicit receiver, cancel and shutdown
  acceptance, without competing for the tuner.

## Exact acceptance boundaries

| Gate | Pop!_OS 24.04 | Ubuntu 24.04 / Debian | Others |
| --- | --- | --- | --- |
| Source provenance and scripts | CI verification needed | CI verification needed | Unsupported |
| Bash syntax / shellcheck / Python compilation | CI verification needed | CI verification needed | Unsupported |
| Native Kaffeine build, isolated install and rollback | HOLD until green CI | HOLD until green CI | Unsupported |
| DVB-T2 tuning, Teletext, subtitles, recordings, stop | HOLD, manual RF | HOLD, manual RF | Unsupported |
| FM/DAB, Radio AI and audio stream continuity | HOLD, manual RF | HOLD, manual RF | Unsupported |
| CPU Whisper, CUDA/GPU, Argos translation models | HOLD, install acceptance | HOLD, install acceptance | Unsupported |
| Runtime and binary equivalence with owner's build | HOLD | HOLD | Unsupported |
| GPL/SPDX/attribution and bundled assets audit | HOLD | HOLD | Unsupported |

**Licensing:** Existing native patch header declares GPL-2.0-or-later. Original
KDE source and its dependency licenses/attributions must be retained. SPDX
review of the entire frozen Python, C++/Qt, JavaScript and icon payload remains
a separate release blocker; no licensing completeness is claimed by this PR.

**CI means source/build verification only.** Hardware, real FM/DAB, Kaffeine
DVB playback, Teletext/recording stability, model inference, GPU drivers and
binary identity require separate owner-approved installed acceptance. No
merge, stable tag, release, hardware action or installation on the owner's PC.
