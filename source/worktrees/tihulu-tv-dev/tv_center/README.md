# TIHULU TV Center — Native Debian/Pi + Pages companion

**Status: experimental v0.1, untested on actual Raspberry Pi 5 and not a finished stable release.**

A standalone, native Qt Widgets + MPV DVB-T/T2 television frontend for **Debian, Ubuntu,
Pop!_OS COSMIC and 64-bit Raspberry Pi OS on Raspberry Pi 5**. The receiver runs locally:
the browser is **not** asked to use WebUSB. A separate GitHub Pages client can view
real captions and request Teletext pages through an **opt-in token-protected loopback bridge**.

The project lives beside the existing TEXT CENTER services. TV and offline AI workers
reuse the already implemented `textcenter.speech`, `textcenter.compute` and
`textcenter.transcripts` modules. Existing Flight Radar/readsb, Satellite Center,
NooElec NESDR and protected RTL-SDR allocations are not touched.

## Verified from the user's previous Linux tests (not retested by this new app)

- Hauppauge WinTV-soloHD USB `2040:8268`; `em28xx`, `Si2168-D60`, firmware
  `dvb-demod-si2168-d60-01.fw`; `/dev/dvb/adapter0`.
- Successful `dvbv5-scan` channel files: `~/tv-538-channels.conf` (ZDF/KiKA),
  `~/tv-586-channels.conf` (Phoenix/NDR), `~/tv-626-channels.conf` (RTL, often encrypted).
- Kaffeine sometimes embedded video only under `QT_QPA_PLATFORM=xcb`; libVLC had
  VDPAU allocation failures, AAC-LATM issues and significant UCB / TS continuity errors.
- KiKA Teletext subtitles actually displayed; ARTE Teletext page 100 was readable,
  but automatic subtitle selection and page 150 were unreliable.
- RF reception must be improved: this app cannot repair missing DVB frames.

## Run native (development checkout)

Install distro dependencies (nothing in the install process is silently downloaded by the app):

```bash
sudo apt update
sudo apt install python3 python3-pyqt5 dvb-tools mpv ffmpeg psmisc
# In repository root:
python3 -m tv_center doctor
QT_QPA_PLATFORM=xcb python3 -m tv_center
```

On Raspberry Pi 5 use the 64-bit Raspberry Pi OS / Debian packages. Video output
may require a compatible X11/XWayland session. The default MPV hardware
decoder is OFF to avoid repeating Kaffeine's NVIDIA VDPAU failure; for Pi 5,
try `auto-safe` explicitly if installed GPU codecs are confirmed. The Pi 5's
real-world HEVC 1080p decode/transcoding and Whisper performance are **not verified**.

You can also build a Debian package using `bash tv_center/packaging/build-deb.sh`;
this creates an `Architecture: all` package. The architecture-neutral Python
package does not imply tested ARM64 video acceleration.

## Tune and scan

The application automatically lists existing `~/tv-*-channels.conf` files, so
your previously verified frequencies and channel list are reused without rescanning.
It runs `dvbv5-zap -a 0 -c ... -p -P -r "Channel name"`, reads only
`/dev/dvb/adapter0/dvr0`, and feeds the live MPEG transport stream to embedded MPV
using the DVB service ID. Other DVB owners (Kaffeine/Tvheadend) must be stopped first.

A manual scan button accepts a genuine initial transponder file from
`/usr/share/dvb/dvb-t/`. It runs `dvbv5-scan` explicitly and writes
`~/.config/tihulu-tv-center/channels.conf`.
Country-specific scanning profiles/EPG service indexing are not implemented in v0.1.

## Captions, Teletext and installable languages

Choose **Off**, **Broadcast Teletext**, **Live transcription**,
**Teletext first → ASR fallback**, or **Teletext page viewer**. Enter page
100–899 directly; ARTE/ARD commonly use 150, while ZDF captions may use 777.
The application captures only short (up to 12-second, max 24-MiB) temporary
MPEG-TS segments while a subtitle mode is enabled. FFmpeg with **libzvbi**
decodes actual broadcaster Teletext into text; page rendering is text-only
in this preview, not full colored Level 1 Teletext graphics.

For spoken transcription, the app needs a **locally installed multilingual**
`whisper.cpp` CLI and a user-selected GGML Whisper model. No model is bundled.
`textcenter.speech` may choose a supported local CPU/GPU backend; GPU/NPU
is never inferred just because a device is present. Chunk sizes and model
speed mean subtitles are delayed, not word-by-word zero-latency.
Translation is performed by existing offline Argos, with **Turkish, German,
English** selectable independently as source and target. Install
`argostranslate` in an environment that can import PyQt5 (e.g. a venv with
`--system-site-packages`) and use the **Install local .argosmodel** button.
Missing language pairs show a real error; no invented translations.

This first decoding path parses the first discovered Teletext/audio stream in
the selected TS multiplex. On multi-service multiplexes the mapping to the
current service still needs a hardware-stream acceptance test.

## Web companion / GitHub Pages

The static site lives in `tv_center/web/`. On GitHub Pages it should be
published at `https://tihulu.github.io/TIHULU-TEXT-CENTER/tv_center/`
**after** the repo's Pages build includes that directory (do not replace
the existing TEXT CENTER, Flight Radar or Satellite pages).

The desktop app starts **no HTTP service by default**. Enable its local bridge
manually; paste the session token into the Pages interface. The bridge binds
only to `127.0.0.1:8768`, allows exactly the project Pages origin for CORS,
and exposes real read-only status/captions plus an explicit Teletext page
request. Browser localhost/private-network protections may prevent the
connection. To access a Pi across the LAN, a separate authenticated TLS
reverse proxy with owner isolation is required; it is NOT bundled.

**Video playback in the Pages companion is not implemented.** Raw DVB MPEG-TS/
HEVC is not reliably supported by ordinary browser media elements. A properly
secured, demand-started browser-compatible video relay would need additional
transcoding/buffering and Pi hardware testing. Do not mislabel the web preview
as a working remote television player.

## Acceptance criteria and current gaps

Unit tests run without RF hardware. Real DVB-T2 lock, service selection,
Teletext page extraction, French subtitles, subtitles on video, model
latency, Pi 5 acceleration, all scanners, EPG and the Pages local
connection must be verified on real devices before a stable release.

No background tuner activity, no auto RF or AI sessions, no network or
model download without user action, no automatic SDR preemption.
