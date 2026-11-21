# One-line install

```bash
curl -fsSL https://raw.githubusercontent.com/Tihulu/tihulu-media-center/fix/media-acceptance-record-playback/install.sh | bash
```

What it does:

- Clones the public source repository
- Builds the native TIHULU Media Center in your HOME
- Installs the Python companion and launchers in HOME
- Does not install AI models
- Does not modify an existing Kaffeine/TIHULU installation, model directory, settings, channels, recordings or tuner services

Optional dependency approval:

```bash
TIHULU_ALLOW_APT=1 curl -fsSL https://raw.githubusercontent.com/Tihulu/tihulu-media-center/fix/media-acceptance-record-playback/install.sh | bash
```

AI services:

- The application starts without AI.
- Open Settings -> Optional ASR & Translation Model Market to install or repair local models.
- If models already exist on the computer, the app reuses them; it does not force a re-download.

Rollback:

```bash
bash installer/media-stable-first.sh --rollback
```
