# Round-3 release verification (isolated install)

Verified on 22 November 2026 with the version installer, in a disposable HOME:

```
TIHULU_REPO_URL=<local mirror> bash versions/v1.1-round3/install.sh --install --no-ai
```

## Result

- Installer exit code `0`; release staged and selected atomically at
  `~/.local/opt/tihulu-media-stable/releases/r2-<snapshot>-<timestamp>`.
- `SOURCE-PROVENANCE.txt` records the **round-3 snapshot** and KDE Kaffeine
  `v2.0.19` (`e7ea15b86dafed3b20b151cbcb080578ab8e2d5c`).
- No AI models were downloaded; no owner installation, settings, recordings,
  channels, tuner or service was touched.
- Clean-environment GUI start (Xvfb, no AI models, no sound server): the
  application started and stayed alive, `0` fatal loader errors.
  `PulseAudio connection refused` is expected without a session sound server.

## Safety gates exercised (they correctly refused and were then fixed)

- Owner-writable-only managed directories (`0700`-style release root).
- Legal notices must be regular, single-link, `0644`, not group/other-writable.
- Pinned snapshot: the pinned commit is verified when present; a shallow tag
  clone installs the release commit it checked out, and records it in
  `SOURCE-PROVENANCE.txt`.
- Installer single-mode rule is preserved by the per-version wrappers.

## Still open

- GitHub push / Draft PR (blocked by the local environment's permission policy).
- CI AppDir/AppImage artifact verification once the branch is pushed.
