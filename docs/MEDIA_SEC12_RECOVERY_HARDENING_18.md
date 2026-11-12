# Agent 01 — MEDIA-SEC12-RECOVERY-HARDENING-18

**Draft PR only. Full Security HOLD. Public Release HOLD.**

**Pinned baseline:** Draft PR #12 exactly 5c17ed010bd0bfaa2ea0348bfbc92a74ac397292; previous exact-head GitHub Actions run 43286135590, 165/165 executions PASS. Independent Agent 04 findings: https://github.com/Tihulu/tihulu-media-center/pull/12#issuecomment-6833593023. Frozen source 7821769eb7aed576dd426ec18ffce3696d93a00d, original 165 tests and previous PR history remain unchanged.

## SEC12-01: quarantine preflight before any irreversible release deletion

New `_preflight_committed_quarantine` is called immediately after checking the committed marker, **before** iterating or removing any release. It confirms (a) no launcher, desktop, current or previous at any original live path, (b) exactly the entries the immutable validated plan requires, (c) exact owner/regular-file/content/no-hardlink/inode properties for launcher and desktop, (d) exact owner/symlink/link-target/inode for both pointers, and (e) the pinned quarantine directory inode and private 0700 mode. All four planned slots must be present when **any release remains**; if a release has already been permanently removed and remaining releases exist, staged files still must be intact before a subsequent irreversible removal.

Once **all** owned releases have been removed, an interrupted final cleanup may already have unlinked one or more quarantined entries. An absent staged item is permitted **only at this no-releases-remain stage**, enabling explicit forward recovery without deleting another release. Unknown unexpected staged content is always rejected. Original live paths must remain absent. Final unlink still independently rechecks each pinned file. No garbage collection, chmod, migration or private purge.

Regression injections: after an independently verified first release deletion with synthetic failure at second, replace launcher bytes, desktop bytes, current/previous target, hardlink or symlink staged content, or remove an expected staged file; assert `shutil.rmtree` is never called on retry and the remaining release and private sentinels survive. These are **deterministic synthetic fixtures**, not an external exploit demonstration.

## SEC12-02: strict transaction plan mode, descriptor, identity and schema

Plan is read only from a verified owner-owned real 0700 quarantine parent FD and a separate O_NOFOLLOW|O_CLOEXEC descriptor opened relative to that FD. Reject any non-regular file, non-owner UID, nlink != 1, mode other than **0600**, zero-length and >1 MiB files. Compare before/open/post stat devices, inodes, size, timestamps and mode; reject parent directory substitution. Read only the pinned descriptor, not a new pathname. Reject JSON duplicate object keys; require exactly `{schema,releases,had_releases,entrypoints,pointers}` with **schema exact integer 1 (not Boolean)**, unique sorted valid release names, exact Boolean pair and matching launcher/desktop presence, exact Boolean had_releases, exact dict of current/previous string or null pointing only to recorded releases. No auto chmod or journal repair.

Negative fixtures cover 0644/0666/0400/0700 plan modes, hardlinks, symlinked plan to private file, inode replacement in the gap between pre-stat and open, malformed field types (list/dict mismatches, Boolean schema, malformed pointer), duplicate names, unexpected and duplicate JSON keys, insecure 0755 transaction directory. Each case checks the still-valid release is not removed.

## Real SIGKILL committed-phase fixtures

1. A disposable unprivileged Python subprocess starts a genuine two-release uninstall, commits the fsynced plan/quarantine, completes removal of release one using real directory-FD `shutil.rmtree`, then receives **SIGKILL from its own process**. Parent verifies returncode -SIGKILL, committed journal and quarantined entrypoints are intact, release one gone, release two still verified, and private sentinels unaffected. Explicit later `--uninstall` safely completes verified forward recovery. This tests **real process death** at committed phase, not just a patched EIO exception. It does **not** simulate electrical power loss or prove power-failure persistence.
2. A second disposable child receives SIGKILL after first committed quarantined unlink, when all releases are gone. Explicit retry tolerates that one already-completed unlink and finishes safely with private data preserved.

## Owner-led manual recovery: fail closed, preserve unknown data

**Never perform manual recovery on the owner's machine without explicit permission.** A corrupt/missing/hardlinked/weak-mode plan, unexpected quarantined entry, changed launcher/pointer, nonmatching release manifest, partial recursive deletion, parent replacement, or ambiguous disappearance of a staged entry while releases remain is a **HOLD**. Do not reinstall, rollback, reconstruct a fake plan, delete the journal, chmod unsafe files, force-move a replaced entrypoint, or run `rm -rf` as an automatic workaround. The supported recovery path is **explicit `--uninstall` only for an intact, recognized transaction**; it must pass full preflight.

For a manual HOLD, stop further installer operations. Collect read-only `lstat`/inode/mode/owner, contents of release **names** (avoid collecting private file bytes), manifest verification results, current/previous target strings, exact journal status and copies of any signed/logged evidence. Securely preserve private preview settings and owner data; do not upload them to public issues. Inspect on a disposable offline copy under owner oversight and restore only explicitly verified, uniquely owned content. If a release has already been deleted, it is **irreversible**; do not claim atomic rollback. Require owner-approved repair plan and another independent security review before live use.

## Limits and acceptance boundaries

Immutable frozen TV, Radio, Teletext, Lyrics, Karaoke and AI source bytes unchanged. All **165 inherited executed tests remain unchanged**; add 15 SEC12 security executions. Native CI still builds and installs KDE Kaffeine twice on disposable Ubuntu 24.04 and executes 46 deterministic runtime/algorithm fixtures with synthetic inputs. Physical DVB-T2/FM/DAB/Teletext, RTX CUDA, CPU Whisper, translation weights, private installed binary/settings equivalence, SPDX/GPL licensing, and owner acceptance are **NOT RUN / HOLD**.

Residual limitations: POSIX unlinkat remains pathname-based after last inode check; same-UID adversarial mount, path swaps, data alteration and parent/pointer mutation across non-atomic multi-path stages are **Full Security HOLD**. An actual process SIGKILL is not a hard power-loss durability proof. Independent Agent 04 exact-HEAD review, Agents 02/03 real hardware and model tests, Agent 05 licensing, Agent 06 binary/installed parity, and owner approval remain mandatory. No merge, tag, release, deployment, public one-line installer or owner-machine access.