# MEDIA — Codex Stable-First Handoff

Updated: 2026-11-20 (UTC). Status: **PUBLIC RELEASE HOLD**. This branch is documentation-only and is not an approved stable release.

## Read order (minimum context)
**To resume this application in a new Codex session, copy the ready-to-run [application-specific prompt](CODEX_RESUME_PROMPT.md).**

1. This file (constraints + entry point).
2. [STATE.json](STATE.json) (machine-readable exact baseline, current Draft, blockers, next actions).
3. [KNOWLEDGE.jsonl](KNOWLEDGE.jsonl) (small source-linked retrieval chunks; not embeddings).
4. [HISTORY.md](HISTORY.md) (append-only historical decisions).
5. Project source and evidence referenced in STATE; on Flight Radar also read existing root `AGENTS.md`.

## Current scope
Preserve custom Kaffeine-based Media Center working installation and frozen source; public release HOLD.

**Baseline:** `stable-first-local-2026-11-12` / `7821769eb7aed576dd426ec18ffce3696d93a00d` — frozen source snapshot; not rebuilt binary equivalence.

**Latest inspected work:** [Draft PR #23](https://github.com/Tihulu/tihulu-media-center/pull/23) at `9da09f2ec12d3e7ad6ad78898048e0da20bff479` — GPL corresponding-source delivery design and synthetic checks; not released. Exact CI/head must be freshly rechecked before working.

## Non-negotiable invariants
- No owner-host installation, binaries, settings, recordings, hardware, background services, model downloads, merges or release actions.
- Do not change the frozen source branch, existing TEXT-CENTER worktrees or previous Draft PRs.
- Source snapshot does not establish exact matching source/build for the installed binary.
- Optional models and redistributable rights need exact-artifact legal review.

## Safe continuation
1. Read GitHub issue #1, frozen source manifest and Draft PR #23 without modifying either.
2. Verify latest exact PR head and CI yourself; treat prior test counts as scoped reports only.
3. Plan isolated clean Pop!_OS/Ubuntu install and real-device parity tests, subject to owner approval.
4. Keep any local binary or private archive off GitHub; only owner-approved audited artifacts may be published.

## Retrieval indexing
Run `python3 docs/codex/index_local.py index` for an offline FTS5 search index stored outside Git; then `python3 docs/codex/index_local.py search "query"`. For **genuine semantic vectors**, run the same commands with `--model-dir /path/to/already-installed-local-embedding-model` using locally installed `sentence-transformers`. This is opt-in, strictly offline, no model download or cloud transmission; `KNOWLEDGE.jsonl` is vector-ready, not yet vector-embedded. Never commit private raw data or machine-generated index databases.

## Handoff updates
On a meaningful milestone, append HISTORY, update STATE + knowledge chunks, link exact PR head/CI URLs and PASS/HOLD claims. Do not overwrite history or infer acceptance from a CI green badge. Create a NEW isolated Draft PR; do not merge, tag, release or install without the owner's explicit separate approval.
