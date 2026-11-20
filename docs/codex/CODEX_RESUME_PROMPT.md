# Codex resume prompt — TIHULU Media Center (stable-first)

> Paste the section below into a NEW Codex session with access to this repository. This is an inspection and planning request, **not authorization to install or release**. **Public release: HOLD.**

## Copy-paste prompt

You are continuing the **TIHULU Media Center stable-first preservation and independent reproducible packaging** project. Do not restart the project or overwrite working code. Do not assume synthetic test success proves the installed native application matches the source.

**Repository:** `Tihulu/tihulu-media-center`  
**Documentation handoff branch:** `docs/stable-first-codex-handoff-20261120` (Draft PR #24; not merged)  
**Protected source-only snapshot:** `stable-first-local-2026-11-12` at `7821769eb7aed576dd426ec18ffce3696d93a00d`  
**Prior tracked work:** issue #1 and Draft PR #23; inspect any newer work and verify HEAD/CI before trusting old reports.

### Step 1 — Read before acting
1. Read `docs/codex/START_HERE.md`, `STATE.json`, `KNOWLEDGE.jsonl`, `HISTORY.md`, `SEARCH_INDEX.md` and this file **from the documentation handoff branch**. Also read root `AGENTS.md` from that branch.
2. Read the frozen snapshot manifest and [archive-first issue #1](https://github.com/Tihulu/tihulu-media-center/issues/1). Inspect [Draft PR #23](https://github.com/Tihulu/tihulu-media-center/pull/23) as a prior checkpoint, not automatically the newest or approved implementation.
3. Record verified branch SHAs, provenance, test workflows, review scope, discrepancies and unknowns. Distinguish local installed binary from frozen source-only snapshot.

### Step 2 — Reconstruct the stable-first plan
- Preserve the existing custom KDE/Kaffeine desktop workflow and its channel/settings/recording behavior. Avoid modifying the existing installation.
- Track source selection precisely. Do not silently combine old `kaffeine_next`, `tv_center`, `textcenter` variants or reuse unreviewed legacy installers that fetch moving external branches.
- Split acceptance for DVB-T2 live TV, FM radio, DAB+, teletext, subtitles, Whisper ASR (CPU and optional CUDA), translation, AI profiles, EN/TR/DE UI, and full-file transcription. Existing synthetic CI is not hardware or runtime parity evidence.
- Plan deterministic source acquisition, auditable license/notice/SBOM review, clean Pop!_OS/Ubuntu packaging, repeat install, uninstall and rollback, and binary-to-corresponding-GPL-source proof. Optional model licenses and noncommercial weights must not be treated as automatically redistributable.
- Use disposable environments for non-destructive static/code tests only. Never use owner-host recordings, settings, local archives, AI weights, physical tuner, privileged actions, or production services without distinct explicit authorization.

### Step 3 — Knowledge and local retrieval
- Index only the public, source-linked `KNOWLEDGE.jsonl` chunks, never secrets, recordings, private binaries or system logs. Offline SQLite FTS5 is available through `docs/codex/index_local.py`; embeddings are **not precomputed**. Semantic vectors require an explicitly selected already-installed local model; no downloads, remote services or data egress.
- When a milestone is independently verified, update `STATE.json` and the affected knowledge chunks, append `HISTORY.md`, and cite exact SHA, CI URL and reviewer evidence. Preserve prior records.
- Put proposed code/remediation changes in separate isolated Draft PRs. **Do not merge, tag, publish, install or replace the user's working Media Center without separate owner approval.**

## Required output (in Turkish to the user)

Produce a compact evidence-based status report with:
- Exact source branch/commit and links actually inspected; distinguish baseline, current Draft, and installed runtime.
- Scoped PASS/HOLD for source integrity, isolated build, clean install, rollback/uninstall, native device/UI parity, security, licensing, and public release.
- Blockers grouped P0/P1/P2 and concrete next owner-safe tasks.
- Whether the local FTS index was executed/tested and whether semantic embeddings were actually generated; do not claim vectorization otherwise.
- A copyable next-session handoff, plus proposed documentation-only updates to STATE.json, KNOWLEDGE.jsonl and append-only HISTORY.md.

Never invent percentages, test results, successful hardware reception, model availability or release approval. Keep technical GitHub documentation in English.
