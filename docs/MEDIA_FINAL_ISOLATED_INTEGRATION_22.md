# MEDIA-FINAL-ISOLATED-INTEGRATION-22 — controlled, unmerged Draft

**Status:** integration implementation proposal only; public release HOLD; independent Agent 04 exact integrated-head security review is mandatory.

## Immutable inputs and acceptance gate

| Upstream input | Exact tested HEAD | Evidence |
|---|---|---|
| Agent 01 SEC12 security Draft #15 | `b7d4e7ee820e7969b976a56c9888ba05e676a3b1` | Exact-head CI https://github.com/Tihulu/tihulu-media-center/actions/runs/43291618169 — 180/180 PASS; independent Agent 04 scoped SEC12 review https://github.com/Tihulu/tihulu-media-center/pull/15#issuecomment-6837553832 |
| Agent 05 compliance Draft #16 | `14b51610d00e12cdf811a8ed6fb416681b4ac58e` | https://github.com/Tihulu/tihulu-media-center/actions/runs/43319107852 — 14/14 static-only PASS, legal signoff HOLD |
| Agent 06 parity Draft #17 | `afc70c6fc77d7c0a37d5879abf83fc7e131dd7c6` | https://github.com/Tihulu/tihulu-media-center/actions/runs/43320292048 — 3/3 completed SUCCESS; 108/108 old+parity source, 2 x (23 original native + 5 parity native), and separate negative-control native build of exact PR11 confirming both original faults; real RF/model parity HOLD |

The immediate integration gate was the PR #17 final *exact-head native CI*, not the broader public release gate. Verified all 3 jobs completed successfully at that exact SHA, including real native negative/positive controls in disposable Ubuntu. PR #17's prior handoff said HOLD **pending this CI**; that conditional technical HOLD was satisfied. No independent release approval is implied; Agent 06's last comment was a pre-CI checkpoint.

**Preserved baseline:** integration branch starts at PR #15 SHA and never merges older #11-based branches. Frozen source snapshot `7821769eb7aed576dd426ec18ffce3696d93a00d`; all selected `source/installed-package` objects, older security Python, and all 180 preexisting test sources are kept unchanged.

## File-level provenance, avoiding branch merge conflicts

**PR #16 exact copied artifacts (nine original blobs):** `LICENSE`, `LICENSES/GPL-2.0-only.txt`, `NOTICE`, `docs/compliance/AI_MODEL_LICENSES_19.json`, `docs/compliance/MEDIA_LICENSE_COMPLIANCE_19.md`, `docs/compliance/PRELIMINARY_SBOM_19.json`, `docs/compliance/SOURCE_PROVENANCE_19.json`, `docs/compliance/SPDX_SOURCES_19.spdx.json`, `tests/test_media_license_artifacts_19.py`. The original stand-alone PR16 workflow is *not copied* because its PR-only selector and license test #06 explicitly require **only compliance files modified** relative to PR11, incompatible with intentional integration. This is documented, not bypassed or weakened.

**PR #17 exact copied installer and QA (four original blobs):** `installer/media-stable-first.sh`, `docs/MEDIA_PARITY16_DIAGNOSTICS_TV_ROUTING_20.md`, `tests/test_media_parity16_source_20.py`, `tests/test_media_parity16_native_20.py`. The original PR17 standalone workflow is *not copied* because its source-diff gate expressly rejects security Python changes relative to PR11; the new integration workflow preserves its original baseline-negative test step and positive tests under the secure PR15 installer. The PR15 installer shell blob was verified identical to PR11's shell blob `8405ae7632a2eda8c72b823f75d75ddd66a4140f`; consequently importing the exact PR17 shell blob `3cccbdf9af4e535677085ab0d19e45016e39a864` does not override any post-PR11 shell security modifications. `installer/preview_safety.py` remains exactly PR15.

**New integration-only artifacts:** `.github/workflows/media-final-isolated-integration-22.yml`, `docs/MEDIA_FINAL_ISOLATED_INTEGRATION_22.md`, `tests/test_media_final_isolated_integration_22.py`. The integration test asserts exact imported Git blob SHAs, source snapshot bytes, all inherited test blob identities, strict allowlist of these sixteen paths, and explicit licensing restrictions. The exact input SHAs are pinned, not overwritten.

## Combined exact-head GitHub Actions acceptance

One workflow contains **three mandatory jobs**:

1. **Source, security, compliance and integration provenance:** PR15 original 134 source/security/AI tests; all PR17 three source guard tests; PR16 original 14 licensing static tests executed unchanged in a detached disposable worktree at its exact original PR16 commit, *after* checking every integrated licensing artifact blob identical to PR16; eight new integrated exact-Git-blob/safety/rights tests on actual integrated HEAD. **159/159 source test executions**. Static verification of ShellCheck, Python syntax, frozen source and original test IDs. This distinction is essential: standalone license test #06 correctly rejects an integrated branch if run in-place, so the original test is neither skipped nor weakened; the new source-head test independently verifies the integrated files.
2. **Independent PR11 native negative-control reproduction:** exact PR11 baseline checked out in a new disposable worktree, built/installed on Ubuntu 24.04 to reproduce both old DVB diagnostic-route and direct isolated Python TV failures. Both failures are **expected pre-fix evidence**; no real receiver, recordings or model. Not counted as a unittest execution.
3. **Combined two-install native acceptance:** use **the integrated secured installer** for two independent Kaffeine builds/installs in one disposable CI HOME. On each install run 10 installed runtime acceptance + 13 TV/Radio/Teletext/Lyrics/Karaoke algorithm fixtures + 5 real native parity GUI/diagnostic tests = **56/56 installed test executions**, followed by separate synthetic AI preview isolation, rollback, two owned-only uninstalls, and owner-settings/recording sentinels. Confirm original owner public bin remains untouched while private preview TV shim is preserved.

**Expected total: 215/215 named unittest executions**, if/when exact-head green; this is a target, not a premature PASS. No downloaded models or real RF. All 180 inherited PR15 executions remain byte-for-byte unchanged. Do not count baseline native negative-control assertions as extra unit tests.

## PASS / HOLD and dependencies

- **Scoped technical PASS only after green exact-head workflow** for 180 secured inherited tests, 14 static licensing, 3 parity source, 10 parity native and 8 integration provenance.
- **Agent 04 HOLD pending independent re-review** of the *new integrated installer exact SHA*, especially coexistence of private preview TV compatibility shim with SEC12 journal/quarantine and rollback/uninstall, input security invariants and remaining same-UID filesystem races.
- **Licensing/redistribution HOLD:** provisional NOTICE/SPDX (133-source inventory with deliberate NOASSERTION), incomplete 30-component SBOM and 9 opt-in model records do not establish corresponding-source, compiled dependency and redistribution approval. NLLB/audEERING NC restrictions remain unaltered.
- **Real physical acceptance NOT RUN:** Agent 02 Draft #13 has 7/7 plan-only and 0/41 real tuner acceptance; Agent 03 Draft #14 has 129/129 source/synthetic and no validated CUDA/CPU model inference. Agent 06 original installed binary/settings equivalence remains HOLD, independent of fixed parity build. True power-loss recovery and hostile same-UID multipath TOCTOU remain full-security HOLD.
- **Owner safety:** no changes to current owner's Media Center, sources, services, tuner, recordings, models, system settings or other repositories; all native installation operations confined to disposable Ubuntu Actions HOME. No merge, tag, release, public one-line installer or deployment. Owner approval required for any live acceptance or publication.