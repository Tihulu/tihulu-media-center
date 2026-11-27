# NOTICE20-P2-01 — version-anchored release format and fail-closed legacy recovery

**AGENT 01 · new isolated Draft remediation · PUBLIC RELEASE HOLD.**

## Frozen review inputs

Source baseline **PR #20** exact `3d7aae9c3fa23c785b178208a8e32ced590b703e` (261/261 scoped CI), independently reviewed by [Agent 04](https://github.com/Tihulu/tihulu-media-center/pull/20#issuecomment-6841585575) and [Agent 05](https://github.com/Tihulu/tihulu-media-center/pull/20#issuecomment-6841576102). Frozen app snapshot `7821769eb7aed576dd426ec18ffce3696d93a00d` unchanged. No prior PR or owner system modified.

## Confirmed exploit condition (P2 hardening, NOT cross-UID security)

Original PR #20 `verify_release` asks whether any of four legal paths are present on disk **or** in the mutable manifest. A malicious same-UID writer can remove **all three** `LICENSE`, `NOTICE`, `LICENSES/GPL-2.0-only.txt`, the `LICENSES/` directory and legal marker `.media-preview-legal-notices-v1`, then replace the 0600 self-declared manifest with a valid schema 1 inventory lacking all those entries. The PR20 verifier previously accepted that as a legacy release. The new adversarial negative-control fixture dynamically loads the exact PR20 Python source and independently observes that acceptance; the new verifier rejects it.

## Generation v2 policy — bind to pathname outside self-declared release metadata

- New installer creates release **basenames** only as `r2-<frozen12>-YYYYMMDDTHHMMSS-<pid>`, not historical `r-...`. Both names are strictly checked against one-leaf regexes; pointers may only use direct release children and continue the inherited content/owner checks.
- New `prepare-release` requires the independently computed versioned destination leaf, checks `r2-...` and all **three exact PR16 legal blobs plus owner-only marker** before writing the release manifest. Manifest schema **2** declares `format=TIHULU_MEDIA_LEGAL_NOTICE_RELEASE_V2`, the **exact r2 release_name** and the complete owned entry inventory. An `r2-` basename can never pass a legacy schema 1 manifest—even when every legal file, marker and evidence key has been removed and the manifest rebuilt.
- `verify_release` compares the actual release leaf to schema/format/name, checks every pinned legal file through no-follow inode ownership/size/nlink/mode/content validation, and recomputes full manifest. A forged or downgraded name, format or schema or absent/altered bundle **fails closed before rollback/uninstall**.
- Historical `r-...` **with an intact legal bundle** can continue verified rollback/uninstall under schema 1, preserving already-delivered PR20 notices and compatibility where positively observed. A notice-less `r-...` release **cannot be automatically proven genuine old**: a pre-PR20 installation and stripped/re-manifested PR20 release have indistinguishable attacker-writable bytes. They are deliberately classified **UNATTESTED** and `verify_release` returns HOLD for any automatic install, rollback or uninstall. There is no hidden automatic chmod, cleanup, repair or trust-on-first-use conversion.
- A separate **read-only** `audit-unattested-legacy PATH` confirms only format/remaining file integrity and explicitly says **'UNATTESTED LEGACY OR REWRITTEN PR20'**. This does **not** authorize automatic removal/rollback, certify age, or change a single byte. Owner-led independent provenance/recovery is required for genuine old notice-less installations; no new migration is attempted in this Draft.
- Historical standalone stage test fixtures outside a real `releases/` directory may verify an intact schema-1 legal bundle; this **is not an installed-release exemption**. All actual `releases/` descendants must have the strict v2 or strictly verified-notified old-name status to authorize mutations.

## Observable security boundaries and limitations

Changing the release directory basename **does not** make it immutable to a malicious same-UID actor. Renaming an r2 directory to r and rewriting a schema1 manifest after stripping legal still results in UNATTESTED HOLD. If an attacker forges an entirely different complete release, substitutes a noncooperating parent/mount, or wins a path race after verification, **SEC11-03 FULL SECURITY HOLD remains open**. No cryptographically authenticated external historical release registry predates PR20, so definitive positive identification of an already tampered pre-v2 release would be dishonest. No full-power-loss test, cross-UID exploit, production hardware or original owner machine has been exercised.

## Adversarial regression acceptance

The first disposable native integration failed closed when the new bash release name accidentally included a literal trailing `# NOTICE20-P2-01 — version-anchored release format and fail-closed legacy recovery

**AGENT 01 · new isolated Draft remediation · PUBLIC RELEASE HOLD.**

## Frozen review inputs

Source baseline **PR #20** exact `3d7aae9c3fa23c785b178208a8e32ced590b703e` (261/261 scoped CI), independently reviewed by [Agent 04](https://github.com/Tihulu/tihulu-media-center/pull/20#issuecomment-6841585575) and [Agent 05](https://github.com/Tihulu/tihulu-media-center/pull/20#issuecomment-6841576102). Frozen app snapshot `7821769eb7aed576dd426ec18ffce3696d93a00d` unchanged. No prior PR or owner system modified.

## Confirmed exploit condition (P2 hardening, NOT cross-UID security)

Original PR #20 `verify_release` asks whether any of four legal paths are present on disk **or** in the mutable manifest. A malicious same-UID writer can remove **all three** `LICENSE`, `NOTICE`, `LICENSES/GPL-2.0-only.txt`, the `LICENSES/` directory and legal marker `.media-preview-legal-notices-v1`, then replace the 0600 self-declared manifest with a valid schema 1 inventory lacking all those entries. The PR20 verifier previously accepted that as a legacy release. The new adversarial negative-control fixture dynamically loads the exact PR20 Python source and independently observes that acceptance; the new verifier rejects it.

## Generation v2 policy — bind to pathname outside self-declared release metadata

- New installer creates release **basenames** only as `r2-<frozen12>-YYYYMMDDTHHMMSS-<pid>`, not historical `r-...`. Both names are strictly checked against one-leaf regexes; pointers may only use direct release children and continue the inherited content/owner checks.
- New `prepare-release` requires the independently computed versioned destination leaf, checks `r2-...` and all **three exact PR16 legal blobs plus owner-only marker** before writing the release manifest. Manifest schema **2** declares `format=TIHULU_MEDIA_LEGAL_NOTICE_RELEASE_V2`, the **exact r2 release_name** and the complete owned entry inventory. An `r2-` basename can never pass a legacy schema 1 manifest—even when every legal file, marker and evidence key has been removed and the manifest rebuilt.
- `verify_release` compares the actual release leaf to schema/format/name, checks every pinned legal file through no-follow inode ownership/size/nlink/mode/content validation, and recomputes full manifest. A forged or downgraded name, format or schema or absent/altered bundle **fails closed before rollback/uninstall**.
- Historical `r-...` **with an intact legal bundle** can continue verified rollback/uninstall under schema 1, preserving already-delivered PR20 notices and compatibility where positively observed. A notice-less `r-...` release **cannot be automatically proven genuine old**: a pre-PR20 installation and stripped/re-manifested PR20 release have indistinguishable attacker-writable bytes. They are deliberately classified **UNATTESTED** and `verify_release` returns HOLD for any automatic install, rollback or uninstall. There is no hidden automatic chmod, cleanup, repair or trust-on-first-use conversion.
- A separate **read-only** `audit-unattested-legacy PATH` confirms only format/remaining file integrity and explicitly says **'UNATTESTED LEGACY OR REWRITTEN PR20'**. This does **not** authorize automatic removal/rollback, certify age, or change a single byte. Owner-led independent provenance/recovery is required for genuine old notice-less installations; no new migration is attempted in this Draft.
- Historical standalone stage test fixtures outside a real `releases/` directory may verify an intact schema-1 legal bundle; this **is not an installed-release exemption**. All actual `releases/` descendants must have the strict v2 or strictly verified-notified old-name status to authorize mutations.

## Observable security boundaries and limitations

Changing the release directory basename **does not** make it immutable to a malicious same-UID actor. Renaming an r2 directory to r and rewriting a schema1 manifest after stripping legal still results in UNATTESTED HOLD. If an attacker forges an entirely different complete release, substitutes a noncooperating parent/mount, or wins a path race after verification, **SEC11-03 FULL SECURITY HOLD remains open**. No cryptographically authenticated external historical release registry predates PR20, so definitive positive identification of an already tampered pre-v2 release would be dishonest. No full-power-loss test, cross-UID exploit, production hardware or original owner machine has been exercised.

 instead of a numeric shell PID. A new `test_22_native_release_name_contains_numeric_pid_expression` source test enforces that `final=` uses literal shell `$`. The repair changes no frozen application source and is validated via a fresh exact-HEAD native build.

New `tests/test_media_notice20_p2_generation_25.py` uses only isolated tempfile owner HOMEs; no real binary or tuner. It proves: original PR20 verifier accepts the all-absent+re-manifest downgrade (negative-control); new r2 verifier rejects it even with forged schema2; name→old-prefix rename is refused; a genuine notice-less legacy is audit-only; an intact old-name PR20 release passes; schema2 name/format forgery is refused; new v2 manifest cannot be minted without notices; two-release corrupt current/previous uninstall aborts **before any** `shutil.rmtree` call, no transaction is created and owner sentinel bytes remain; rollback with corrupt or unnotified previous holds without changing pointers; valid v2+notified old and two valid v2 releases uninstall owned data and preserve owner sentinel.

All prior security, native parity, 3/3 legal notice and GPL source-candidate tests remain available and unmodified. If original historical security fixtures deliberately modeled notice-less automatic legacy deletion, execute those **unchanged** in an exact PR20 detached worktree and report them as historical—not incorrectly as coverage of the new stricter policy. New policy regressions execute on the new exact HEAD. Real disposable Ubuntu native Kaffeine builds/install, rollback and double uninstall must remain green for newly minted r2 releases.

## Required independent review and release gates

Agent 04 must audit **this new exact SHA** with NOTICE20-P2-01 attack reproducer, legacy policy and rollback/uninstall safety, 2-release predelete checks, install shell regex, and the original SEC11-03 issues; scoped PASS does not equal fully adversarial GO.

Agent 05 remains owner of legal obligations: complete GPL corresponding source provided to recipients, final NOTICE/license holder clearance, ELF/codec/wheel/model SBOM, binary reproducibility and NLLB/audEERING noncommercial rights all **HOLD**. The existing 492-file source review candidate and its metadata+patch artifact are not a real source offering or approval.

Real SDR/DVB/FM/DAB hardware, CUDA/Whisper/translation model inference, actual owner binary/settings parity and public deployment/merge/install remain **HOLD**. No owner computer, services, models, settings, personal data or prior PRs are changed. **PUBLIC RELEASE HOLD.**