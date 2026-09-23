# Changelog

## 0.1.1

Safety and Unraid compatibility update.

- Add global `DRY_RUN` safety switch, defaulting to `true` in example configs
- Prevent downloads and Emby refreshes while global dry-run is active
- Show global dry-run state in the Web UI and disable the real download button while active
- Recognize legacy `Trailer`, `Trailers`, `trailer`, and `trailers` directories case-insensitively
- Treat empty/inaccessible legacy trailer directories safely during scans
- Reuse an existing plural `Trailers`/`trailers` directory for downloads to avoid duplicate directories caused by capitalization
- Add Unraid installation documentation
- Add explicit AI-assisted / vibe-coded development disclosure to the README
- Add tests for global dry-run and legacy trailer directory handling

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
