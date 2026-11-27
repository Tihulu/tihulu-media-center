# TIHULU AI ready modes and remote GPU

## Native Model Market workflow

Open **TIHULU AI → Model Market → Ready modes · Install all**.

1. Choose a profile to see its exact model/runtime components, estimated disk,
   restrictions and hardware suitability.
2. **Check installed** inspects locally provisioned components. A checkpoint
   file alone is not a live performance benchmark.
3. **Install all** asks permission and installs only missing components,
   sequentially. The operation needs internet for downloads/compiles, but
   does not select a mode, access a tuner, or run on application startup.
   Rerunning safely skips already installed components. Partial successes
   remain installed; errors must not be hidden.
4. **Select mode** checks hardware and every required local model/runtime,
   then activates the backend, CPU fallback model and translator in persistent
   owner-owned settings. Live captions must be restarted for a clean session.

| Preset | Speech | Translator | Additional components | Hardware |
|---|---|---|---|---|
| Pi 5 8GB | whisper.cpp Tiny CPU (3 of 4 cores) | Argos DE/EN/TR | CPU build, TV/Argos reserved headroom | Pi 5, >=6GB host RAM |
| Pi 5 8GB + AI HAT+ 2 | Hailo-10H Whisper Base **NPU** when HEF/NPY ready; Tiny CPU fallback | Argos DE/EN/TR **CPU** | HailoRT + Hailo Apps + official offline assets installed separately | Pi 5 + verified HAILO10H |
| Normal PC | whisper.cpp Small CPU | Argos DE/EN/TR | CPU build | >=7.5GB RAM |
| Performance | Faster-Whisper Large-v3 Turbo CUDA | Argos DE/EN/TR | Resemblyzer + Small CPU fallback | NVIDIA >=12GB VRAM; >=16GB RAM |
| Experimental | CUDA Turbo | MADLAD-400 3B CUDA | Resemblyzer, NLLB-200 600M, Argos, CPU fallback | NVIDIA >=24GB VRAM; >=32GB RAM |

NLLB uses **CC-BY-NC-4.0 (non-commercial)**. MADLAD uses Apache-2.0.
Experimental's simultaneous model execution may still exceed a VRAM/latency
budget despite meeting these minimum checks; no real-time guarantee.

### Raspberry Pi 5 8 GB — vanilla and CPU mode

The standard AI installer provisions Whisper Tiny multilingual and Argos
DE↔EN↔TR packs. The Pi 5's 4-core CPU now runs the whisper.cpp CLI with
**3 threads** by default (1–4 can be chosen under Ready modes). This
reserves CPU scheduling headroom for DVB/HEVC decoding, Argos, Qt, and
receiver processing. It does not guarantee real-time recognition under
thermal throttling or low signal-quality TS.

The 3-thread budget is also applied automatically to **vanilla** first-run
Pi 5 installations with no named preset selected. It is never applied to
other computer architectures by default. Pi 5 uses CPU Tiny, not CUDA
Large-v3 Turbo; start with a single translation target, and prefer
broadcast Teletext captions when available.

### Raspberry Pi 5 8 GB + AI HAT+ 2 — actual Hailo-10H Whisper

The Hailo-10H has separate **8 GB of NPU memory**, which is **not** 8GB of
extra host RAM. Its official Hailo Apps Speech Recognition workflow
supports precompiled **Whisper Base** or Tiny models; they are separate
**HEF** and **NPY** decoder assets, NOT interchangeable with CPU GGML files.
Argos remains CPU-based.

1. On **64-bit Raspberry Pi OS Trixie**, follow the Raspberry Pi [AI software
   instructions](https://www.raspberrypi.com/documentation/computers/ai.html).
   For AI HAT+ 2, install the driver/runtime with
   `sudo apt install dkms hailo-h10-all`, reboot, then run
   `hailortcli fw-control identify`. Device Architecture must be HAILO10H.
   Do not install the mutually exclusive `hailo-all` package for HAT+ 2.
2. Install the current official [Hailo Apps](https://github.com/hailo-ai/hailo-apps)
   using its documented GenAI/speech-recognition environment, and explicitly
   download its matching Hailo-10H Whisper **Base** encoder HEF, decoder HEF
   and decoder NPY assets using the vendor's resource manager. Review the
   vendor's downloads before authorizing them. TIHULU itself never runs the
   vendor's auto-download resolver when tuning TV or opening the Model Market.
3. In **Model Market → Ready modes → Pi 5 + AI HAT+ 2**, use the Hailo
   fields to choose the **local** encoder/decoder HEF files and the NPY
   folder. Click **Save model paths → Check Hailo-10H**.
   The check verifies device architecture, Python modules and local assets
   *without loading the model*.
4. Click **Test NPU · local silence** if desired to actually initialize the
   vendor WhisperPipeline and process one second of synthetic silence.
   This is not proof of quality, multilingual detection, word timestamps
   or a 6-second real-time target. It never accesses a tuner or a microphone.
5. **Install all** installs the known CPU Tiny + Argos fallback. It does not
   install HailoRT/HEF assets, touch the PCIe device or auto-select NPU.
   **Select mode** activates NPU only if HAILO10H and local model/runtime
   requirements are recognized; otherwise CPU Tiny remains selected.

A Hailo output currently supplies **plain transcribed phrases without
verified word-level source timestamps**. Exact speaker-turn/word alignment
and lip-sync are not claimed. Spoken language **Auto detect** uses the Tiny
CPU fallback until NPU auto language detection is verified. A failure of the
Hailo inference path is explicitly reported and reverts to CPU only when
the **Hailo CPU fallback** option remains checked.

For low RAM or unstable power/thermals, disable experimental background
models and test one subtitle language at a time. The NPU is on-demand; no
camera, audio capture, USB device or model initialization happens during
ordinary startup.

## Remote GPU option (off by default)

This is the **speech recognition** backend only. Translation and TV playback
remain local. Only bounded 32-kHz s16le speech PCM is uploaded when the user
explicitly selects and saves **Inference engine = remote** plus **Allow sending
spoken TV audio**. No service discovery, uploads, model downloads, or LAN
server startup occurs automatically.

1. On the **GPU computer**, install the native TIHULU TV Python code and its
   separately verified managed Faster-Whisper CUDA Turbo model. Provide an
   HTTPS certificate and private TLS key for the GPU host's real DNS name.
2. Generate a distinct random token securely on the GPU computer:

   ```bash
   python3 -c 'import secrets; from tv_center.remote_gpu import save_token; save_token(secrets.token_hex(32)); print("Private token generated")'
   ```

   Transfer that secret to the viewing computer **only over a secure
   channel**; do not paste it into public issues, repository files or logs.
3. Start the server **manually** on the GPU computer. By default it listens
   on loopback only; for use over a trusted network set the host bind address
   explicitly and restrict access with your firewall/VPN:

   ```bash
   python3 -m tv_center.remote_gpu_server \
     --host 127.0.0.1 --port 8443 \
     --cert /path/to/server.crt --key /path/to/server.key \
     --token-file "$HOME/.config/tihulu-tv-center/remote-gpu-token"
   ```

   For direct LAN access, use an explicitly approved network bind address,
   a valid certificate matching your GPU host name, and restricted
   firewall/VPN access. Self-signed certificates must be trusted by the
   **client OS**; TLS verification is intentionally not disabled.
4. On the **viewing computer**, open Ready modes → Remote GPU. Enter
   `https://your-gpu-host:8443`, save the matching private token, and use
   **Test TLS · no audio**. Enable transmission and local fallback as desired.
   Go to **Speech models → Inference engine = remote**, then **Save settings**.
   Restart live captions. Without these explicit steps, no audio is uploaded.

The server's `/health` response only confirms local installed files, NOT a
real GPU speed/accuracy result. Measure on real broadcasts before relying on
remote results. All HTTP redirects and environment proxies are rejected;
the client uses system TLS certificate verification and a private token.

## Faster startup / no surprise hardware access

The native TV window and Model Market now display before NVIDIA/CUDA and
Argos package inventory probes complete. Slow discovery runs on read-only
worker threads; status updates appear afterward. Native Kaffeine now starts
without tuning the last channel by default, to avoid RF activity before the
user explicitly selects TV. To restore old behavior for a particular launch:

```bash
TIHULU_AUTOPLAY_LAST_CHANNEL=1 tihulu-media-center
```

No benchmark of first-paint duration or complete live remote inference is
claimed until tested on actual user hardware.
