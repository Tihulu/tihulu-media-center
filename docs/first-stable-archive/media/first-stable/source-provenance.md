# Source Provenance — TIHULU Media First Stable

## Provenance Status: HOLD

The exact source commit that produced the installed binary has NOT been conclusively
identified. However, this does NOT prevent preservation — the binary itself is the
source of truth.

## Evidence Collected

### 1. Upstream Source Checkout

| Property | Value |
|----------|-------|
| **Path** | `owner build tree: upstream checkout (not published)` |
| **Repository** | kaffeine upstream (KDE) |
| **Latest commit** | `e7ea15b` — "Changelog: update it with v2.0.19 changes" |
| **Tag** | `v2.0.19` |
| **Build type** | Release |
| **Shallow** | Yes (single commit history) |

This is an upstream-only clone. It does NOT contain TIHULU custom commits.

### 2. Build Directory

| Property | Value |
|----------|-------|
| **Path** | `owner build tree: build directory (not published)` |
| **CMake** | `CMAKE_PROJECT_NAME=kaffeine` |
| **Build type** | Release |
| **Config timestamp** | 2026-11-10 18:17 |
| **Build timestamp** | 2026-11-10 18:18 |

### 3. Historical Commit References (Unverified)

| Commit | Status |
|--------|--------|
| `426feb2ec386cc5bd114062aa08bee797c785c92` | Not conclusively linked to binary |
| `73698d2d9f99b5145a1ac429cb2ee16a77b5e1d6` | Not conclusively linked to binary |

### 4. Install Manifest

The install manifest (`install_manifest.txt` in the build tree) lists all installed
files but does not include source commit information.

## What We Know

1. The binary was built from a Qt5-based kaffeine source tree
2. Build type was Release
3. Custom TIHULU components were compiled into the binary
4. Build occurred on 2026-11-10 around 18:17-18:18 +0100
5. The upstream v2.0.19 tag is present but may not be the exact build source

## What We Don't Know

- Which exact commit (including TIHULU custom changes) produced the binary
- Whether TIHULU changes were on top of v2.0.19 or a different branch
- Whether the build used system libraries or bundled dependencies
- The full patch set that distinguishes this from stock Kaffeine

## Impact on FIRST STABLE

The provenance gap does NOT affect:

1. **Binary preservation** — The original ELF file is archived and verified
2. **Functional reinstallability** — The archive can restore the exact binary
3. **Installation testing** — The package can be installed and verified
4. **Rollback capability** — The original can always be restored from archive

The provenance gap affects:

1. **Byte-for-byte reproducibility** — Cannot guarantee rebuild produces identical output
2. **Upstream mergeability** — Cannot cleanly merge TIHULU changes back to upstream

**Conclusion:** Preserve the binary. Continue source investigation in parallel if needed.
Category: `LOCAL BACKUP PASS / SOURCE PROVENANCE HOLD`