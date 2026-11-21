# Safe local testing without touching the installed app

Your currently installed TIHULU Media Center stays untouched during these tests.

## 1. Before test

Record the installed hashes:

```bash
sha256sum ~/.local/opt/tihulu-kaffeine/bin/kaffeine ~/.local/bin/tihulu-kaffeine
```

Expected:

```text
1211bd5f8e16267d4b7f7b537f2b2c5c218b204d786c85fa6119a0f8ffa0d502
85553f66f51ace8850950692a8648205bfee4b9416541ae45b60e8ac431ea2bf
```

## 2. Start isolated test profile

```bash
"/home/horseman/tihulu apps open code/media stable first/acceptance-owner-round3/start-fixed"
```

This uses:

- The candidate build
- A private HOME under the test directory
- Your existing model/runtime files as read-only assets; Argos translation weights stay read-only and only a private tokenizer cache is written inside the preview HOME
- Your display/session for a real owner test
- It does not write to `~/.local/opt/tihulu-kaffeine`

With a video file:

```bash
"/home/horseman/tihulu apps open code/media stable first/acceptance-owner-round3/start-fixed" "/home/horseman/Desktop/example.mp4"
```

## 3. After test

Verify installed system again:

```bash
sha256sum ~/.local/opt/tihulu-kaffeine/bin/kaffeine ~/.local/bin/tihulu-kaffeine
```

The same hashes mean the installed binaries were not changed.

## 4. Test a CI-produced AppDir

Download the artifact from GitHub Actions:

```text
tihulu-media-center-portable
```

Then extract and run it with a separate test HOME:

```bash
mkdir -p "$HOME/tihulu-appdir-test/home"
tar -xzf ./tihulu-media-center.AppDir.tar -C "$HOME/tihulu-appdir-test"
cd "$HOME/tihulu-appdir-test"
HOME="$PWD/home" \
XDG_CONFIG_HOME="$PWD/home/.config" \
XDG_DATA_HOME="$PWD/home/.local/share" \
XDG_CACHE_HOME="$PWD/home/.cache" \
XDG_STATE_HOME="$PWD/home/.local/state" \
TIHULU_ASSET_HOME="$HOME" \
./AppDir/AppRun
```

This keeps AppImage/AppDir settings separate from the installed app while still allowing reuse of existing AI models through `TIHULU_ASSET_HOME`.
