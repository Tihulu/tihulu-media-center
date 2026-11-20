# TIHULU Media First Stable — Installation Layout

## File Hierarchy

```
~/.local/opt/tihulu-kaffeine/              (Live installation — DO NOT MODIFY)
├── bin/
│   ├── kaffeine                           (2,637,160 bytes, ELF 64-bit x86-64)
│   └── tihulu-media-center -> kaffeine    (symlink)
├── lib/
│   └── x86_64-linux-gnu/                  (Custom libraries, if any)
└── share/
    ├── applications/
    │   └── org.kde.kaffeine.desktop       (5,350 bytes)
    ├── icons/
    │   └── hicolor/
    │       ├── icon-theme.cache
    │       └── scalable/
    │           ├── actions/               (34 icon files)
    │           ├── apps/
    │           ├── devices/
    │           ├── mimetypes/
    │           ├── places/
    │           └── status/
    ├── kaffeine/
    │   └── scanfile.dvb                   (1,880,284 bytes)
    ├── locale/                            (57 locale files)
    ├── metainfo/
    │   └── org.kde.kaffeine.appdata.xml
    └── solid/
        └── actions/
            ├── kaffeine_play_audiocd.desktop
            ├── kaffeine_play_dvd.desktop
            └── kaffeine_play_videocd.desktop

~/.local/bin/tihulu-kaffeine               (Launcher script, 2,059 bytes)
~/.local/share/tihulu-kaffeine/            (Runtime data)
├── build-system-qt5/                      (Build metadata)
├── upstream-v2.0.19/                      (Upstream source)
├── dvb_diagnostics.sh                     (Diagnostic script)
├── install_welle.sh                       (Welle installation script)
└── logs/                                  (Application logs)
~/.config/kaffeinerc                       (User preferences)
~/.config/tihulu-media-centerrc            (TIHULU-specific settings)
```

## Archive Layout

```
<ARCHIVE_ROOT>/
├── archive/                               (Binary archive)
│   ├── bin/
│   │   ├── kaffeine
│   │   └── tihulu-media-center -> kaffeine
│   ├── share/                             (All share resources)
│   └── tihulu-kaffeine                    (Launcher copy)
│   └── manifest-verified.sha256           (Full manifest, 114 entries)
├── gh-content/
│   └── media/
│       └── first-stable/
│           ├── README.md
│           ├── VERSION
│           ├── original-identity.md
│           ├── source-provenance.md
│           ├── runtime-dependencies.md
│           ├── manifest.sha256
│           ├── install.sh
│           ├── verify.sh
│           ├── restore.sh
│           ├── rollback.md
│           ├── acceptance.md
│           └── release-checklist.md
├── first-stable-v1-original.tar.gz        (Full tar archive)
└── tihulu-first-stable-manifest.sha256    (Quick manifest)
```

## Installation Paths

| Component | Path | Purpose |
|-----------|------|---------|
| Binary | `~/.local/opt/tihulu-kaffeine/bin/kaffeine` | Main executable |
| Launcher | `~/.local/bin/tihulu-kaffeine` | Environment wrapper |
| Symlink | `~/.local/opt/tihulu-kaffeine/bin/tihulu-media-center` | Alias for binary |
| DVB Channels | `~/.local/opt/tihulu-kaffeine/share/kaffeine/scanfile.dvb` | Channel list |
| Config | `~/.config/kaffeinerc` | User settings |
| Settings | `~/.config/tihulu-media-centerrc` | TIHULU settings |
| Data | `~/.local/share/tihulu-kaffeine/` | Runtime data |

## Dependency Summary

- Qt5 Core (libQt5Core.so.5)
- Qt5 GUI (libQt5Gui.so.5)
- Qt5 Widgets (libQt5Widgets.so.5)
- Qt5 Network, SQL, XML, D-Bus, Svg, PrintSupport, WaylandClient, X11Extras
- KDE Frameworks 5 (CoreAddons, WidgetsAddons, Config*, I18n, IconThemes, XmlGui, Solid, Service, Crash, AuthCore, Bookmarks, Completion, GuiAddons, ItemViews, JobWidgets, GlobalAccel, KIO*, WindowSystem)
- VLC (libvlc.so.5, libvlccore.so.9)
- DVB (libdvbv5.so.0)
- System (udev, dbus, X11, GL, zlib, ICU, etc.)

## Platform Requirements

- OS: Pop!_OS 24.04 / Ubuntu 24.04 LTS
- Architecture: x86_64
- Display: X11 or XWayland
- DE: KDE Plasma or COSMIC with XWayland