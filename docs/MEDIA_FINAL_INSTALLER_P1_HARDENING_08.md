# MEDIA-FINAL-INSTALLER-P1-HARDENING-08 — isolated security acceptance

**Status: DRAFT. Standalone/public release remains HOLD.**

## Sources and immutable boundaries

Baseline combined Draft #9 at `122baf10621cd7a166844f7d6ca6dc6671963863`. The frozen, byte-identical TV/Radio/Lyrics/Karaoke/AI source remains `7821769eb7aed576dd426ec18ffce3696d93a00d`. PRs #5–#9, main and every other project are unchanged. Existing 28 stable-first + 20 P0 safety + 13 AI source tests, 2 × (10 installed + 13 TV/Radio/Lyrics) runtime test executions are **not** removed, changed or waived.

## Independently confirmed P1 weaknesses in baseline #9

1. Installer reinstall only checked if a launcher contained one expected `exec` line; extra shell commands or a modified executable could pass. A desktop containing only the marker `X-TIHULU-StableFirst=true` could pass even with a rewritten `Exec`, `Icon`, or other lines. Uninstall was already stricter but install was not.
2. The original install acquired its root-local lock **after** directory/marker/profile creation, source/dependency checks and identity decisions. Rollback and uninstall did not hold a single lock across every mutation, so races between these modes and initial staging were not excluded.
3. Shell `exec 9>>.install.lock` could follow an injected symlink between its pathname check and shell opening; `install` and `cat > desktop` could overwrite entrypoints swapped after preflight. Interrupted `.work`/`.stage` directories needed deterministic, fail-closed detection.
4. A different unprivileged process with the *same UID* and direct write access to the user's HOME can still alter paths outside the cooperative lock. A directory-descriptor-based filesystem transaction or dedicated OS isolation is required for a stronger hostile-same-user guarantee. No hardware/machine claim is implied.

## Narrow P1 implementation

- A single **sibling operations lock** `~/.local/opt/.tihulu-media-stable-operations.lock` serializes **the entire** install (including dependency consent and native build), rollback and uninstall. The shared lock is created with `O_NOFOLLOW` and verified on an open FD for owner UID, single link, strict permissions, stable inode and nonblocking flock. It exists outside an app root so a fresh install races safely with uninstall or rollback. An inherited FD guard is required by mutating Bash operations, making forged environment-only bypasses fail closed.
- Read-only preflight is executed **before any filesystem creation**, including the operations lock. It requires exact app-root ownership marker, verified safe parent directories, a complete launcher+desktop pair, and no incomplete/stale `.stage`/`.work` roots. Missing/partial/unknown/foreign artifacts cause refusal, not migration or cleanup.
- Full launcher and desktop byte comparison against the canonical installed launcher and exact desktop text, with `lstat`, owner UID, regular-file and unique-inode checks, plus `O_NOFOLLOW` reads and before/after inode checks. Existing owned entries are never truncated.
- File publication uses exclusive `O_CREAT|O_EXCL|O_NOFOLLOW` and `fsync`, then checks exact content again. A competing symlink/hardlink/foreign file is not overwritten. First-install partial publication after an interruption fails closed on the next invocation; do not manually delete without owner review.
- Preserve inherited PR #6 **release-pointer traversal restrictions and manifest verification**, PR #5 private HOME/XDG/DBus isolation, and #8 opt-in preview-only AI tool.
- Negative regression suite `tests/test_media_installer_p1_hardening_08.py` addresses foreign/modified files, extra shell commands, marker-preserving desktop tampering, symlinked/hardlinked entrypoints, parent symlinks, missing/foreign marker, ambiguous orphan/partial installation, interrupted staging, malicious operations-lock symlinks and hardlinks, TOCTOU symlink insertion during exclusive file publication, fake guard descriptor, and concurrent install/rollback/uninstall. Positive tests verify exact owned pairs, normal publishing, locked rollback and repeat uninstall.

## Exact combined-head CI and PASS/HOLD interpretation

New workflow `.github/workflows/media-final-installer-p1-hardening-08.yml` is stacked on Draft #9. It checks out and asserts the **exact Draft PR head SHA**, verifies frozen installed-package bytes, exact #7 and #8 copied source/test/QA file identities, and verifies no edits to any inherited tests. It reruns all **107 pre-existing executions** (61 source/security/AI + 46 installed across 2 disposable native builds) plus **20 new P1 security tests**, and all existing syntax/ShellCheck checks. No test is weakened or replaced by a mock-only source presence assertion. It includes native Xvfb startup, real Qt setting isolation, opt-in fake-model metadata, rollback, repeated uninstall and private settings/channel/recording sentinel preservation.

**GO only for an exact-head green CI run in disposable Ubuntu. HOLD** pending Agent 04 independent review, real Pop!_OS/Debian installation, DVB-T2/FM/DAB/Teletext and recording hardware, actual Whisper CPU/CUDA/Qwen/Argos/NLLB/MADLAD inference, timed Lyrics/karaoke/acoustic parity, original installed binary/private settings equivalence, independent concurrency/TOCTOU security review and licensing/IP review. The lock protects participating processes; it is **not** a complete defense against a malicious process running concurrently with the same user credentials and mutating filesystem paths outside the lock.

No owner-computer installation/uninstall, no models, no hardware/service use, no merge/tag/release/deployment and no public one-line installer authorization.
