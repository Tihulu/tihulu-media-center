# MEDIA-PARITY16-DIAGNOSTICS-AND-TV-ROUTING-20

**Status:** Draft-only independent remediation; PUBLIC RELEASE HOLD.

**Frozen snapshot:** `7821769eb7aed576dd426ec18ffce3696d93a00d` (byte-for-byte unchanged).
**Isolated parent:** SEC09 Draft PR #11 SHA `2f5699eeb47505468bf3327be4dbdd89fed3dff1`.
**Prior baseline CI:** https://github.com/Tihulu/tihulu-media-center/actions/runs/43196547501, 151/151 CI PASS (synthetic and disposable installed runtime; NOT RF acceptance).
**Prior audit:** https://github.com/Tihulu/tihulu-media-center/pull/11#issuecomment-6833109011.

## PARITY16-01 — native DVB diagnostics

Frozen `kaffeine_next/patch_upstream.py` injects a native menu action looking for:
`QDir::homePath() + "/.local/share/tihulu-kaffeine/dvb_diagnostics.sh"`.

The standalone installer isolates `HOME` in `$APPROOT/preview-home`, but copies the unchanged frozen diagnostics script to `$release/py/kaffeine_next/dvb_diagnostics.sh`. It never creates the former path. The exact PR #11 native executable will therefore select a missing path, even though the script is bundled.

The **isolated installer** now replaces this *one exact C++ expression* **after** applying the unmodified frozen Kaffeine patch, **inside the disposable upstream build tree only**, with:

```cpp
QStringList() << QDir::cleanPath(
    QCoreApplication::applicationDirPath() +
    QLatin1String("/../../py/kaffeine_next/dvb_diagnostics.sh"))
```

The packaged script remains unchanged. Build fails closed unless exactly one original occurrence was found, the script is staged, and the compiled native ELF embeds the installed-relative path without the old HOME path. Because the native executable resides at `$release/native/bin/kaffeine`, resolving `../../py/kaffeine_next/dvb_diagnostics.sh` points to the bundled script in *that same release*, even after rollback.

## PARITY16-02 — direct Python TV command

Frozen `tv_center.__main__` locates `Path.home()/".local/bin/tihulu-kaffeine"` on direct `python3 -m tv_center tv`. Original supported standalone public route `$release/bin/tihulu-tv-center tv` already dispatches correctly to `$release/bin/tihulu-kaffeine`; **do not regress it**.

The installer now creates exactly one **preview-only** compatibility symlink:

```
$APPROOT/preview-home/.local/bin/tihulu-kaffeine
    -> $APPROOT/current/bin/tihulu-kaffeine
```

This makes *isolated* direct Python invocation work with `HOME=$APPROOT/preview-home`, `TIHULU_MEDIA_OWNER_HOME=$REAL_OWNER_HOME` and `PYTHONPATH=$release/py`. It never writes into the owner's actual `~/.local/bin`. The operation validates ownership, non-symlink `preview-home/.local/bin` and its parent permissions, uses an `O_NOFOLLOW|O_DIRECTORY` directory FD and `symlinkat`-style exclusive creation, and rejects any foreign or differing destination instead of replacing it. The stable `current` pointer makes rollback reuse the same link. No additional native launcher or model downloads.

**Uninstall and privacy contract:** the preview-private profile is intentionally retained by the inherited uninstaller, and its compatibility symlink is retained too (it becomes dangling when `current` is deactivated). It must not be mistaken for an executable in the owner's real HOME. Do not clean the private profile without separate explicit owner consent.

## Reproduction and acceptance — CI evidence policy

Dedicated isolated workflow: `.github/workflows/media-parity16-diagnostics-tv-routing-20.yml`.

1. **Baseline negative control:** check out **exact PR #11** in a Git worktree; build/install native Kaffeine in a fresh temporary Ubuntu 24.04 HOME; assert the *original native ELF* embeds the stale HOME diagnostics path while the script exists only under `release/py`; assert direct isolated `python3 -m tv_center tv` returns 2 with the old missing-Kaffeine message. These are actual **disposable native installation reproductions**, not source-only suspicions.
2. **Frozen + source safety:** rerun the inherited 105 source/security/AI tests unchanged, add three PARITY16 source guards, check original frozen identity, Bash/ShellCheck and pinned dry-run.
3. **Corrected installed native:** two clean Ubuntu 24.04 native builds/installs, inherited 10 installed runtime + 13 synthetic TV/Radio/Teletext/Lyrics/Karaoke suites per install, plus five PARITY16 tests per install, including native ELF/script path, bash diagnostics with **no `/dev/dvb` permitted**, supported wrapper, private pointer, direct Python **actual GUI under Xvfb**. Check rollback, repeated uninstall and real-HOME private sentinels unchanged.
4. **CI exact-head required:** workflow success and SHA must be inspected before announcing tests as PASS.

All TV/Radio/Teletext/Lyrics fixture inputs are **synthetic**; native launch is real Ubuntu GUI under Xvfb; negative-control native binary is real compilation; no tuner, FM/DAB, actual audio, recording, model inference, CUDA, owner configuration or original binary is used.

## PASS / HOLD and dependencies

| Gate | Required evidence | Decision until latest exact-head CI |
| --- | --- | --- |
| Frozen source unchanged | git diff and byte identity | PENDING CI |
| PARITY16-01 baseline negative and fixed native | actual native ELF + script in disposable Ubuntu | PENDING CI |
| PARITY16-02 baseline negative and fixed direct Python GUI | native installed launch with private HOME | PENDING CI |
| Inherited 151 tests | source + two native installations | PENDING CI |
| No private owner data / no hardware / no models | disposable fixture and test command contract | PASS by isolation scope; not owner acceptance |
| SEC11/SEC12 security remediation & independent Agent 04 review | https://github.com/Tihulu/tihulu-media-center/pull/12 and subsequent newer Draft | HOLD |
| Hardware / actual speech and translation inference | Agents 02/03 independently authorized acceptance | HOLD |
| GPL, SBOM, model redistribution review | Agent 05 independent license acceptance | HOLD |
| Owner-original binary/settings equivalence and approval | explicitly authorized read-only compare | HOLD |

**No merge, release, real owner-machine access, source edits, tuner/service/model operations, migrations, downloads of models or automatic installation. PUBLIC RELEASE HOLD.**
