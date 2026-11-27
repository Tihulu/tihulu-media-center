# MEDIA-SEC09-PARENT-DIRECTORY-AND-RACE-HARDENING-10

**Draft only. Public installer/release HOLD.**

## Immutable base and source

- PR #10 exact parent `ed834c6814d536bdeaf5a409d5d31d23e45e911c` with [130/130 previous test executions](https://github.com/Tihulu/tihulu-media-center/actions/runs/43192734206).
- Frozen original source `7821769eb7aed576dd426ec18ffce3696d93a00d`. The entire `source/installed-package/` tree and ALL prior test files remain unchanged.
- New PR stacked exclusively on PR #10, no merging or protected branch writes.

## SEC-09-01 — confirmed directory permission issue

The original `preview_safety.directory()` required a genuine directory owned by the user but did not refuse `S_IWGRP`/`S_IWOTH`. Existing `~/.local`, `~/.local/opt`, lock parents, launcher/desktop parents, release roots and app root could be group/world-writable and pass preflight. This is an avoidable cross-account modification risk whenever another process can write such a directory.

The new verifier rejects group/other-writable managed directories, including HOME itself, every managed path checked by `paths()`, app root and preview/release dirs. It never automatically changes mode/ownership, removes a directory, imports settings, or migrates an old installation. Ordinary safely configured HOME and managed directories with modes `0700` or `0755` pass. A world-writable `/tmp` *above* a secure user HOME is not treated as a managed directory; only the user-owned HOME and descendants are checked.

Release manifest traversal now rejects nested writable release directories. The operations lock is opened relative to a checked parent directory FD using `open(..., dir_fd=..., O_NOFOLLOW)`, with original inode cross-check and repeated `verify_guard` parent checks. Launcher and desktop unlink during uninstall is anchored to an opened safe parent directory FD. Release deletion uses Python's fd-based `shutil.rmtree(..., dir_fd=...)` and re-verifies release manifests before the destructive phase; a post-verification release substitution test must fail without deleting a foreign target. The shell also rechecks the guard immediately before final promotion and activation.

## Adversarial cases exercised in disposable CI

- Group- and world-writable `HOME`, `.local`, `.local/opt`, application root, release parent, release child and nested release paths, preview HOME, launcher and desktop parent — reject without chmod or creating lock
- Secure `0700` and `0755` directories remain supported
- Permissions modified after acquiring a cooperative lock — subsequent guard use refuses
- Lock parent renamed/replaced while FD held — subsequent guard use refuses
- Desktop symlink substituted between publication preflight and exclusive create — fail closed; unrelated owner sentinel unchanged
- Release contents tampered after first manifest verify before uninstall — refusal prior to deleting entrypoints
- Release path swapped to symlink at fd-scoped deletion — refuse deletion of symlink target
- Abrupt `SIGKILL` of **disposable synthetic lock holder**, leaving interrupted stage — next preflight refuses; no automatic deletion; an explicit simulated owner cleanup in test permits a subsequent locked operation

These are deterministic injected race probes, not a proof of exhaustive interleaving coverage.

## Residual threat-model limitations (mandatory HOLD)

- A malicious process with the *same UID* able to rename/replace directories and files can still race a path between separate `lstat`, content verification, launcher/link publication, native staging and deletion steps. Cooperative flock only serializes participating installers. The new dirfd-anchored operations reduce exposure, but **do not** turn all shell and Python paths into a single atomic filesystem transaction; especially pointer swaps and multi-release removal still have mutable path windows.
- A mutable HOME parent above the managed HOME (e.g. an insecure mount) or adversarial filesystem/mount behavior requires separate security review.
- Interrupted staging deliberately causes HOLD until explicit owner action; no auto-delete or automatic recovery of potentially private content.
- No real DVB-T2/FM/DAB/Teletext, Whisper CPU/CUDA, model inference or licensing acceptance; no parity to owner's installed binary/settings/hardware.
- Agent 04 must independently review exact PR head and classify same-UID attack assumptions and race limits. Passing CI earns **scoped SEC09/Ubuntu-synthetic PASS only**, not full-security GO and never public release GO.

**No owner machine modifications, hardware access, services, model downloads, merge, tags, release, deployment or public one-line command.**
