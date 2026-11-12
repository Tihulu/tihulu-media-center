# MEDIA-SAFE-DISTRIBUTION-PACKAGING-24 — source-and-native notice remediation

**Status:** Draft-only; no license determination; PUBLIC RELEASE HOLD. No hardware/model/owner PC use.

## Immutable inputs and purpose

- Standalone distribution evidence [Agent 05 Draft PR #19](https://github.com/Tihulu/tihulu-media-center/pull/19), exact head `03a566a57f76428c7fab86fc56e41ac03f011cc2` and [CI run #43329003306](https://github.com/Tihulu/tihulu-media-center/actions/runs/43329003306), 2/2 SUCCESS; installed-release legal notices observed 0/3 even though source root included them. Its four original files, 15 static tests, and restrictive NC model declarations are unchanged.
- Prior integrated independent security review [PR #18](https://github.com/Tihulu/tihulu-media-center/pull/18) exact `e5271965dadaf82c4be1a336396d0e9b3a083b8d`; [Agent 04 report](https://github.com/Tihulu/tihulu-media-center/pull/18#issuecomment-6838435488) and [215 inherited tests](https://github.com/Tihulu/tihulu-media-center/actions/runs/43322278695). Original frozen source `7821769eb7aed576dd426ec18ffce3696d93a00d` remains untouched. SEC11-03 hostile same-UID filesystem race concerns remain **FULL SECURITY HOLD**.

## Fixed packaging defect (scoped implementation)

Existing PR19 native evidence detected actual installed release missing: `LICENSE`, `NOTICE`, and `LICENSES/GPL-2.0-only.txt` (0/3). The new installer shell now invokes a **fail-closed** Python `stage-notices` step after the native ELF and wrappers are staged and **before** `prepare-release` emits the immutable release integrity manifest or the shell promotes the stage to an owned versioned release. The source inputs must be the original PR16 exact Git blobs:

| Notice | Pinned Git blob SHA-1 |
|---|---|
| `LICENSE` | `c03664da635ac564fa53300fc7bd91848839ef68` |
| `NOTICE` | `45798db6c4414a3848125fdd0a2cbdcb95b2825b` |
| `LICENSES/GPL-2.0-only.txt` | `d159169d1050894d3ea3b98e1c965c4058208fe1` |

**Authority boundary:** these hashes are independently hardcoded identities of PR16 original notice blobs. Source files and destination bundle are regular owner-owned, unique-link files, mode 0644; marker ` .media-preview-legal-notices-v1` (without the leading visual space) is a 0600 owned file. Parent directories and files are opened through pinned O_NOFOLLOW/O_CLOEXEC descriptors and rechecked for path/inode/size/timestamp change. Staging creates files using O_CREAT|O_EXCL and fsyncs the staged files/directories; it will not overwrite or chmod a preexisting/foreign destination. Release integrity manifests include all three file hashes, LICENSES directory and marker. Existing legacy test fixtures without the versioned bundle retain old semantics, while a bundle listed in a release manifest or partially present on disk requires the entire pinned bundle. Deletion/recovery/rollback continues to call `verify_release`, so corruption is rejected before any release is removed.

**Preservation:** The original security quarantine plan, guarded global lock, ownership, private preview TV shim, native diagnostics parity, predecessor release rollback and committed SIGKILL recovery functions are unchanged apart from integrating legal notice validation into release verification. No prior branch or CI suite is weakened, and no physical owner data is inspected or removed.

**CI negative coverage:** exact missing/changed/weak-mode/owner-spoof/symlink/hardlink legal files, preexisting destination, symlink/hardlink/altered source, missing legal marker; actual disposable release uninstall corrupted/missing/symlinked notice causes HOLD before transaction/irreversible deletion and preserves a private sentinel. Exact installed native Kaffeine release asserts 3/3 genuine source-matching legal files and 5 native notice QA cases per build. Real same-UID hostile concurrent races, crash/power-loss, owner system still HOLD.

## GPL corresponding-source candidate — review path, not distribution

Agent 05's **unaltered** `tools/compliance/media_distribution_evidence_23.py reconstruct` takes the pinned KDE Kaffeine v2.0.19 source at `e7ea15b86dafed3b20b151cbcb080578ab8e2d5c`, extracts the frozen selected 133 source files, executes the frozen `patch_upstream.py`, extracts and runs the exact PR17 native DVB diagnostics patch from the installer shell, and produces `modified_kaffeine`, `selected`, `patches/kaffeine-from-pinned-upstream.patch`, `build_scripts` and `legal` directories. The new `tools/compliance/media_package_candidate_24.py` separately checks immutable upstream commit, candidate manifest/patch hash and build inputs, inventories all candidate source SHA256/modes and rejects external source symlinks; it produces a review-only file inventory and build instructions, with **no full-source or binary upload**. The CI artifact contains only review metadata, reconstructed patch and instructions; the full disposable candidate remains inside the CI runner.

CI-only commands (on a disposable Ubuntu host with matching source build dependencies; not an owner-machine instruction):

```bash
python3 tools/compliance/media_distribution_evidence_23.py reconstruct --repo . --candidate "$RUNNER_TEMP/media24-source-candidate"
python3 tools/compliance/media_package_candidate_24.py --repo . --candidate "$RUNNER_TEMP/media24-source-candidate" --output "$RUNNER_TEMP/media24-review"
cmake -S "$RUNNER_TEMP/media24-source-candidate/modified_kaffeine" -B "$RUNNER_TEMP/media24-cmake" -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF -DCMAKE_INSTALL_PREFIX="$RUNNER_TEMP/NOT-FOR-DISTRIBUTION"
cmake --build "$RUNNER_TEMP/media24-cmake" --parallel 2
```

These commands are **not** bit-reproducibility instructions. Exact compiler environment, toolchain, patch and complete packaging flags, binary-to-source attestation, complete GPL corresponding-source delivery, dynamic-codec dependencies and all per-file third-party rights are not established. The baseline PR19 observed different actual ELF hashes across disposable runs. No source candidate is claimed to have been delivered to binary recipients.

## Exact-head acceptance strategy

One new isolated Draft workflow runs all 215 inherited PR18 tests (the eight original integration-only identity tests must run unchanged in the **exact PR18 disposable worktree** because two intentionally require PR18's installer and exact 16-file PR15 delta; new HEAD tests independently check the new delta), PR19's original **15 static** tests and the new notice regression suites, plus two real ephemeral Ubuntu native installs with feature/performance parity, AI no-model checks, rollback/repeated uninstall and owner private sentinels. The original PR16 14 static tests remain in an exact PR16 detached worktree as in PR18. The exact count is taken from actual CI logs, never assumed.

## Mandatory HOLD and independent review

- Agent 04 must independently review the **new** exact installer and Python SHA, including pinned notices versus hostile owner/mount/path substitutions, quarantine and rollback/inode-safety implications. Prior PR18 approval does not auto-approve the new HEAD.
- Agent 05 must independently examine actual installed 3/3 notices, pin provenance, full candidate evidence, GPL source delivery gaps, third-party rights, native/ELF/codec/wheel final SBOM and noncommercial NLLB `CC-BY-NC-4.0` / audEERING `CC-BY-NC-SA-4.0`. Adding notices does **NOT** clear the legal distribution HOLD.
- Original frozen source remains unchanged, 110/133 files lacked explicit SPDX tags, and 133/133 conclusions remain NOASSERTION pending legal review; real physical DVB-T2/FM/DAB 0/41, true Whisper/CUDA/translation inference NOT RUN, original owner binary/settings parity and explicit owner approval still HOLD.
- **No merge, install on owner computer, tag, release, model/hardware access, private data or public one-line installer. PUBLIC RELEASE HOLD.**