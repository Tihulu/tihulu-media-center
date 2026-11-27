# MEDIA-SEC11-UNINSTALL-TRANSACTION-HARDENING-12

**Draft-only security remediation. Public release HOLD.**

Baseline: Draft #11 at exact SHA 2f5699eeb47505468bf3327be4dbdd89fed3dff1; 151/151 source and native test executions PASS ([run 43196547501](https://github.com/Tihulu/tihulu-media-center/actions/runs/43196547501)). Frozen source 7821769eb7aed576dd426ec18ffce3696d93a00d unchanged, all existing tests unchanged.

## SEC11-01: explicit committed uninstall journal

Old behavior: remove launchers and pointers, then delete release 1, release 2, etc. Failure deleting release 2 left ambiguous partial state without an explicit recovery journal.

New behavior: read-only verify all releases and entrypoint bytes, then create owner-only .media-uninstall-transaction-v1/ and fsync a fixed-schema plan.json. Quarantine launcher/desktop/current/previous via inode-verified renameat2(RENAME_NOREPLACE) with directory FDs; no original files deleted yet. Verify manifests a second time and fsync a committed marker. Only then remove releases individually using a pinned directory FD and repeated manifest checks. Quarantined entrypoints and pointers are permanently removed only after all releases are gone. No private settings, model or recording directory is included.

### Reversible versus irreversible boundaries

| Phase | Reversible state | Owner-triggered recovery |
|---|---|---|
| Before durable plan | No owned release deletion | Incomplete/unrecognized journal = manual HOLD, no automatic cleanup |
| Planned, before commit | All releases intact; staged files can in principle be renamed back | An explicit --uninstall resumes forward after validating the journal; never auto-reactivates |
| After commit, before release deletion | Live entrypoints absent and safely staged | Explicit --uninstall resumes verified cleanup |
| After release 1 deletion but release 2 failure | First deletion **irreversible**, second release remains, exact staged entries + committed journal retained | Explicit --uninstall checks the remaining release manifest, then resumes cleanup; install/rollback blocked meanwhile |
| During partial recursive deletion | Possibly modified/incomplete remaining release | Manual HOLD; no automatic removal of partial, unknown or potentially private data |
| During last journal removal | Program already removed, possibly incomplete journal | Manual HOLD; no speculative repair |

Critical: this is a **forward-recovery transaction**, not full atomic rollback across destructive operations. No unknown stage, file or directory is automatically chmodded, migrated, recovered, or deleted.

## SEC11-02: inode-bound entrypoint quarantine

Open exact owned launcher/desktop via O_NOFOLLOW; pin fd, compare all bytes and inode, then rename with Linux renameat2(NO_REPLACE) between verified parent directory FDs. Compare the moved inode with the pre-opened inode. A mismatch triggers a best-effort no-replace reversal and fail-closed HOLD, never deletion of the unrecognized file. Final file unlink is limited to committed quarantined entries, with another opened FD, byte comparison and immediate inode validation.

POSIX unlinkat remains name-based: a malicious same-UID process can still swap an entry **after** the last inode check. This residual threat is documented, not claimed solved.

## SEC11-03: parent/pointer races

Preserve PR #11 managed parent mode/UID gates and shared operations flock; enforce no-replace quarantine staging and check releases parent inode before/after every fd-scoped recursive deletion. Current/previous symlink contents are recorded and verified. A parent replaced during deletion causes HOLD instead of silently continuing under a replacement pathname. Multi-path filesystem operations cannot be fully atomic against malicious same-UID processes; mount namespace attacks and same-UID mutations remain Full Security HOLD.

## Tests and acceptance

Rerun 151 inherited executions unchanged (105 source/security/AI, 46 installed native on 2 disposable Ubuntu builds). New SEC11 negative tests cover second-release deletion failure and post-failure exact file state, explicit recovery, committed state install/rollback refusal, precommit stage failure/retry, tampered journals, unknown quarantined user data, malicious inode substitution, quarantine name collision, pre-unlink swap, parent replacement, simulated SIGKILL, repeat uninstall and private sentinels.

Frozen source identity and original tests/workflows remain intact. No owner PC, real tuner, private settings, models, service, deployment, merge, release or public one-line installer. Scoped CI GO requires exact-head 2/2 success. Independent Agent 04, real hardware/AI inference, owner binary/settings parity and licensing acceptance remain Release HOLD.