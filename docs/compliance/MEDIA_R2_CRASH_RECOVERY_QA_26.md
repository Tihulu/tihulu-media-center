# MEDIA P2-QA25-01: isolated r2 crash-recovery acceptance

Status: **DRAFT QA ONLY — PUBLIC RELEASE HOLD**.

Immutable predecessor: Draft PR #21 exact SHA
`fe91a918b38482c02db7e78c510c05ad15e7d128`.
This follow-on must not change PR #21, preexisting tests, compiled application
sources, user machine, device access, installations, AI models, or services.

## Test authority and scope

`tests/test_media_r2_crash_recovery_26.py` dynamically imports the
**actual** production `installer/preview_safety.py` at this branch HEAD and
creates two legitimate `r2-` release trees using the existing original
`stage_legal_notice_bundle` and `prepare_release(..., v2_release_name=...)`.
It verifies both schema-2 names and pinned legal bundle before running. Binary
payloads are **synthetic**; no native player, SDR, DVB, radio, TV, GPU or AI
runtime is launched. Every test has a unique temporary ordinary-user HOME.

The subprocess tests use **real OS SIGKILL** on an isolated Python worker:
- durable plan written before staging;
- committed journal marker written before release deletion;
- first verified r2 dirfd-scoped `shutil.rmtree` completes;
- quarantined launcher unlinked after both releases are deleted;
- plan unlink during final journal cleanup (manual HOLD expected).

A fresh independent CLI invocation handles restart/resume. Positive cases
require safe cleanup, idempotent second uninstall and byte-identical owner
recording, config, preview settings and synthetic model sentinel.

Malformed journal cases include truncated JSON, extra unknown private file,
substituted current pointer, missing expected quarantine launcher while a
release remains, corrupted remaining r2 manifest inventory, changed commit
marker, insecure plan mode, and unknown precommit journal bytes. They must
refuse restart with `PREVIEW-SAFETY HOLD`, perform **no further release
deletion**, retain foreign bytes and never auto-chmod or modify private data.

This exercises actual process termination and durable journal lifecycle under
GitHub Actions' disposable filesystem. It is NOT a real power-cut test and
cannot establish fsync-on-physical-storage guarantees or stop an active hostile
same-UID process from changing mount/path/inode identities. The remaining
SEC11-03, complete GPL corresponding-source and legal rights, real
hardware/models, owner-binary parity and public distribution gates remain
**HOLD** even if all 13 r2 scenarios and 22 inherited new-generation regressions
pass. No release, merge, automated remediation or user machine operations.

## Review acceptance

Independently verify the exact resulting commit SHA and the new Actions run,
check **13/13** new scenarios (including actual child SIGKILL and separate CLI
restart) and **22/22** inherited v2 generation cases. Confirm the predecessor
SHA and original installer/security/notice/test file bytes are unchanged.
Report P0/P1/P2, PASS/HOLD, and remaining limitations to Agent 04 on the new
Draft PR and cross-reference Media issue #1 and master issue #8. Never count
PR21's 195 historical executions as fresh current-head tests.
