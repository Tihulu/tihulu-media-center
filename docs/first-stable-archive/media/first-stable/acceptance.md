# TIHULU Media First Stable — Acceptance Criteria & Results

## Test Matrix

### 1. Original Binary Preservation
| Test | Status | Evidence |
|------|--------|----------|
| SHA256 match | PASS | `1211bd5f8e16267d4b7f7b537f2b2c5c218b204d786c85fa6119a0f8ffa0d502` |
| Build ID match | PASS | `f148596245a60e39b83e8dfb248641830b93ead3` |
| Size match | PASS | 2,637,160 bytes |
| TIHULU markers in binary | PASS | TihuluRadioTab, TihuluBrassDial, TihuluMediaPanel, TihuluUnifiedRecorder, TihuluHardwareTab, TihuluWebTvDialog, org.mpris.MediaPlayer2.tihulu_media_center |

### 2. Archive Integrity
| Test | Status | Evidence |
|------|--------|----------|
| Archive directory exists | PASS | `<ARCHIVE_ROOT>/archive/` |
| manifest-verified.sha256 valid | PASS | 114 files verified, 0 FAILED |
| Critical binary in archive | PASS | `archive/bin/kaffeine` hash verified |
| Symlink preserved | PASS | `archive/bin/tihulu-media-center -> kaffeine` |
| Launcher in archive | PASS | `archive/tihulu-kaffeine` hash verified |
| Share resources in archive | PASS | icons, locales, desktop files, scanfile.dvb |

### 3. Package Scripts
| Test | Status | Evidence |
|------|--------|----------|
| install.sh created | PASS | Validates archive before install |
| verify.sh created | PASS | Checks all critical hashes |
| restore.sh created | PASS | Backs up live install before overwrite |
| rollback.md created | PASS | Documented rollback procedures |

### 4. Documentation
| Test | Status | Evidence |
|------|--------|----------|
| README.md | PASS | Overview and quick verification |
| original-identity.md | PASS | Binary identity and comparison table |
| source-provenance.md | PASS | Build provenance analysis |
| runtime-dependencies.md | PASS | Complete dependency list |
| manifest.sha256 | PASS | Quick reference manifest |
| VERSION | PASS | 2.0.19-tihulu-custom |

### 5. Platform Compatibility
| Test | Status | Evidence |
|------|--------|----------|
| x86_64 ELF | PASS | Confirmed via readelf |
| Qt5 runtime | PASS | All Qt5 libs found in system |
| KDE Frameworks 5 | PASS | All KF5 libs found in system |
| VLC integration | PASS | libvlc.so.5, libvlccore.so.9 present |
| DVB support | PASS | libdvbv5.so.0 present |

### 6. Source Provenance
| Test | Status | Evidence |
|------|--------|----------|
| Upstream source identified | HOLD | v2.0.19 tag found, exact TIHULU patches unknown |
| Build timestamp known | PASS | 2026-11-10 18:17-18:18 +0100 |
| Build system known | PASS | Qt5 CMake Release build |
| Reproducible rebuild | HOLD | Source not fully identified |

### 7. GitHub Distribution
| Test | Status | Evidence |
|------|--------|----------|
| Repository verified | HOLD | Tihulu/tihulu-media-center needs verification |
| Archive branch created | HOLD | Pending GitHub access |
| Draft PR created | HOLD | Pending GitHub access |
| Binary NOT published | PASS | Requires separate authorization |

### 8. Clean Restore Test
| Test | Status | Evidence |
|------|--------|----------|
| Clean environment test | HOLD | Requires disposable VM/container |
| GUI launch test | HOLD | Requires display server access |
| Media playback test | HOLD | Requires media files |

## Overall Status

LOCAL ARCHIVE: **PASS** (verified with real evidence)
GITHUB RECOVERY: **HOLD** (awaiting authorization)
CLEAN RESTORE: **HOLD** (requires isolated environment)
SOURCE REPRODUCIBILITY: **HOLD** (exact source unknown)