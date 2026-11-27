# MEDIA-LICENSE-COMPLIANCE-ARTIFACTS-19 — PRELIMINARY REDISTRIBUTION EVIDENCE

**Decision: PUBLIC RELEASE HOLD. No legal approval is asserted.** This review-only change set creates traceable records; it is **not** an installable application, a signed-off bill of materials, or a product license grant.

## Exact provenance and scope
- Audited security Draft PR #11: https://github.com/Tihulu/tihulu-media-center/pull/11
- Exact baseline HEAD: `2f5699eeb47505468bf3327be4dbdd89fed3dff1`; head Git tree `06790356ea1deaf63e1e93b6d7fbc4ed471ab160`.
- Frozen installed-package snapshot: `7821769eb7aed576dd426ec18ffce3696d93a00d`, source-tree OID `d471b3aa4e546e8d790512df37fad763254023c6`.
- Selected installer input: **133** files from `source/installed-package/{kaffeine_next,tv_center,textcenter}`; excludes all `source/worktrees/**` archived development variants.
- KDE Kaffeine v2.0.19 upstream commit `e7ea15b86dafed3b20b151cbcb080578ab8e2d5c`. Git object IDs are **not file SHA-256**, and source provenance is **not legal provenance**.
- No compiled binaries, shared libraries, font files, private AI weights, recordings, channels or owner settings are added. The owner's privately reported Kaffeine binary checksum is NOT a successful rebuilding or equivalence verification.

## Redistribution gates and outstanding evidence

| ID | Severity | Finding | Required before distribution |
|---|---|---|---|
| LIC15-01 | P0 | No complete distributable copyright and third-party notices dossier | File-level author/license verification; actual release layout copies required legal notices |
| LIC15-02 | P0 | KDE Kaffeine GPL source transformation and linked binary | Preserve full unmodified required license/copyright notices; exact pinned upstream + all patches + build/install scripts + complete corresponding source delivered in GPL-compliant manner with distributed binaries; account for applicable GPL-2.0-or-later terms |
| LIC15-03 | P0 | Meta NLLB-200 distilled 600M has CC-BY-NC-4.0 | No commercial use/offer or bundling without separate rights; keep explicit opt-in & license disclosure |
| LIC15-04 | P0 | audEERING voice model has CC-BY-NC-SA-4.0 | No commercial use/offer without separate rights; preserve attribution and ShareAlike where applicable |
| LIC15-05 | P1 | Qt, KDE Frameworks, libVLC, FFmpeg, DVB, PyQt and Python wheels unresolved | Collect actual versioned ELF/ldd or readelf dynamic dependencies, package licenses, build flags and complete recursive pip wheels with attribution |
| LIC15-06 | P1 | Unverified original code, JS/CSS, SVG creator/rights and historic worktrees | Author/editor rights ledger; per-file SPDX; no blanket license by assumption |
| LIC15-07 | P1 | Argos language packs and embedded Stanza/training provenance incomplete | Exact pack IDs and checksums; validate contents, training/third-party rights and notices |
| LIC15-08 | P1 | Floating model IDs and pip versions | Pin exact revisions/hashes, model card and license text per downloaded artifact; revisit origin changes |
| LIC15-09 | P1 | Lyrics API use does not confer lyric copyright | Terms review; avoid unauthorized exporting, caching, publishing/rehosting lyrics |
| LIC15-10 | P1 | Optional welle-cli changes and native linkage | Source delivery with modified GPL-covered welle-cli when redistributed and dependency/license reconciliation |

## Files and evidence semantics

- `LICENSE`: **scope notice**, not a new outbound license; includes no blanket permission for unverified code/assets.
- `LICENSES/GPL-2.0-only.txt`: verbatim copy of pinned KDE Kaffeine upstream `COPYING`, not an assertion all TIHULU files are GPL-2.0-only.
- `NOTICE`: **preliminary** attribution and provider record, NOT final notice compliance.
- `SPDX_SOURCES_19.spdx.json`: valid-shape SPDX 2.3 source-file inventory with **133 unique filenames** and conservatively `NOASSERTION` conclusions/copyright. Git blob OIDs are *evidence identifiers*, NOT content SHA-1 checksums. Do not use this as a legally complete shipped SBOM.
- `PRELIMINARY_SBOM_19.json`: static/declaration-level native/Python/model catalog, **NOT** package-resolved installation evidence.
- `AI_MODEL_LICENSES_19.json`: separately acquired models and their asserted/verified evidence tiers; model licenses are independent of engine code.
- `SOURCE_PROVENANCE_19.json`: immutable source/version identities; only selected tree is included in installer; archived worktrees excluded.
- `tests/test_media_license_artifacts_19.py`: read-only structural/integrity guards and intentionally failing negative fixtures. CI cannot establish commercial permission.

## Specific GPL delivery requirements (not exhaustive legal advice)
If the project publishes a Kaffeine-derived executable it must accompany any applicable GPL notices and a compliant way to obtain complete corresponding source, including the original matching upstream, all modifications and scripts necessary to control compilation and installation. A link to `KDE/kaffeine` alone is insufficient when the distributed executable contains TIHULU modifications. Keep copyright notices, distribution license, source-availability language and an actual built-package inspection together in the release checklist. The GPL terms of source components are not overridden by optional AI model licenses. Review LGPL/GPL combinations and any OS/runtime-static-vs-dynamic linking facts on the **actual** executable.

## Bundled vs separately downloaded — crucial distinction
The selected standalone preview installer does **not** package model files, welle-cli binaries or third-party Python wheels into this Git commit. OS packages are provided by the target distribution; optional AI install actions may later pull wheels/models into private runtime locations. That distinction does NOT waive relevant license obligations for any component later shipped, hosted or distributed by TIHULU. The historical `kaffeine_next/install.sh` and `build-deb.sh` are source snapshots, not automatically an approved release path.

## Handoff / required independent gates
- Agent 01 security remediation PR #12 https://github.com/Tihulu/tihulu-media-center/pull/12 and later isolated successors.
- Agent 04 independent security reviewer: https://github.com/Tihulu/tihulu-media-center/pull/11#issuecomment-6833132950
- Agent 02 RF acceptance: https://github.com/Tihulu/tihulu-media-center/pull/13 ; no claimed real hardware tests by this compliance branch.
- Agent 03 real AI acceptance: https://github.com/Tihulu/tihulu-media-center/pull/14 ; model inference requires its own separate installed evidence.
- Agent 06 parity: https://github.com/Tihulu/tihulu-media-center/pull/11#issuecomment-6833109011

**PASS/HOLD:** immutable base/source integrity — conditional PASS after CI; model license restriction detection — source-level PASS after CI; GPL corresponding source — HOLD; complete resolved SBOM — HOLD; noncommercial model commerce — HOLD; complete notices — HOLD; physical RF/model inference — NOT RUN; public release — HOLD.

No merge/tag/release/owner-machine operations were authorized by these files.
