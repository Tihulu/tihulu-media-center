# MEDIA-FINAL-COMBINED-INTEGRATION-P0 — isolated acceptance

**Release verdict: HOLD.** This document is for a new *stacked Draft PR only*, not a release, stable tag, public installer or automatic update.

## Immutable provenance

| Role | Commit / source |
|---|---|
| Frozen source archive | `7821769eb7aed576dd426ec18ffce3696d93a00d` |
| Base safety PR #5 | `e772a7bde546de178339dfce4592b9a9ee743218` |
| Independent rollback fix PR #6, integration parent | `a63535040edbcfc83e8032124fa3834e1fd60d44` |
| Installed TV/Radio/Lyrics fixtures PR #7 | `5ef0bdc0ccd8ce9d7d5519b2c016f9e7936814ce` |
| AI path/runtime compatibility PR #8 | `145d48bc4ecf0cc1a22b2c0915529bdac115ccf4` |

The integration starts **only** from PR #6, which already contains #5. Thus #5's installer, QSettings/preview HOME, D-Bus isolation, uninstall safety and rollback fixes are inherited once. PR #7 adds three files (TV/Radio/Lyrics test, workflow, QA evidence); PR #8 adds four different files (AI compatibility CLI, tests, workflow, QA evidence). Every imported file is copied byte-for-byte from its exact PR head; no content in `source/installed-package/` is changed. Original existing tests are kept (the inherited PR #6 test corrections are unchanged). No code is imported from main or TEXT CENTER development.

## Exact combined-head CI

`.github/workflows/media-final-combined-integration-p0.yml` checks out the **pull request's head SHA explicitly**, not GitHub's temporary merge commit, and asserts that `git rev-parse HEAD` matches it. The source job:

1. Asserts commit ancestry (#5 -> #6 -> integrated head) and byte identity of the frozen source.
2. Asserts exact imported #7/#8 file identities using `git diff --exit-code` against each exact head.
3. Runs original 28 stable-first source/parity tests unchanged, all inherited rollback/security negatives and the added AI synthetic/metadata compatibility tests, Bash/Python syntax and ShellCheck.
4. Runs read-only dry run and prohibits model downloads, automatic settings migration and hardware use.

The disposable Ubuntu 24.04 native job installs the fixed snapshot **twice**, runs every installed-runtime acceptance test and PR #7's TV/Radio/Teletext/Lyrics/karaoke production-algorithm fixtures against **both installed releases** under Xvfb/D-Bus, and verifies the PR #8 optional model-path preview application and fail-closed behavior without loading a model. It then verifies rollback, two uninstalls, and preservation of original-configuration, recording, channel, appearance and fake-model sentinels.

### Interpret evidence honestly

Passing synthetic decoder, matching and karaoke fixtures proves only tested installed algorithm paths with deterministic inputs; this **does not** establish live DVB-T2, FM/DAB, broadcaster Teletext, PTS timing, music/audio recognition or native full GUI behavior. Importing AI libraries or locating fake model bytes is **not** Whisper/Qwen/Argos/NLLB/MADLAD inference or CUDA readiness. Two disposable Ubuntu native builds are **not** a clean Pop!_OS 24.04 or Debian hardware acceptance.

## Hard HOLD gates before release

- Independent Agent 04 GO/HOLD of this exact integrated commit and complete CI, with no test removal or waiver.
- Authorized clean physical Pop!_OS 24.04 and Debian-family native install, safe uninstall and rollback; coexistence with owner's independent Media, TV, SDR and TEXT CENTER processes.
- User-authorized real DVB-T2/FM/DAB/Teletext, audio/subtitle pacing, native TV/radio/lyrics/karaoke, recordings, device ownership and recovery.
- Real Whisper CPU and CUDA GPU (with appropriate drivers/runtime), translation (Argos/NLLB/MADLAD), model paths, Qwen timing and negative missing-dependency behavior; separate model downloads only with consent.
- Original owner-private binary, settings, channel DB, model preferences and GUI parity, plus SPDX/GPL/asset provenance audit.
- Owner's explicit release approval after those gates. No changes to protected PR heads, frozen snapshot, main, other repositories, existing desktop installation or services. No merge, tag, release, deployment or public one-line installer.

The independent review should treat missing real-machine, hardware, inference, concurrency and licensing proof as **HOLD**, even if CI is green.
