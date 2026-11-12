# MEDIA DISTRIBUTION COMPLIANCE 23 — disposable evidence, NOT a release

**PUBLIC RELEASE HOLD.** This isolated continuation is stacked only on independent-reviewed integration PR #18 at exact HEAD e5271965dadaf82c4be1a336396d0e9b3a083b8d. Licensing PR #16, the integrated application source, installer, security tests and archived frozen sources remain unchanged.

The disposable GitHub Actions Ubuntu 24.04 job builds the native KDE Kaffeine v2.0.19 executable through the existing integrated installer using --no-ai in a temporary CI HOME. A second pinned upstream clone is patched with the frozen patcher and the exact in-installer native parity modification, and retains an independent **candidate corresponding-source directory** in the disposable runner. Its metadata includes exact upstream and frozen Git IDs, patch SHA-256 and selected source files. **This candidate is NOT a complete legal corresponding-source offer** and is not distributed with a release binary.

The probe inspects the actual built ELF SHA-256, readelf direct NEEDED entries, ldd resolution of that trusted self-built executable, dpkg ownership/versions and the presence/digests of system copyright files (not inferred license grants). Python metadata records the runner's available distributions, NOT a completed optional AI wheel or CUDA SBOM. The selected 133 source files are checked for missing per-file SPDX headers; the preexisting SPDX inventory still has NOASSERTION for all 133 file license/copyright conclusions.

The native staged release is checked for LICENSE, NOTICE and the GPLv2 license text; absence is a distribution blocker, while presence alone would still need independent legal and package acceptance. The source-only root LICENSE/NOTICE is not proof that recipients received notices with the binary. No AI model is downloaded or run; any unexpectedly bundled model artifact causes CI failure. NLLB-200 remains CC-BY-NC-4.0 and audEERING age/gender remains CC-BY-NC-SA-4.0. Optional Argos packs, converted Whisper models and Qwen/MADLAD revisions require exact artifact-level verification; engine licenses do not automatically authorize weights.

The workflow uploads **only JSON evidence**, not a binary, source candidate, source tarball, model, user's private files or general-use installer. The evidence is ephemeral, not a publication or permission to ship. No owner machine, external services, RF tuners or user applications are accessed. The GitHub Actions runner installs apt build dependencies only in its disposable environment.

## Explicit acceptance matrix
| Gate | Evidence / decision |
| --- | --- |
| Source identity and four compliance-only changed files | PASS if CI verifies exact SHA and frozen source |
| Actual disposable compiled ELF and observed native dependencies | scoped PASS if CI completes |
| Observed runner Python metadata | scoped PASS, final wheel graph HOLD |
| Independently reconstructed modified source candidate | candidate PASS, legal corresponding-source distribution HOLD |
| GPL source/NOTICE delivered with actual binary | HOLD until tested and accepted |
| Fully resolved native/Python/codec/CUDA SBOM | HOLD |
| Copyright owner permissions and per-file license statements | HOLD |
| NLLB/audEERING commercial rights, Argos/other models | HOLD |
| Physical hardware, real AI inference, owner application parity | NOT RUN |
| Public merge, installation, release or owner approval | HOLD |

## Dependencies / follow-up
- Agent 01 integration PR #18 and Agent 04 independent review: https://github.com/Tihulu/tihulu-media-center/pull/18#issuecomment-6838435488 (residual same-UID filesystem races, full security HOLD).
- Agent 05 source-only licensing PR #16: https://github.com/Tihulu/tihulu-media-center/pull/16 (preliminary notices, 133-file SPDX, 30-component declared SBOM, 9 opt-in models).
- Agent 06 parity PR #17, Agent 02 physical acceptance PR #13 (0/41 physical tests at last handoff), Agent 03 real AI acceptance PR #14 (actual inference not approved).
- Next: independent auditor inspects CI evidence JSON, resolves actual corresponding-source delivery and full notices, exact optional wheel/dlopen/codec dependency rights, every unlicensed file/icon rightsholder and model revision. Only owner approval can authorize any release. **PUBLIC RELEASE HOLD.**

**Observed Debian diversion edge case:** dpkg-query -S for the ELF interpreter can first return a diversion record rather than an actual package. Evidence collector explicitly ignores such records and accepts only valid package-name lines (with a synthetic negative regression). This repairs package ownership reporting; copyright-file presence is still NOT a legal permission conclusion.
