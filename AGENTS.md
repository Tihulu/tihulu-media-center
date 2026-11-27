# TIHULU Media Center — Agent Instructions

## Stable-first agent entry point (read on every new session)

- **Canonical project-specific AI instructions (on `main`):** [`docs/codex/CODEX_RESUME_PROMPT.md`](docs/codex/CODEX_RESUME_PROMPT.md). Read this before planning or making changes.
- **Detailed evidence and resumable state (separate Draft branch):** `docs/stable-first-codex-handoff-20261120`, files `docs/codex/START_HERE.md`, `STATE.json`, `KNOWLEDGE.jsonl` and append-only `HISTORY.md`. These additional files are **not yet merged to main**: explicitly check out or fetch the Draft branch, do not assume they exist on main.
- **Protected baseline:** Frozen source-only branch `stable-first-local-2026-11-12` at `7821769eb7aed576dd426ec18ffce3696d93a00d`; it does NOT prove installed Kaffeine binary parity.
- Verify current refs and CI independently. Distinguish reported tests from actual installation, security, UI and physical-device acceptance; all public releases remain **HOLD**.
- Do not modify working local installations, frozen snapshots, SDR/receiver services, recordings, settings, external AI models, previous Draft PRs, or release artifacts without separate explicit owner approval. Only authorized, isolated documentation/read-only/CI work is permitted.
- Do not upload private repository material, machine details or recordings to unapproved cloud models or public GitHub. No automatic embedding-model downloads, no remote vectorization. Read public knowledge snippets before creating a local index.
- Keep GitHub technical work in English. Report progress to the owner in Turkish. Preserve the app's independence and the full decision history.

## Working procedure

1. Read the application-specific Codex prompt on `main`.
2. Load detailed state and historical evidence from the explicitly named documentation Draft branch (if accessible).
3. Verify exact source SHAs, latest reviews and CI; propose a scoped continuation plan and independent QA gates.
4. Prefer no-op/read-only inspections, then isolated Draft PRs. Do not merge, install, release, start hardware or share protected private material without separate owner approval.
5. After a verifiable milestone, append dated historical evidence; do not silently rewrite old conclusions.
