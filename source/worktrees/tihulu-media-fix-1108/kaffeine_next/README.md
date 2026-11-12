# TIHULU TV — Kaffeine-native rebuild (experimental)

A **real C++ source-code extension of KDE Kaffeine**, not another
unrelated Python DVB player. Uses pinned Kaffeine **v2.0.19** at immutable
upstream commit **e7ea15b86dafed3b20b151cbcb080578ab8e2d5c**.
Source transformations are in patch_upstream.py and keep Kaffeine's GPL
licensing and contributor notices.

## One-line installation

Debian/Ubuntu/Pop!_OS and 64-bit Raspberry Pi OS:

~~~bash
curl -fsSL https://raw.githubusercontent.com/Tihulu/TIHULU-TEXT-CENTER/architecture/kaffeine-core-tv-2026-11-07/kaffeine_next/install.sh | bash
~~~

Read the script first if preferred. It installs the KDE/Qt5 DVB build
dependencies, clones verified upstream code, patches, compiles and installs
the new application under HOME/.local/opt/tihulu-kaffeine. The normal
installer also attempts to install user-owned Whisper Tiny (~78MB),
whisper.cpp CPU and German/English/Turkish Argos translation packages.
A failed model installation does NOT uninstall or disable TV. All downloads
are initiated by the user's explicit installation action.

Start:

~~~bash
~/.local/bin/tihulu-kaffeine
~~~

A separate **TIHULU TV (Kaffeine)** desktop entry is installed. The original
system Kaffeine executable and personal channel database are preserved.
Both Kaffeine builds may share settings, so back up settings before
experimenting; close the original Kaffeine before starting the fork.

## Kaffeine-style player and native antenna scan

**There is now only one default television interface:** Kaffeine's original
channel sidebar, live player, normal playback controls, EPG, channel editor,
Teletext and recording UI. Opening either `tihulu-tv-center` or
`tihulu-kaffeine` launches **Kaffeine's Television tab**. The separate
Python player and w_scan_cpp scanner have been withdrawn from the default
route; the old preview is available explicitly through
`tihulu-tv-center legacy-player` for debugging only.

To use the **actual native Kaffeine antenna scanner** on a device already
known to receive the three DVB-T2 multiplexes:

1. Quit any other Kaffeine or DVR program which owns the same DVB frontend.
2. Open **Television → Configure Television → Device 1 → DVB-T2**.
   Ensure **DVB-C Source = No Source** for an aerial antenna, and select
   **Source = TIHULU tested: 538 / 586 / 626 MHz** for DVB-T2.
   This targeted source uses the frequencies previously detected on the
   owner's antenna, not fabricated channel entries. It is optional and
   not a claim about other cities in Germany.
3. Choose **Television → Full Antenna Scan...**. If video is playing,
   confirm that Kaffeine may stop live playback temporarily: this releases
   the frontend for a full frequency sweep rather than restricting the
   normal **Channels** editor to the currently playing transponder.
   Select **Terrestrial (T2)** as Source, then Start Scan. Kaffeine itself
   tunes and obtains real channel service tables. When services appear,
   choose TV/free-to-air filters, **Add Filtered** or **Add Selected**, then OK.
4. Alternatively use Kaffeine's own **Autoscan** DVB-T2 source for a
   broader real frequency sweep. It can take longer and may fail to
   resolve services if RF signal or PLP selection is unstable.

The targeted scan source is implemented *inside Kaffeine's own
DvbManager::getTransponders* so it continues working even if the optional
scanfile.dvb is missing or stale. This does not use w_scan_cpp, dvbv5-scan,
Python USB access or WebUSB, and does not touch saved channel databases.

For separate receiver health diagnostics (which must **not** take the tuner
away from Kaffeine), run `tihulu-tv-center kaffeine-doctor`. Lock and
C/N/UCB cannot be honestly measured while Kaffeine owns the tuner; use
Kaffeine's own scanning UI metrics instead.

## Feature architecture

- **Real TV:** upstream Kaffeine owns USB DVB device, discovery/scanning,
  EPG, favorites, DVR/timeshift, built-in Teletext and existing libVLC player.
  The user's Kaffeine scan results, not new synthetic channel catalogs, are
  the starting point.
- **Whisper & Translator Market:** native Kaffeine TIHULU AI menu opens
  the existing installed market with Tiny/Small, DE/EN/TR Argos packs,
  external SSD storage, user-managed updates/deletions and backend
  CPU/GPU/NPU compatibility checks. No AI inference runs by default.
- **Caption and Teletext:** a separate always-on-top caption controller
  offers real Teletext page 100-899, broadcaster subtitle, Whisper ASR and
  fallback. Source and translated captions are displayed together, with
  actual processing latency. Six-second overlapping capture chunks plus
  inference latency mean this is NOT word-for-word instantaneous.
- **Same tuner, selected channel:** Kaffeine's DvbLiveView copies its
  already-filtered MPEG-TS packets into a bounded nonblocking private
  UNIX datagram socket only when a caption consumer is listening.
  No second frontend open, scan or PID filter; slow AI consumers drop their
  own copies and cannot block ordinary TV playback.
- **iPhone/Android from the same Wi-Fi (experimental):** caption controller
  can explicitly enable local Wi-Fi access with a six-digit PIN; separate
  H.264/AAC HLS switch transcodes the current Kaffeine program using
  FFmpeg. The program ID is extracted from the real MPEG-TS PAT. Changing
  the service stops the old HLS stream; restart manually. iPhone Safari
  supports native HLS; Android may need the bundled web client's hls.js
  library which is currently loaded from the Internet.
- **GitHub Pages:** informational/static web companion. Pages/WebUSB
  cannot access Kaffeine's tuner remotely or replace Linux DVB drivers.
  Telephones use the locally paired host web app.

## Pop!_OS / COSMIC / Conda Qt5 linker troubleshooting

When the old installer ends with a long list of
libQt5WaylandClient.so.5 missing QVulkanInstance or Qt_5_PRIVATE_API
symbols, the **link stage failed**. The missing executable/launcher is
a consequence of that earlier failure, not a missing PATH entry.
It often indicates that the linker picked Qt components from incompatible
builds (e.g., Conda base Qt5 plus Ubuntu Qt5) or the distro has
inconsistent Qt5Gui/Qt5WaylandClient packages. It is not proof that
Kaffeine's DVB device or Vulkan GPU acceleration is broken.

The updated one-line installer now configures and compiles using a
**clean system toolchain environment**, ignoring Conda linker/CMake/Qt
plugin path variables. It uses CMake --fresh in a new build directory,
so previously contaminated CMakeCache.txt cannot be reused. The
finished XWayland launcher similarly ignores Conda's Qt plugin and
library paths. Existing Kaffeine, SDR apps and the old build directory
remain untouched.

Retry the same installer from any shell, including (base); no manual
Conda deletion required. Build logs are saved under
HOME/.local/share/tihulu-kaffeine/logs/configure.log and build.log.

If undefined Qt_5_PRIVATE_API symbols remain after a clean build, inspect
the distribution packages before modifying system libraries:

~~~bash
dpkg-query -W libqt5core5a libqt5gui5 libqt5waylandclient5 qtbase5-dev
apt-cache policy libqt5gui5 libqt5waylandclient5
ldd -r /lib/x86_64-linux-gnu/libQt5WaylandClient.so.5 | grep -E 'not found|undefined'
~~~

**Do not** work around missing Qt symbols by ignoring linker errors,
forcing ABI-incompatible libraries or replacing system libQt5Gui.
The source-build CI proves it works with Ubuntu 24.04 distro Qt;
a particular desktop still needs runtime and DVB hardware testing.

## Live Whisper quality: GPU, missing speech and longer A/V buffer

The original first implementation threw away **an entire 4-second MPEG-TS
chunk whenever the previous Whisper calculation was still running**.
That creates speech gaps *before* translation. A TV playback delay cannot
restore those lost words.

The new Kaffeine-caption worker accepts **6-second continuous windows** with
approximately **1-second overlap** to preserve syllables/phrases crossing
segment boundaries. Every captured segment enters a chronological **bounded
FIFO** rather than being discarded when inference is busy. The default
desktop queue is 96 MiB (48 MiB on a Pi-family device), up to 24 clips.
This is finite storage, not a claim of guaranteed lossless recording
if CPU processing remains slower than capture indefinitely. The UI reports
queue depth and any overflow explicitly. Repeated words caused by overlap
are trimmed **before** sending the text to Argos/NLLB translation, so they
don't contaminate the translation.

The TV **audio+video delay is now manually adjustable from 0 to 20 seconds**.
The opt-in automatic recommender caps itself at 12 seconds on a desktop,
6 seconds on a Raspberry Pi 5, and may choose less when the actual MPEG-TS
bitrate would exceed the reserved memory. Audio and video are delayed
*together*; this is not the same as a caption-offset/lip-sync meter.
The underlying C++ buffer is still capped at 64 MiB and reverts safely
if an extremely high-bitrate service exceeds the cap.

To determine whether Whisper is actually accelerated, the caption status
explicitly reports **Whisper: GPU / CPU / NPU** and selected model when
the ASR engine is used. Hardware detection in the Model Market alone is
not proof of a working CUDA model. In particular, the Pop!_OS Kaffeine
`--software-video` switch affects **libVLC HEVC video rendering**, NOT
the separate CUDA Whisper speech engine. Both may be enabled together.

### NVIDIA RTX 5080: two independent GPU Whisper installation paths

**Recommended first:** in **TIHULU AI → Whisper + Translator Model Market**,
choose **Install CUDA Faster-Whisper Large-v3 Turbo · no nvcc needed**.
After confirmation, the installer creates an isolated user-owned Python
virtual environment with CTranslate2 Faster-Whisper and CUDA 12 cuBLAS/cuDNN
libraries; it downloads and hashes a pinned multilingual CT2 Large-v3 Turbo
model. The downloaded weights may live on the model-storage external SSD.
The CUDA ASR worker remains alive and retains model weights across live
six-second captions, avoiding per-segment startup/model loading. It does
**not** install/change the NVIDIA graphics driver or system CUDA toolkit.
It does not touch the DVB frontend, Kaffeine or the GGML CPU model.

**Alternative:** CUDA `whisper.cpp` engine plus multilingual GGML Large-v3
Turbo / Large-v3 Turbo Q5. Compiling this path on RTX 50-series requires a
CUDA toolkit with `nvcc` >= 12.8 and separate user action; this requirement
does not apply to the prebuilt Faster-Whisper wheel path.

Restart captions after installation. Select **GPU** or **Auto**, turn on
offline transcription, and inspect `tihulu-tv-center ai-check`. A successful
installation should report `selected_backend: gpu`,
`backend_ready: true`, `known_gpu_engine: faster_whisper_managed`.
These values describe *readiness*, not confirmed live inference accuracy
or end-to-end caption latency. The live caption status should identify
**large-v3-turbo** and the actual worker backend; `--software-video`
continues to affect only libVLC video decoding. Verify on a physical
DVB-T2 broadcast before claiming speech-gap or synchronisation fixes.

If the CUDA worker cannot run with the host's installed NVIDIA driver,
it remains **not ready** and may need compatible userspace CUDA runtime
versions; no automatic CPU/GPU downgrade is hidden. A Pi 5 without a
supported speech NPU should use smaller models.

DVB radio audio selection also prefers an ordinary soundtrack tagged for
the requested source language rather than an unrelated language or an
accessibility audio-description track. It falls back to the existing
program audio if no matching track exists.

### Exactly what is delayed (and what is not)

The native Kaffeine DVB callback **duplicates each selected-service TS packet
before the playback buffer**. One copy is immediately sent over the
private UNIX datagram socket to the Python caption worker. Whisper
processes live audio in overlapping six-second windows and Argos/NLLB
then translates the actual recognized words; neither waits for
Kaffeine's delayed video output. The OTHER copy enters Kaffeine's
delayed MPEG-TS FIFO, so audio and video play together after the delay.
It is not an isolated audio track delay.

For example, when a caption becomes ready approximately 7 seconds
after speech enters the RF receiver, 10 seconds of native delayed
playback can give 3 seconds of alignment headroom. If the CPU cannot
process six seconds of speech inside the available playback window,
the worker's queue will grow regardless of how long the display waits.
The queue is bounded; missing RF packets or nonblocking-sidecar drops
cannot be recovered by buffering the video.

**Requested vs actually applied:** the native playback FIFO keeps a
64 MiB maximum and computes a safer bitrate-limited delay with ~48 MiB
of target capacity and 16 MiB of headroom. The caption panel reads
Kaffeine's per-second effective MPEG-TS delay status from the user's
private runtime directory. It shows both requested and applied seconds,
plus the sampled incoming TS bitrate. When a high-bitrate channel,
timeshift or a recovery cooldown reduces the effective delay, the
panel warns rather than falsely presenting the requested time as
what the viewer is actually watching. The number describes the native
FIFO, not VLC's extra decoder/video-output latency. Auto-sync still
requires live processing measurements; it does not guarantee exact
per-word lip sync.

### Broadcaster Teletext language and subtitle-channel picker

The caption settings now discover actual **DVB Teletext subtitle descriptors**
from the currently copied service's PAT/PMT tables. Choose the
real language, PID and page in **Broadcast subtitle channel**, then
press **Apply**. This follows Kaffeine's own subtitle menu behavior
without inventing nonexistent language channels. It also prevents
the old failure where both German and French captions were mixed from
the same Teletext stream. The chosen page is fed directly to FFmpeg
and the signalled source language is used for translation; manual
page entry and pure Whisper transcription remain separate modes.

Whisper's published multilingual tokenizer supplies **100 source-language
codes**; the subtitle panel provides four one-click presets and an editable
source field for any supported language (for example `es`, `pl`, `ja`,
`ar`). Translator availability is independent: **Additional translation
languages** accepts ISO codes (for example `es,pl`) and full NLLB script
codes (for example `zho_Hant`). The subtitle panel handles up to three
simultaneous translation targets to avoid uncontrolled latency.

Model Market now exposes all official Argos pairs, not only DE/EN/TR.
NLLB checks the installed model tokenizer's actual language set before
inference. Selecting a valid language does **not** automatically download
a translator model or imply that a matching pack is installed. Original
Teletext remains readable even if Whisper or translation is unavailable.
If translation cannot be produced, **Translations only** displays the
source-language words with an explicit original/unavailable label
rather than blank captions or fake text. When a selected DVB audio PID
disappears, Whisper switches only to a broadcaster-labelled soundtrack
in the same language. Otherwise the status lists available alternate
audio languages and prompts selection instead of silently guessing.
Libre DVB Teletext formatting escape `\\h` is normalized to whitespace.

### Choose a *real* TV audio channel for Whisper

In **TIHULU AI → Live Teletext / Whisper subtitles**, the new **Whisper
source audio channel** picker lists verified audio elementary-stream PIDs
signalled by the currently tuned DVB service's PMT. The first choice leaves
the normal language-aware, non-audio-description preference in place.
Selecting a specific PID means Whisper reads **only** that program audio;
it does not change Kaffeine's own TV soundtrack, retune the receiver,
or open a second tuner. If the selected track disappears, the sidecar
reports an error rather than transcribing a different language silently.

The **Broadcast subtitle channel** picker is independent: select an
actual Teletext language/page/PID for broadcast captions, or use
**Whisper live transcription** for a chosen soundtrack. In **Teletext →
Whisper fallback** mode the subtitle/translation source language follows
the broadcaster Teletext page when text is present; when Whisper is needed,
it follows the selected audio language. Other languages require matching
Whisper and translator support and real installed Argos/NLLB models.
Unknown PMT language codes are not guessed as German.

Native C++ playback buffering and subtitle cue scheduling now take the
**effective** playback delay reported by Kaffeine when its 64-MiB
memory cap reduces the user's requested delay. If no fresh matching
status exists, the UI labels the lateness estimate as unconfirmed instead
of claiming exact synchronization.

## Synchronized live subtitles, embedded on-video OSD and Apply / Reset

In Kaffeine choose **TIHULU AI → Live Teletext / Whisper subtitles**.
The companion remains on top for caption diagnostics, but the subtitles
are now **also drawn natively inside Kaffeine's actual video widget**
without replacing libVLC or Kaffeine's existing EPG/Teletext OSD.

- Source modes: broadcaster-marked Teletext subtitles first with Whisper
  fallback, Teletext-only, Whisper-only, and explicit manual Teletext page.
- Languages: 100 Whisper speech codes plus user-entered Argos/NLLB targets.
  Both spoken words and translation can be shown together on the video.
- Video overlay: toggle on/off, original/translated line switches, position
  top/bottom, font size and black background opacity.
- **Apply** commits all pending control changes atomically and drops
  stale cues from a previous source/language. **Reset** restores controls,
  then **Apply** makes them active.
- **Caption offset:** -10 to +10 seconds. Positive makes text appear
  later; negative requests earlier text, but recognition cannot predict
  speech before a segment has finished decoding.
- **TV playback buffer:** 0–20 seconds. The native Kaffeine MPEG-TS FIFO
  keeps **audio and video together** and optionally delays both behind
  the immediate RF/Whisper capture. This enables more realistic alignment
  without shifting audio relative to the picture. The delay queue is
  bounded to 64 MiB. Kaffeine timeshift is already a separate playback
  mode and is not double-buffered.

Whisper operates on approximately **6-second overlapping audio segments** (plus
inference/translation time); it is not truly simultaneous word-by-word
ASR. A 3–6 second broadcast delay may help where machine processing
is fast enough. Use the live **ASR+translate latency** and
**Caption lateness** readouts to choose a buffer. Default playback
buffer and caption offset are both **0** to preserve live TV and
minimize Pi 5 RAM use.

Subtitles are transferred only via a private 0600 file under the
current user's XDG_RUNTIME_DIR. Untrusted remote clients cannot
write captions. They expire automatically, and all temporary OSD and
buffer settings are removed when the caption controller closes.

### Real translation model detection

The offline Argos translator can live in TIHULU's isolated AI runtime
virtual environment even when the KDE/Qt5 caption process uses system
Python. Caption processing now explicitly invokes that private runtime
with bounded JSON input. It does not fetch translation models at
inference time. Missing German/English/Turkish packages are reported
with an actionable Model Market prompt rather than a generic label.

### Pop!_OS error-log corrections

Previous logs had:
- **QObject::connect: No such slot DvbTab::showFullScanDialog():** Full
  Antenna Scan now connects through Qt's compile-time-checked function
  pointer, not an unchecked string-based slot name. The actual C++
  source is compiled in CI.
- **software-no-audio + Using NVIDIA VDPAU:** the software profile now
  removes conflicting saved libVLC `--avcodec-hw` flags and forces
  `--avcodec-hw=none` both at instance and media level. The fallback
  VLC initialization also preserves software decoding and the
  no-audio diagnostic.
- **kf.i18n: Using an empty domain:** Kaffeine's static EPG genre
  translations are now initialized on first use, after the KDE
  translation domain is configured, not during global initialization.
- **QCommandLineParser: already having an option named h/help-all/v:**
  Qt help and version options are registered once by KAboutData.
- **KServiceTypeTrader: ThumbCreator not found:** missing optional
  KDE thumbnail service; not a DVB/decoder error and no privileged
  system packages are changed to mask it.
- **libEGL / VA-API / VDPAU:** the software decoder profile avoids
  hardware video decode, but this does not fix every graphics output
  driver or RF continuity error. Test on the actual Pop!_OS host.

To verify after updating and fully quitting older Kaffeine windows:

~~~bash
~/.local/bin/tihulu-kaffeine --software-video 2>&1 | tee ~/tihulu-tv-video-test.log
grep -E 'TIHULU playback|Using NVIDIA VDPAU|picture allocation failed|avcodec_send_packet' ~/tihulu-tv-video-test.log
~~~

The log should report an enforced software profile; **any remaining**
NVIDIA VDPAU decoder line or frozen picture needs more diagnosis rather
than a false success claim.

### Automatic synchronization (opt-in)

The companion now includes **Automatic sync · detect caption lag & adjust safe
TV buffer** (OFF by default). Select it and press **Apply**. It collects at
least **three real live Whisper/Argos results** and compares the audio
capture start against the timestamp at which the translated caption became
available. The display shows:

- **Estimated caption availability lag**, measured from actual processing.
- **Safe TV playback buffer range** and a recommended delay in seconds.
- Sample count and whether the safe hardware/memory limit was reached.

With automatic sync OFF, the recommendation is informational; **manual
caption offset and playback delay are not changed**. With it ON, the first
valid recommendation is applied to Kaffeine's existing audio+video MPEG-TS
buffer; later changes have a 30-second cooldown, 0.75-second hysteresis and
at most 0.5-second adjustment to avoid rapid playback stalls.

Automatic TV delay is limited to **15 seconds** on normal Linux systems,
**6 seconds** on Raspberry Pi 5 and a stricter value if the current
transport-stream bitrate would consume more than roughly **48 MiB**.
Manual playback delay supports 0–20 seconds; the 64 MiB native queue still limits what the hardware can safely buffer. When the
observed lag is above the safe maximum, the UI warns that speech/text
can remain late rather than pushing the buffer past its memory budget.

**Accuracy limitation:** this is an *availability-lag estimator*, not
speaker diarization, word-level Whisper timestamps or an independent
audio/video lip-sync meter. It cannot reconstruct the exact position of
each word inside a six-second audio chunk (with a short overlap). Manual **Caption offset**
remains available for visual fine-tuning; automatic mode does not
fabricate a precise text offset. Broadcaster Teletext is not used to
train Whisper latency and changing the DVB service clears measurements.

## Live video freezes or stalls — Pop!_OS / COSMIC / NVIDIA

The tuner and Kaffeine must not be replaced with another scanner. There
are **two independent causes** of a frozen live picture:

- **RF loss:** the previous Hauppauge WinTV-soloHD tests showed real
  uncorrected blocks (UCB) and MPEG-TS continuity errors. Software
  cannot reconstruct missing DVB packets. Reposition the indoor aerial
  and compare a free-to-air channel at 538/586 MHz; keep other DVB apps
  closed during TV playback.
- **HEVC/AAC-LATM/libVLC decoder:** NVIDIA + Wayland/COSMIC previously
  produced VA-API/VDPAU initialization failures. libVLC may also emit
  AAC-LATM unsupported subframe warnings. A good signal is not proof that
  the decoder is healthy.

The Kaffeine-native app now has three per-session playback profiles,
without changing system Kaffeine, AI settings, channel lists or the tuner:

- Normal launcher: `~/.local/bin/tihulu-kaffeine`. On NVIDIA **and**
  Wayland it selects a software decoder profile by default. On Pi 5 and
  other systems it leaves Kaffeine's original libVLC selection alone.
- `~/.local/bin/tihulu-kaffeine --software-video`: explicitly disables
  libVLC accelerated decoding and applies 1500ms file FIFO caching.
  Requires more CPU; compare a known free-to-air HEVC channel.
- `~/.local/bin/tihulu-kaffeine --auto-video`: return to Kaffeine's
  original hardware-decoding preferences for performance comparison.
- `~/.local/bin/tihulu-kaffeine --diagnose-no-audio`: same software video
  path, temporarily disable audio, to isolate the previous AAC-LATM
  issue. This is *diagnostic only*, not a replacement for audio support.

Kaffeine **Settings → Configure Kaffeine → libVLC arguments** continues
to take precedence if you explicitly set hardware decoding or caching
flags there. The profiles apply at process startup, so quit Kaffeine
fully before switching. Logging can be captured with:

~~~bash
~/.local/bin/tihulu-kaffeine --software-video 2>&1 | tee ~/tihulu-tv-playback.log
~~~

Do **not** assume the new profile fixes antenna signal loss. Look for
VLC decoder failures and compare with DVB signal lock/UCB changes. When
TV plays normally but the caption panel stutters, close the AI consumer
temporarily to distinguish Whisper CPU saturation from playback.

## Diagnosing missing words vs GPU inference

This version has independent end-to-end timing and transport telemetry.

- **Stage timings:** Teletext extraction, Whisper ASR, translation and
  total duration are reported separately. A 6-second Whisper chunk
  can take *longer than 6 seconds* when the CPU is too slow.
- **Backlog:** remaining queued capture clips and MiB are shown. Workers
  process clips in chronological order with a one-second overlapping
  tail; a full queue reports missed seconds rather than silently claiming
  there is no loss.
- **TS continuity gaps:** the sidecar now measures MPEG-TS discontinuities
  and requests a larger private UNIX socket receive buffer. Gaps can
  originate from antenna reception **or from Kaffeine's nonblocking
  sidecar packet sends**. This metric alone cannot blame the antenna.
- **Faster-Whisper on CUDA:** when the optional CUDA Faster-Whisper
  model/runtime is actually present, its large model is cached in GPU
  memory for subsequent short clips instead of loading weights anew
  for every clip. The whisper.cpp CLI path still starts an executable
  for every chunk and can have substantial loading overhead.

Use the read-only health command **without acquiring the DVB frontend**:

~~~bash
tihulu-tv-center ai-check
~~~

This prints the RTX/GPU/NPU discovery, selected backend, installed model,
CUDA-runtime readiness and translator backend separately. A detected
RTX 5080 is *not* proof that Whisper inference runs on the GPU.

For the settings UI, use `tihulu-tv-center ai-market`. Install a
multilingual GGML model and a compatible CUDA whisper.cpp runtime, choose
**Auto** or **GPU** in the market, save the settings, and reopen Kaffeine's
captions controller. If the output reports CPU, adjust the backend or
model rather than increasing TV playback delay indefinitely.

**Sync:** Automatic sync is optional (default OFF). Three real ASR
samples are required before it recommends delaying both video and audio.
The safe recommendation respects the current MPEG-TS bitrate and the
native 64 MiB bounded FIFO. Speech cannot be aligned earlier than
Whisper/translation finishes, and longer buffering is not a cure for
missing or corrupt incoming TS packets.

## Known limitations and cautions

Kaffeine itself uses **libVLC**. Existing VA-API/VDPAU, AAC-LATM, HEVC
and signal/UCB problems will not disappear simply because the DVB
foundation is Kaffeine. The prior tests found severe RF continuity and
uncorrected-block problems; these must be tested again on hardware.
Do not run two DVB applications against the same frontend.

Remote TCP port 8769 is **OFF by default**. Pairing uses unencrypted
HTTP and must be enabled only on trusted Wi-Fi; never port-forward.
For external access use owner-authenticated HTTPS/Tailscale Serve.

**This version supports Linux DVB hosts**, including a Raspberry Pi 5
only if its hardware and codecs work with the distro. Windows/macOS
native DVB/BDA backends are not implemented. iPhone/Android/browser
access to the Linux receiver is cross-platform. Actual WinTV-soloHD
and Raspberry Pi 5 acceptance tests remain pending.

Kaffeine now includes the **experimental native on-video subtitle
OSD**. Closing the separate settings panel does not stop the caption
worker; use **Stop subtitles & Exit** to end it. This is source-build
tested, but not yet accepted on the user's live WinTV-soloHD hardware.
Verify current KiKA/ARTE Teletext, German speech, Turkish/English
translation, switching channels, and iPhone HLS before a stable release.

## RTX 5080 GPU, NPU, live buffer and conversational captions

The **RTX 5080 is a CUDA GPU, not a dedicated Hailo/Intel NPU**. On NVIDIA
Blackwell, use **AI Model Market → Speech models · GPU/NPU → Install CUDA
Faster-Whisper Large-v3 Turbo · no nvcc needed**. This isolated install
requires a working NVIDIA driver, but *not* the CUDA source-build compiler.
It installs pinned CTranslate2 >=4.6.3, CUDA 12.8+ cuBLAS and cuDNN 9
runtime wheels with a SHA-256-verified model, then runs a synthetic CUDA
inference self-test. The **Advanced compile whisper.cpp** button is optional
and *does* require the CUDA Toolkit >=12.8 (nvcc); a missing compiler must
not be mistaken for a missing GPU. The user's existing CPU GGML Tiny model
is a valid fallback but is **not** the GPU Turbo model.

After installing and saving **Auto** or **GPU** backend:

```sh
tihulu-tv-center ai-check
tihulu-tv-center ai-check --deep
```

The first reports runtime status without model inference or RF. `--deep`
explicitly loads the installed CUDA model and executes GPU inference on
synthetic audio, without tuning any real receiver, downloads, or TV playback.
Actual live performance still needs a tuned receiver and measured RF/audio.

**Broadcast data path:** Kaffeine copies filtered, real, selected-channel
MPEG-TS datagrams to the separate Whisper/Teletext sidecar *before*
buffering its own MPEG-TS-to-libVLC playback queue. In the interval while
both TV audio and video are delayed, the AI sidecar receives and transcribes
the original live stream and performs optional translation. A word-time
scheduler reads Faster-Whisper CUDA's `word_timestamps` and shows small
spoken phrases as their **delayed playback time** approaches. Translated
word pacing is approximate: no translator claims actual target-language
word alignment. If word timestamps are unavailable the prior chunk-level
caption path is preserved. If an ASR process is still slower than the
buffer, captions may appear late; no imaginary live transcript is emitted.
The native 64 MiB TS memory limit can cap or temporarily cancel the
requested buffer. See **Native TV delay: actual / requested** in UI.

**Speaker separation** is optionally enabled in the live captions settings
and **OFF by default**. Model Market has a separate **Speaker separation**
tab for pyannote Community-1, an owner-approved gated CC-BY-4.0 model.
Before installation accept the official Hugging Face model terms and enter
a read token *only in the installer prompt*. This installs into isolated
user-owned storage (or the selected external model drive), and speaker
inference uses local audio offline; no remote voice API. The UI renders
`[Speaker 1 · clip]`, `[Speaker 2 · clip]` only where the offline model
actually produced speaker turns and Whisper supplied word timings. These
IDs are **temporary per clip**: do not interpret them as a reliably
persistent person across scenes, and do not automatically infer whether
a voice belongs to a woman, man, child, or a particular person.
**Token-free automatic voice labels** are the preferred option. The optional
Resemblyzer 0.1.4 package includes public pretrained Apache-2.0 weights,
requires **no Hugging Face token**, and runs in a dedicated offline CPU
environment independent of the RTX 5080's CUDA Whisper and the NLLB
translator. Under **Model Market → Speaker separation** the public model
can be installed, verified, and removed without a gated account. When
available, Live Captions has **Auto-label distinct voices** checked by
default and displays **Speaker 1, Speaker 2, ...** based on estimated
embedding clusters. Users do **not** need to type speaker names. The
public model works best on English and may be unreliable on some other
languages, short dialogue, music or overlapping voices. It does not
identify a person's gender, age or civil identity. The more advanced
gated pyannote Community-1 option is collapsed under an optional
advanced section and still requires owner-authorized access.
Diarization adds processing time; if the model is missing or fails,
**original and translated captions continue without speaker labels**.

**In the same AI Model Market window:** the Speech tab lists installed
GGML models and offers explicit online discovery of verified Medium and
Large-v3 Turbo models, with Download / Use Selected. The translation tab
lists installed and official-available Argos language pairs and has
install/remove actions and the optional NLLB-200 multilingual model. The
Speaker tab controls the optional voice-separation runtime. None of these
downloads happen automatically on app launch.


## Caption window and subtitle color controls (2026-11-08)

AI Model Market now has independent vertically scrolling Speech, Translation,
and Speaker tabs. Long labels wrap, the dark palette stays consistent, and
the **Save settings / Close** footer stays visible even on smaller windows.
Live Captions also scrolls its settings independently while preserving
**Apply**, **Hide settings / keep subtitles**, **Stop subtitles** and concise
live caption status.

The on-video overlay now reads **both** text and background colors from
validated private user-owned OSD IPC JSON (`text_color` /
`background_color`, each #RRGGBB). Independent text and backing opacity
controls span 0–100%. A color dialog, live visual preview and presets
provide white-on-black, yellow, cyan/navy, transparent backing and
fully transparent styles. These settings are actually rendered in the
patched native Kaffeine/Qt OSD, not just in the control dialog.

The language checkboxes represent **requested output languages**, not an
implicit single target. EN and TR remain checked even if a detected
broadcast subtitle channel carries English as its **original** language.
The transcript is shown as EN (no redundant translation call) alongside
the genuinely translated TR text when a compatible local language pack
is installed. Original + translations avoids duplicate copies of
English; Translations only includes requested English as a source-language
output when appropriate. A single unambiguous broadcaster-signalled
Teletext or audio track is selected automatically, including its
*actual language*, rather than incorrectly labeling broadcaster
English as German. Unavailable translations are reported separately
and cannot erase the original transcript.


## Native Radio (DAB+) + local media AI (2026-11-08)

The left navigation now includes **Radio (DAB+)** in the SAME native
Kaffeine window alongside Playback, Playlist and Television. Radio uses
the shared libVLC `MediaWidget` and bottom playback toolbar; selecting a
station does **not** open another player or browser. It does not open any
receiver on startup.

**welle.io backend** is an optional pinned GPL-2+ welle-cli build
(`AlbrechtL/welle.io`, commit
`512558d1f8ac4c524d3c63e97510ea36c1bd7a70`). It requires its own
DAB-capable RTL-SDR/SoapySDR device. A DVB-T2 frontend is NOT
automatically DAB-compatible. To install it:

```sh
bash "$HOME/.local/share/tihulu-kaffeine/install_welle.sh"
# Or opt in to both source builds during a new install:
# bash install.sh --with-dab
```

The backend installer changes welle.io's unprotected default HTTP bind
from `INADDR_ANY` to `127.0.0.1` **before building**. Only the
locally patched, marked binary is accepted by the native Radio tab.
Never use an externally network-exposed welle-cli `-w` server as the
Kaffeine radio backend. The optional builder depends on installed
Debian/Pop!_OS APT development libraries, internet access for the
first build, and sufficient disk space. It does not touch NVIDIA drivers,
Whisper models or DVB-T2 tuner configuration.

**Radio features included**: real Band III ensemble scanning on
owner request, persistent station cache, per-service selection and
playback, explicit automatic/RTL-SDR/SoapySDR driver choice, owner-initiated
local MP3 recording without overwriting existing files, broadcaster DLS
text, MOT slideshow, live ensemble and SNR/FIC/audio error indicators,
TII transmitter-count status, receiver information and on-demand spectrum,
null spectrum, constellation and impulse-response visualizations. The
interface uses the actual welle `/mux.json`, `/channel`,
`/mp3/<SID>`, `/slide/<SID>` and RF diagnostic endpoints on the
private 127.0.0.1 server. It **does not yet replicate every original
welle.io GUI menu**, e.g. detailed TII transmitter diagrams, advanced
FFT placement/coarse-correction controls or historical RF recording;
those are not claimed as complete. Only one
application should own a particular RTL-SDR at once.

**Offline radio AI** is an optional **Start offline live captions**
button in the Radio tab. It extracts PCM from the same local welle
station stream, uses the already installed GPU/CPU Whisper model and
selected offline Argos/NLLB translator, and displays the original plus
checked EN/TR translations without uploading audio. **Include music
vocals** disables speech VAD on the CUDA model; it may be less accurate
on instrumental or heavily mixed music. Actual live radio word display
can lag playback: TV's native MPEG-TS playback buffer is **TV-specific**
and is not falsely reported as applied to welle MP3. The radio worker
is stopped and its private runtime files removed on Stop / application
close.

**Local video and audio AI**: TIHULU AI → **Generate AI captions /
lyrics for local Video or Audio** opens a file selection dialogue.
The installed GPU Whisper and offline translator produce
`.srt` next to the original media file; choose the subtitle file
from Kaffeine's existing subtitle menu. The original media file is
untouched. Supported examples include MP4, MKV, TS, MP3, WAV, FLAC,
M4A and OGG. The offline CLI alternative is:

```sh
tihulu-tv-center media-captions --input "$HOME/Videos/example.mp4" --source de --targets en,tr
tihulu-tv-center media-captions --input "$HOME/Music/song.flac" --source en --targets tr --music
```

**Timed lyrics**: A local same-basename `.lrc` is preferred. For
a radio song announced as `Artist - Track` in DLS, the user may
click **Find timed lyrics** and explicitly authorize a metadata-only
HTTPS request to LRCLIB; no song audio is uploaded and no API key is
required. Radio start time is estimated from the DLS change and a
manual time-offset slider adjusts the approximate alignment. Only
verified synchronized LRC cues are displayed, never made-up lyric
timing. Existing lyrics and other copyrighted text are not republished
by this README. See the provider's terms before redistributing.

**Optional TV music**: In Live Captions, check **Include singing /
music vocals in Whisper**. It uses the same early pre-playback TS tap
and the existing TV buffer. This is real song-vocal transcription, not
audio fingerprinting or guaranteed time-coded third-party lyrics.

**Caption appearance**: `Background opacity` controls the backing
rectangle (0% = completely transparent), while `Text opacity`
controls only the characters. White text at 100% with background
opacity 0% is fully readable text with no black bar; either color can
also be changed independently.


## Natural live subtitle timing, MPEG-TS integrity and true no-background (2026-11-08)

Natural dialogue captions now use **ordered, non-overlapping groups** of
actual ASR words with at least **1.75 seconds of reading time** (rather
than instantly jumping to the last due word). Groups prefer pauses and
complete clauses. Target-language translation text is divided into
**disjoint** rough groups: words no longer repeat across consecutive
windows. Exact translated-word timestamps are not available, so they
are not represented as sample-accurate. When a transcription finishes
too late to follow its word timing, the screen displays one coherent
phrase instead of rapidly catching up with obsolete partial words.
ASR overlap is deduplicated against the **whole prior raw recognition**,
not the already trimmed text of the previous callback.

Whisper continues reading a copy of the **undelayed** DVB TS stream.
The native player still delays audio and video together. The caption
scheduler adds a conservative 550 ms anti-early display margin and
only schedules against the **confirmed, fully primed** Kaffeine TS
buffer, never an unacknowledged new requested delay. The native player
publishes a separate **buffer ready** flag and measured oldest queued
MPEG-TS age. If 15s is requested but only 2s is collected, the caption
controller holds output until real delayed video data is ready instead
of treating the requested 15s setting as already active. Old native
3-field status files are treated as **unverified** for nonzero delays;
rebuilding pinned Kaffeine is required for safe auto-sync. Automatic timing estimates the
full Whisper+translation availability with a rolling window, protects
the 48 MiB safe portion of the native TS budget, adjusts slowly under
the original 30-second cooldown, and independently checks the player
delay every 25 seconds. If the native queue changes actual buffering,
previous cues are cleared rather than displayed ahead of the picture.
The player-reported queue delay is **not** the exact libVLC A/V
presentation clock, so lip-sync precision is not falsely asserted.

The caption-only TS copy has per-packet header, TEI, adaptation and
continuity validation. Exact duplicate payload packets are filtered.
If an audio PID has missing continuity counters, word-perfect cue
alignment is disabled; severely compromised audio segments are
discarded instead of transcribed into possible hallucinations. This
never modifies live TV output or opens the tuner again. The 1 MiB
audio-overlap cap is included in the measured time origin, rather than
incorrectly subtracting a fixed one second at every bitrate.

**No background** means **Background opacity: 0%** and **Text opacity:
100%**. A caption QColor brush with alpha=0 was insufficient: the Qt
child QWidget backing could still paint black over libVLC. The native
caption OSD is now a transparent child widget; it explicitly clears
the paint surface and draws **no backing geometry at all** when the
background opacity is zero. Both color and transparency controls
remain independent; selecting 0% for BOTH actually hides all captions
and is labelled as such. Appearance is saved in local Qt settings and
restored when the caption service is reopened. Qt overlays may still
behave differently depending on the user's window compositor and
video output; native broadcast-supplied DVB subtitles or video
letterboxing are separate layers and are not controlled by this
optional AI caption appearance setting.


## Standalone TIHULU Media Center — TV, all-block DAB+, media and AI (2026-11-08)

This experimental branch now installs a **separate application** named
**TIHULU Media Center**, with its own orbital play icon, application/DBus
identity, local config, desktop launcher and channel/SQLite data directory.
The original KDE Kaffeine remains installed and intact. On the first
install, supported existing Kaffeine DVB channel settings are
**copied** (not moved), when the TIHULU destination does not already
exist. Upstream Kaffeine GPL attribution remains in the About dialog
and source tree. The Home/Start screen now offers **DAB+ Radio** and
**Open Media + Offline AI** alongside native TV, file, CD and DVD actions.

The Radio tab **does not reparent** the shared Kaffeine MediaWidget.
This is crucial: the former implementation moved libVLC's video surface
inside the radio view, breaking Playback or leaving duplicated controls
after tab changes. Radio playback still uses Kaffeine's shared libVLC
audio engine, but its central artist/AI caption canvas is independent.
Playback, Playlist and Television keep their own native video activation.

### DAB+ integrated library and RF tools

- All verified stations are shown by default **across all saved DAB
  blocks** (not just the current frequency), with a persistent local
  catalogue, search, filter by block, sortable wide station names, and
  **★ favorites** saved separately from station data.
- Double-click a station name to retune its actual block and play.
  Clicking the star toggles a favorite without tuning; the cache remains
  available when the tuner is disconnected. A USB receiver must actually
  support DAB+; an ordinary DVB-T2 tuner is not automatically compatible.
- **Show welle.io RF widgets** exposes native spectrum, on-demand
  constellation, CIR, null spectrum, optional **live waterfall / live
  spectrum** updates, FFT/coarse correction and the full local TII/receiver
  diagnostic JSON. The RF panel and live polling are OFF by default.
- DAB **MOT/SLS artwork** has Prev/Next navigation across a bounded
  local slideshow history, as well as original broadcaster DLS text.
  Signal status reports measured SNR and FIC/codec error counters; RF
  quality labels are approximate, never invented percentages.
- The lyrics search remains **explicit, keyless, metadata-only**.
  Separate **Stop lyrics** terminates the lookup and stops synced text
  display. DLS-change timestamps are shifted by the requested radio
  audio cache and may still need the manual offset; neither DLS nor
  LRCLIB supplies an exact libVLC sound-card presentation timestamp.

### Three different, honest buffering mechanisms

1. **Television**: a pre-playback MPEG-TS AI tap and Kaffeine native
   audio+video delay. The controller follows confirmed, primed native
   buffer status and audits it periodically. This is not libVLC PTS.
2. **DAB+ Radio**: a separate, configurable **0–20-second libVLC
   network cache**. Live 6-second radio speech chunks are processed
   off the undelayed local stream; captions are held according to the
   estimated radio cache and measured Whisper+translation completion.
   Opt-in radio **Auto adjust buffer** takes a rolling sample, and
   conservatively raises the cache at most once per minute if clearly
   too short. **Applying a new value reopens the stream** and can cause
   a brief interruption. It is NOT exact lip-sync or audio-fingerprint
   alignment; device/codec/ALSA output latency is unmeasured.
3. **Local video/audio files**: a separate **0–20-second file read-ahead**
   (libVLC `file-caching`) and an independent, checked-by-default
   **Preprocess before playback** control. When you press Generate, the
   file can stop while GPU Whisper and installed translators produce a
   real timestamped SRT, then restart from the beginning with those
   captions loaded in the **same Playback tab**. For long videos this
   may take much longer than 20 seconds; its benefit is correct file
   timestamps without trying to catch up live. File read-ahead is NOT
   itself the ASR compute latency budget.

### Automatic language detection and cross translation

The radio and embedded file AI controls now default to **Auto detect
(GPU Whisper)**. The installed managed Faster-Whisper returns the actual
detected source language, so a broadcast heard in **English** can
produce **German and Turkish translations** while retaining the
original English text only once. Target language availability depends
on offline packages in Model Market; no translation is invented when a
pair is not installed. Radio exposes DE, EN, TR and extra ISO/NLLB
target codes, with bounded resource limits. Native TV Whisper also
offers Auto detect; broadcaster Teletext uses its signalled source
language without guessing. Other CPU/NPU speech engines are not
claimed to support automatic detection unless they actually do.
Song transcription remains an opt-in best-effort speech model use,
not a guaranteed match to copyrighted lyrics.

To build the standalone player AND the optional loopback-only DAB
receiver from this branch:

```sh
curl -fsSL https://raw.githubusercontent.com/Tihulu/TIHULU-TEXT-CENTER/architecture/kaffeine-core-tv-2026-11-07/kaffeine_next/install.sh | bash -s -- --with-dab
tihulu-media-center --software-video
```

GitHub CI validates source patch application, Qt5 compilation and
Python tests. It cannot verify physical receiver scans, live
latency/quality, hardware audio output or desktop compositor behavior.
Keep the PR draft pending physical verification.

