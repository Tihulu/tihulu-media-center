# AppImage build

Build from the public source tree:

```bash
packaging/appimage/build-appimage.sh --output ./tihulu-media-center.AppImage
```

The build:

- Uses the pinned KDE Kaffeine revision
- Applies the repository's pinned native patches
- Bundles the native binary and the TV Center Python companion
- Does not bundle AI models; AI stays optional through the in-app market
- Reuses installed AI models when `TIHULU_ASSET_HOME` points to the existing HOME

If `appimagetool` is not installed, the script creates a portable `AppDir.tar`
instead of a single-file AppImage.
