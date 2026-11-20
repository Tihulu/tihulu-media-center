# Runtime Dependencies — TIHULU Media First Stable

## System Dependencies (Required at Runtime)

These libraries MUST be available on the target system. All are provided by
Pop!_OS 24.04 / Ubuntu 24.04 base installations.

### Core Framework Libraries

| Library | Version/Path | Purpose |
|---------|-------------|---------|
| `libQt5Core.so.5` | system | Qt5 core |
| `libQt5Gui.so.5` | system | Qt5 GUI |
| `libQt5Widgets.so.5` | system | Qt5 widgets |
| `libQt5Sql.so.5` | system | Qt5 SQL database |
| `libQt5Network.so.5` | system | Qt5 networking |
| `libQt5DBus.so.5` | system | Qt5 D-Bus |
| `libQt5Xml.so.5` | system | Qt5 XML parsing |
| `libQt5Svg.so.5` | system | Qt5 SVG rendering |
| `libQt5PrintSupport.so.5` | system | Qt5 printing |
| `libQt5WaylandClient.so.5` | system | Wayland client support |
| `libQt5X11Extras.so.5` | system | X11 extras |
| `libstdc++.so.6` | system | C++ standard library |
| `libc.so.6` | system | C library |
| `libm.so.6` | system | Math library |

### KDE Frameworks 5

| Library | Purpose |
|---------|---------|
| `libKF5CoreAddons.so.5` | Core KDE utilities |
| `libKF5WidgetsAddons.so.5` | Widget extensions |
| `libKF5ConfigCore.so.5` | Configuration framework |
| `libKF5ConfigGui.so.5` | GUI configuration |
| `libKF5I18n.so.5` | Internationalization |
| `libKF5IconThemes.so.5` | Icon theme support |
| `libKF5XmlGui.so.5` | XML-based GUI |
| `libKF5Solid.so.5` | Hardware abstraction |
| `libKF5Service.so.5` | D-Bus services |
| `libKF5Crash.so.5` | Crash handling |
| `libKF5AuthCore.so.5` | Authentication |
| `libKF5Bookmarks.so.5` | Bookmark management |
| `libKF5Completion.so.5` | Auto-completion |
| `libKF5GuiAddons.so.5` | GUI extensions |
| `libKF5ItemViews.so.5` | Item view widgets |
| `libKF5JobWidgets.so.5` | Job progress widgets |
| `libKF5GlobalAccel.so.5` | Global shortcuts |
| `libKF5KIOCore.so.5` | KIO core |
| `libKF5KIOWidgets.so.5` | KIO widgets |
| `libKF5KIOFileWidgets.so.5` | File selection widgets |
| `libKF5KIOGui.so.5` | KIO GUI |
| `libKF5WindowSystem.so.5` | Window management |

### Media Libraries

| Library | Purpose |
|---------|---------|
| `libvlc.so.5` | VLC media player core |
| `libvlccore.so.9` | VLC core runtime |

### Hardware/Device Libraries

| Library | Purpose |
|---------|---------|
| `libdvbv5.so.0` | DVBv5 API for digital TV |
| `libudev.so.1` | Device management |
| `libimobiledevice-1.0.so.6` | iOS device support |
| `libplist-2.0.so.4` | Apple property list parsing |
| `libusbmuxd-2.0.so.6` | USB multiplexer (iOS) |

### System Libraries

| Library | Purpose |
|---------|---------|
| `libz.so.1` | Compression |
| `libssl.so.3` | TLS/SSL |
| `libcrypto.so.3` | Cryptography |
| `libdbus-1.so.3` | D-Bus messaging |
| `libX11.so.6` | X11 window system |
| `libxcb.so.1` | X11 C binding |
| `libGL.so.1` | OpenGL |
| `libpng16.so.16` | PNG image support |
| `libfreetype.so.6` | Font rendering |
| `libfontconfig.so.1` | Font configuration |
| `libharfbuzz.so.0` | Text shaping |
| `libicuuc.so.74` / `libicudata.so.74` / `libicui18n.so.74` | ICU internationalization |
| `libxkbcommon.so.0` | Keyboard handling |
| `libglib-2.0.so.0` | GLib utilities |
| `libpcre2-16.so.0` / `libpcre2-8.so.0` | Regular expressions |
| `libbz2.so.1.0` | Bzip2 compression |
| `liblzma.so.5` | XZ compression |
| `liblz4.so.1` | LZ4 compression |
| `libzstd.so.1` | Zstandard compression |
| `libgcrypt.so.20` / `libgpg-error.so.0` | Encryption |
| `libsystemd.so.0` | systemd integration |
| `libmount.so.1` / `libblkid.so.1` / `libselinux.so.1` | Filesystem/mount handling |
| `libkrb5.so.3` / `libk5crypto.so.3` / `libkrb5support.so.0` / `libgssapi_krb5.so.2` | Kerberos |
| `libexpat.so.1` | XML parser |
| `libdouble-conversion.so.3` | String conversion |
| `libmd4c.so.0` | Markdown parser |
| `libidn.so.12` / `libcap.so.2` / `libacl.so.1` / `libattr.so.1` | POSIX utilities |
| `libgcc_s.so.1` | GCC support library |
| `libffi.so.8` / `libmd.so.0` / `libkeyutils.so.1` / `libcom_err.so.2` | System utilities |
| `libgraphite2.so.3` | Graphite2 font engine |
| `libbrotlidec.so.1` / `libbrotlicommon.so.1` | Brotli compression |
| `libxcb-keysyms.so.1` | XCB keysyms |
| `libwayland-client.so.0` / `libwayland-cursor.so.0` | Wayland client |
| `libXau.so.6` / `libXdmcp.so.6` | X11 authentication |
| `libresolv.so.2` | DNS resolution |

## Runtime Configuration

### Environment Variables (Set by Launcher)

| Variable | Value | Purpose |
|----------|-------|---------|
| `TIHULU_VLC_PROFILE` | `software` / `auto` / `software-no-audio` | Video decoder profile |
| `TIHULU_AUTOPLAY_LAST_CHANNEL` | `0` or `1` | Enable last-channel autoplay |

### Launcher Behavior

The launcher (`~/.local/bin/tihulu-kaffeine`):

1. Sets `QT_QPA_PLATFORM=xcb` when running under Wayland (NVIDIA/XWayland path)
2. Clears `LD_LIBRARY_PATH`, `LD_PRELOAD`, `QT_PLUGIN_PATH`, `QT_QPA_PLATFORM_PLUGIN_PATH`,
   `QML2_IMPORT_PATH`, `QML_IMPORT_PATH` to avoid Conda/library conflicts
3. Passes `--diagnose-tuner`, `--software-video`, `--auto-video`, `--diagnose-no-audio` flags
4. Launches via `~/.local/opt/tihulu-kaffeine/bin/tihulu-media-center` (symlink to kaffeine)

### Configuration Files

| Path | Purpose |
|------|---------|
| `~/.config/kaffeinerc` | Kaffeine application settings |
| `~/.config/tihulu-media-centerrc` | TIHULU-specific settings |
| `~/.local/share/tihulu-kaffeine/` | Application data (build logs, diagnostics) |

## Architecture Requirements

- **CPU:** x86_64 (Intel/AMD 64-bit)
- **GPU:** Any (software rendering supported via VLC profile)
- **Display:** X11 or XWayland (not native Wayland)
- **Memory:** Minimum 1 GB recommended
- **Storage:** ~10 MB for application files (plus VLC runtime ~200 MB system-wide)

## Incompatible Systems

- ARM64 (Raspberry Pi 5, etc.) — NOT compatible
- Non-Qt5 Linux distributions — NOT tested
- Pure Wayland without XWayland — NOT tested
- Systems without DVB support libraries — TV/radio features unavailable
