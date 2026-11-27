# MEDIA GPL SOURCE DELIVERY & LICENSE-CLEARANCE PLAN — 27

**PUBLIC RELEASE HOLD. This is a read-only evidence/planning Draft, NOT legal clearance, a GPL source offer, a signed release, a model redistribution license, or authorization to merge/install/release.**

## Exact immutable inputs and scope

- Independent security reference: [PR #22](https://github.com/Tihulu/tihulu-media-center/pull/22) exact HEAD `77f46af46335b3c91286c327780d657ebe7f0bf4`; [Agent 04 independent report](https://github.com/Tihulu/tihulu-media-center/pull/22#issuecomment-6843097316). PR22 independently validated 35/35 current-head SIGKILL/generation tests; **SEC11-03 hostile same-UID races and physical power-loss remain FULL SECURITY HOLD**.
- Frozen selected installed-package source commit `7821769eb7aed576dd426ec18ffce3696d93a00d`, selected subtree `c572e6eccc5118c5130b1b5827af2f643633c26d`, exactly 133 selected files. KDE upstream Kaffeine v2.0.19 exact commit `e7ea15b86dafed3b20b151cbcb080578ab8e2d5c`. Git hashes are byte identities, not license permission.
- Earlier PR16 root LICENSE is scope-only and NOTICE preliminary. PR20 repaired **3/3 technical legal files** in new disposable releases. The PR20/PR19 **492-file source candidate** (352 modified Kaffeine + 133 selected + 2 build scripts + 3 legal + 1 patch + 1 manifest) is a disposable candidate/inventory; **NO complete corresponding-source archive was delivered to binary recipients**.
- This PR changes ONLY new compliance policy/tool/tests/CI/documentation; no source, installer, model files, old PR, owner PC, broadcast hardware or services.

## Proposed real matching binary/source delivery workflow — not executed

1. **Identify exact target** (platform, architecture, distribution format, release hash) and obtain explicit owner agreement to publish. Build **a specific binary** on a disposable, pinned environment; record toolchain image digest, compiler/linker versions, Qt/KF5, ffmpeg/libVLC, dynamic codec/plugin libraries, Python package wheel digests, CMakeCache, flags, full invoked build/packaging commands, build-generated source, environment provenance and the actual resulting native ELF + package SHA-256. The owner/private existing binary was not inspected.
2. **Capture the complete corresponding source of the actual object code from the SAME build transaction**, not merely reconstructing a later approximation. Include pristine KDE upstream and exact modified Kaffeine source, all native patches (including DVB diagnostics route), exactly selected frozen companion code, applicable generated source and build inputs, compilation/installation/packaging scripts and legal copyright notices. Check SPDX ownership per file before asserting any right to publish. The previous 492-file candidate is a floor for inventory review, **not evidence all legally required material has been captured**.
3. **Publish binary and actual complete source archive together** on an owner-approved, stable, versioned endpoint with independently authenticated binary/source SHA-256 mapping, full copyright/license notices and a resolved SBOM. Example future names only: `tihulu-media-<version>-<os>-<arch>.tar.zst`, `tihulu-media-<version>-corresponding-source.tar.gz`, `SOURCE-DELIVERY-MANIFEST.json`. Do not generate production URLs, keys, or claim signed authority from this Draft. Evaluate any written-offer alternative only with competent legal review of the applicable GPL obligations.
4. **Verify recipient-side delivery**: independent reviewer retrieves *both exact assets* as an ordinary recipient from the approved public delivery channel; verifies authenticated manifest, archive digests, actual unpacked source, matching build chain, notices, distribution location/retention and source availability terms. A CI artifact containing metadata and a patch does not count as a delivered source archive. Independent reviewer must not infer license completeness from valid checksums alone.
5. **Record owner decisions and legal/technical gate sign-offs**. Do not merge/release or enable an installer until the separate complete GPL source/rights/target-SBOM/security/real-device/owner-parity gates are independently accepted and owner explicitly authorizes that exact artifact.

## Read-only fail-closed pairing gate (synthetic CI only)

`tools/compliance/media_gpl_delivery_guard_27.py --repo .` verifies PR22 ancestry, frozen 133-file selected subtree, original PR16 Git legal blobs, 9 optional unbundled model records, retained NLLB/audEERING NC terms, all 133 conservative SPDX NOASSERTION conclusions, and explicit HOLD+UNDECIDED owner gates.

Future **disposable review-only** `--pair <directory>` mode checks `binary/native/bin/kaffeine`, pinned LICENSE/NOTICE/GPL content, `corresponding-source.tar.gz` (actual source candidate archive), `source-inventory.json` (SHA-256, size, mode), `build-provenance.json`, `SBOM-observation.json`, and `SOURCE-DELIVERY-MANIFEST.json` SHA-256 bindings. It detects missing/substituted files, archive traversal/symlinks/hardlinks, altered source digests, incomplete 492-member candidate baseline/133 selected files, disallowed model weights, and fabricated release approval. It does NOT run untrusted candidate binaries.

**Even an all-bytes-matched future pair outputs `technical_candidate_byte_pair=SCOPED_PASS_ONLY`, `complete_gpl_corresponding_source=HOLD`, `real_recipient_delivery=NOT_PERFORMED`, `public_release=HOLD`.** Build provenance declarations are self-reported, not automatically authenticated. This project CI creates only synthetic, clearly marked 492-file source/ELF-like fixtures, not a real paired release; a green run does not close any licensing gate.

## Separate remaining release gates

| Gate | Current evidence | Decision |
| --- | --- | --- |
| 3/3 legal file delivery in new r2 native release | PR20+PR21 disposable pinned Git-blob/mode/manifest QA | **SCOPED PASS for bytes, final notice/legal adequacy HOLD** |
| Full GPL corresponding source paired with exact actual compiled binary | PR20 candidate metadata + patch only; no shipped full source | **HOLD P0** |
| Original and third-party copyright holder/NOTICE accuracy | PR16 root scope-only + provisional NOTICE; 133 per-file NOASSERTION, 110 missing SPDX headers in prior scan | **HOLD P0/P1** |
| Native ELF, FFmpeg/VLC codecs, Qt/KF5, PyQt, Linux plugins, optional wheel/CUDA/model SBOM | PR19/PR20 disposable Ubuntu observations 23 direct ELF NEEDED, 103 resolved runtime libs, 88 runner Python distributions, not true shipping closure | **HOLD P1** |
| Native source/build provenance and reproducibility | Different disposable ELF hashes across earlier jobs; not attested from one identical build transaction | **HOLD P1** |
| Meta NLLB-200 600M weights | `CC-BY-NC-4.0`; separate model terms | **NO COMMERCIAL RIGHTS / NO BUNDLING; HOLD** |
| audEERING wav2vec2 age/gender weights | `CC-BY-NC-SA-4.0`; attribution/ShareAlike and NC obligations | **NO COMMERCIAL RIGHTS / NO BUNDLING; HOLD** |
| Argos language packs, converted Whisper, MADLAD/Qwen, Resemblyzer/AST assets | Individual exact artifacts and embedded data/weights unverified | **NO BUNDLING until clearance; HOLD** |
| Same-UID adversarial filesystem security/power-loss | Agent04 PR22 scoped process crash PASS, SEC11-03 still outstanding | **HOLD** |
| Real FM/DAB/DVB hardware, live AI inference, owner's existing installed binary parity | NOT RUN by this phase | **HOLD** |
| Public release/merge | No authority, independent comprehensive QA or owner release approval | **HOLD** |

## Owner decisions (not assumed or answered)

The separate machine-readable ledger `docs/compliance/MEDIA_GPL_SOURCE_DELIVERY_GATES_27.json` explicitly marks seven decisions `OWNER_REQUIRED / UNDECIDED`: (1) whether to distribute, audience and commercialization, (2) exact release formats/host/source availability and retention, (3) original code/UI/icons/lyrics authorship and outbound licenses, (4) qualified GPL/LGPL and other-license review, (5) mandatory exclusion of unverified models or separately licensed replacement rights, (6) build/signer/SBOM/provenance investment, and (7) final independent security/device/model/parity/owner acceptance.

### Independent QA handoff

Request Agent 04 / an independent license reviewer to inspect only this new exact-head Draft, original PR16–22 source references, synthetic future pair fixtures, strict noncommercial model exclusions and always-HOLD legal status. All prior PRs are frozen. Any real source bundle/public delivery requires a later separately authorized isolated Draft and an independent recipient-side review. **No merge/tag/release, owner installation, models, hardware or private files. PUBLIC RELEASE HOLD.**
