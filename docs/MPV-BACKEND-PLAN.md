# MPV as a full playback backend (planned, needs owner approval)

## Status today

- Default engine stays **VLC**; nothing in the running application changed.
- Local files can already be played in **mpv** ("Open in mpv" / the optional
  external-player setting), with subtitles attached.
- A *full* MPV backend is not implemented yet.

## What a full backend requires

1. **Dependency**: `libmpv-dev` (headers + `libmpv.so`) — needs
   `sudo apt install libmpv-dev` on Pop!_OS/Ubuntu, or a vendored
   `mpv/client.h` in the build tree (development-time only).
2. **Code**: `MpvMediaWidget : public AbstractMediaWidget` implementing the
   Kaffeine backend contract (play/stop, position/seek, volume/mute, audio and
   subtitle track enumeration and selection, metadata, aspect ratio, playback
   status) with a Qt render widget for the mpv surface.
3. **Build**: an optional CMake target guarded by `-DWITH_MPV=ON`, so the
   default build stays exactly as today.
4. **Selection**: Settings → Playback engine → `VLC (default)` / `MPV`,
   validated first (backend ready check) and never silently switched.

## Why it is held

- It is a large, intrusive change to the player core, while the owner's standing
  instruction is to avoid destabilising the working build.
- It needs a system package install, which the agent must not perform without
  the owner's explicit action.

## Sequence once approved

1. Install `libmpv-dev` (owner) or vendor the header.
2. Implement the backend behind `-DWITH_MPV=ON`, default OFF.
3. Add the engine setting with a readiness check and a clear “MPV backend
   unavailable” message (no silent fallback).
4. Behavioral tests: engine selection, surface handling, track selection,
   and a side-by-side VLC/MPV playback check.
