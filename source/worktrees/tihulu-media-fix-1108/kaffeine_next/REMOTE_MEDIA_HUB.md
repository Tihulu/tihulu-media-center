# TIHULU Media Center · paired remote media (preview)

> **Draft feature.** Native Kaffeine TV playback and DVB-T2 tuning are still
> host-local. **This build does not stream live native DVB-T2 television or
> DRM-protected/DVD discs** to browsers. Do not advertise universal mirroring.
> Use only media you are authorized to stream and distribute.

## Local desktop operation

1. Open TIHULU Media Center and choose **TIHULU AI → Start paired remote media hub...**.
2. Select an explicit folder of media to share; the server does not open arbitrary
   paths from web clients. No sharing occurs until you start it.
3. The app displays an 8-digit pairing PIN. Use the host machine browser at
   **http://127.0.0.1:8788**, enter that PIN and choose a file.
4. The hub encodes HLS on the *host* using FFmpeg (shared encode for multiple
   authorized clients). It does not install or run Whisper on client devices.
5. In the browser, **Also play on host computer** plays the same file via
   Kaffeine's legacy MPRIS1 D-Bus player where supported. Uncheck for remote only.
6. Native TV station switching (name or number), host volume/play/pause/stop,
   and playlist Next/Previous are forwarded to the already-running local Kaffeine
   process. Native tuner ownership never transfers to the browser.
7. **Stop remote media sharing** in the app menu or exit the app. Active HLS
   encoders exit and private temporary segments are removed.

## Headless / console

```sh
tihulu-tv-center remote-hub --media-root "$HOME/Videos"
```

You can optionally attach to a **currently running** native radio receiver,
without opening a second SDR device:

```sh
tihulu-tv-center remote-hub --media-root "$HOME/Videos" --native-pid 12345
```

Replace `12345` with the **actual native TIHULU PID**, never a guess. Its private
`$XDG_RUNTIME_DIR/tihulu-welle-<PID>.port` file is written by the native DAB tab
when the optional pinned welle backend is running. If no backend is up, DAB
is absent rather than fabricated. The remote hub follows locally produced
radio ASR/translation caption JSON only when the matching native AI worker exists.

## Phones/tablets or another computer

The local server deliberately binds `127.0.0.1` without encryption. Do **not**
open port 8788 to the public Internet or expose it with Tailscale Funnel.

For an authenticated private tailnet with HTTPS certificate support, run
on the host:

```sh
tailscale serve --bg 8788
tailscale serve status
```

Open the HTTPS URL shown by `tailscale serve status` on a second device that is
already authorized to access the same private tailnet. You must still
enter the **application's own** PIN; Tailscale access does not skip PIN pairing.
This is *Tailscale Serve*, not Funnel. Keep Tailscale ACLs appropriately
restricted. If you already use an HTTPS proxy on port 443, configure Serve
without clobbering your existing routes.

## Security / behavior

- Private 8-digit one-time-in-process PIN; max 5 failures in a rolling 10-minute
  window per remote address; sessions expire after 8 hours.
- HttpOnly, SameSite=Strict cookies plus CSRF token for write operations.
- Default loopback binding; no automatic public bind, RF uploads, secret API
  keys or automatic background service.
- Server-side FFmpeg process owns *one* HLS stream with on-demand encoding.
  Another client can watch the same stream; starting a different source replaces
  it for all clients. Independent simultaneous programmes require additional
  tuners and/or dedicated transcoder sessions (not implemented).
- Firefox and other browsers without native HLS playback may require a suitable
  HLS-capable browser/client; Safari generally supports native HLS.
- A requested radio buffer/Whisper processing delay is **not** proof of
  sample-accurate TV lip sync. Caption payload has only approximate source
  timestamps, not guaranteed audio-output clock alignment.
- Never infer a silent/offline service is playing because it was saved in
  an old DAB channel catalog. Only services present in the live mux are offered.

## Still missing

- Live native DVB-T2 Transport Stream → safe independent HLS copy without
  disrupting libVLC, plus live TV subtitles as synchronized HLS/WebVTT tracks
- Full native UI mirroring into browser with equal capabilities
- Native DVD screen/video mirroring and protected-content handling
- Independent multi-channel sessions; per-client local/remote source routing
- Verified audio/video DRM/network/codec/latency tests on real USB tuners,
  TV hardware and all requested client browsers

Keep PR #38 **draft** until real device end-to-end testing confirms stability.
