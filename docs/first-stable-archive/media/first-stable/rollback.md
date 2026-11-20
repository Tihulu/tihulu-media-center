# TIHULU Media First Stable — Rollback Procedure

> PUBLIC-REPO COPY: this runbook targets an OWNER-ONLY archive. Restoring overwrites the
> target prefix; the live installation is refused by the script unless `--live` is explicitly
> passed. Never run against a machine whose live installation must be preserved.

## When to Rollback

Use rollback if:
- The installed version causes system instability
- A new version fails and needs to be replaced with FIRST STABLE
- Testing reveals critical regressions

## Rollback from Archive

### Method 1: Using the Restore Script (Recommended)

```bash
cd <ARCHIVE_ROOT>
bash restore.sh
```

The script will (unless `--live` is passed, the live installation path is refused):
1. Verify archive integrity
2. Verify the critical binary hash
3. Back up the current installation
4. Restore the FIRST STABLE binary and files

### Method 2: Manual Rollback

```bash
# Backup current installation
cp -a ~/.local/opt/tihulu-kaffeine ~/.local/opt/tihulu-kaffeine-backup

# Restore from archive
cp -a <ARCHIVE_ROOT>/archive/bin/kaffeine \
       ~/.local/opt/tihulu-kaffeine/bin/kaffeine
ln -sf kaffeine ~/.local/opt/tihulu-kaffeine/bin/tihulu-media-center
cp -a <ARCHIVE_ROOT>/archive/share/* \
       ~/.local/opt/tihulu-kaffeine/share/
cp <ARCHIVE_ROOT>/archive/tihulu-kaffeine \
       ~/.local/bin/tihulu-kaffeine
chmod 755 ~/.local/opt/tihulu-kaffeine/bin/kaffeine \
          ~/.local/bin/tihulu-kaffeine
```

### Method 3: From GitHub Archive (Future)

Once the archive is published to GitHub:
```bash
# Download the tarball from the Stable tag
curl -L -o tihulu-media-first-stable.tar.gz \
  https://github.com/Tihulu/tihulu-media-center/archive/refs/tags/media-stable-v1.0.0.tar.gz
tar xzf tihulu-media-first-stable.tar.gz
cd tihulu-media-center-media-stable-v1.0.0
bash restore.sh
```

## Rollback Verification

After rollback, verify:
```bash
sha256sum ~/.local/opt/tihulu-kaffeine/bin/kaffeine
# Should output: 1211bd5f8e16267d4b7f7b537f2b2c5c218b204d786c85fa6119a0f8ffa0d502

readelf -n ~/.local/opt/tihulu-kaffeine/bin/kaffeine | grep "Build ID"
# Should show: Build ID: f148596245a60e39b83e8dfb248641830b93ead3
```

## Important Notes

- Rollback does NOT affect user data in `~/.config/kaffeinerc` or `~/.config/tihulu-media-centerrc`
- DVB channel settings in `~/.local/share/tihulu-kaffeine/` are preserved
- Recordings and media files are never modified by rollback
- The launcher script (`~/.local/bin/tihulu-kaffeine`) must be restored after rollback