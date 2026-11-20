# Original Identity — TIHULU Media First Stable

## Executable Identity

| Property | Value |
|----------|-------|
| **File** | `~/.local/opt/tihulu-kaffeine/bin/kaffeine` |
| **Size** | 2,637,160 bytes (2.64 MB) |
| **Type** | ELF 64-bit LSB pie executable, x86-64 |
| **Linkage** | Dynamically linked, interpreter `/lib64/ld-linux-x86-64.so.2` |
| **Stripped** | No (not stripped — debug symbols present) |
| **Build Date** | 2026-11-10 18:18:14 +0100 |
| **Target** | GNU/Linux 3.2.0+ |

### SHA256 Hash

```
1211bd5f8e16267d4b7f7b537f2b2c5c218b204d786c85fa6119a0f8ffa0d502
```

**Verification:** `sha256sum bin/kaffeine` must produce the exact hash above.
If it does not, the file is NOT the original. Do NOT use it.

### ELF Build ID

```
f148596245a60e39b83e8dfb248641830b93ead3
```

**Verification:** `readelf -n bin/kaffeine | grep 'Build ID'`

## Launcher Identity

| Property | Value |
|----------|-------|
| **File** | `~/.local/bin/tihulu-kaffeine` |
| **Size** | 2,059 bytes |
| **SHA256** | `85553f66f51ace8850950692a8648205bfee4b9416541ae45b60e8ac431ea2bf` |

## Symlink

```
~/.local/opt/tihulu-kaffeine/bin/tihulu-media-center -> kaffeine
```

## Embedded TIHULU Components

The binary contains the following custom TIHULU components (not present in stock KDE Kaffeine):

| Component | Type |
|-----------|------|
| `TihuluRadioTab` | Custom radio tab widget |
| `TihuluBrassDial` | Custom tuning/brass dial widget |
| `TihuluMediaPanel` | Custom media control panel |
| `TihuluUnifiedRecorder` | Custom recording module |
| `TihuluHardwareTab` | Custom hardware configuration tab |
| `TihuluWebTvDialog` | Custom web TV dialog |
| `org.mpris.MediaPlayer2.tihulu_media_center` | MPRIS2 D-Bus interface name |

## Comparison with Stock Kaffeine

| Property | Stock KDE Kaffeine | TIHULU Custom |
|----------|-------------------|---------------|
| Package | `kaffeine` (apt) | Custom build |
| Install path | `/usr/bin/kaffeine` | `~/.local/opt/tihulu-kaffeine/bin/kaffeine` |
| Size | ~2.1 MB | 2,637,160 B |
| MPRIS name | `org.mpris.MediaPlayer2.kaffeine` | `org.mpris.MediaPlayer2.tihulu_media_center` |
| Custom tabs | None | 6+ custom TIHULU components |
| Build ID | Varies by distro | `f148596245a60e39b83e8dfb248641830b93ead3` |

**WARNING:** Do NOT replace this binary with `/usr/bin/kaffeine` from any package manager. That is stock KDE Kaffeine and will lose all TIHULU customizations.