# Changelog

## 0.1.0

Initial Emby-native port.

- Replace Plex API dependency with an Emby REST client
- Movies-first library scanning
- Detect local trailers through `LocalTrailerCount` and filesystem fallback
- Download trailers with yt-dlp into Emby's `trailers/` folder
- Per-item Emby refresh after successful downloads
- Docker/Unraid path mappings
- Minimal Web UI and CLI dry-run/test modes
- PUID/PGID container support
- GitHub Actions tests and GHCR image build
