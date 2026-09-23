# Changelog

## 0.3.4

Add a first Unraid Docker template and standardize the cookies mount.

- Add `templates/unraid/mtde.xml` with WebUI, config, media and optional cookies path entries
- Standardize the optional cookies bind mount as `/cookies/cookies.txt`
- Document the Unraid host path `/mnt/cache/appdata/mtde/cookies.txt`
- Update the Docker Compose example to show the same cookies mount
- Keep `COOKIES_FILE` empty by default and only enable `/cookies/cookies.txt` when a readable cookies file exists

## 0.3.3

Make an unreadable cookies file non-fatal for scans.

- Validate `COOKIES_FILE` when the downloader is configured
- Ignore a missing or unreadable cookies file instead of failing each movie search with `Permission denied`
- Continue YouTube searches without cookies when the configured cookies file is not usable

## 0.3.2

Make scan progress visible live in the Web UI processing log.

- Stream per-library and per-movie progress to the Web UI log while a scan is running
- Add live `CHECKING`, `SEARCHING`, `SEARCH_RESULTS`, `MATCH`, `WOULD_DOWNLOAD`, `HAS_LOCAL_TRAILER`, `PATH_MISSING`, `DOWNLOADING`, `DOWNLOADED` and `STOPPED` style log entries
- Keep yt-dlp stdout in the container log, but mirror the important scan milestones into MTDE's `/api/log`
- Preserve cooperative stop behavior; an active yt-dlp operation may still finish before the stop flag is honored

## 0.3.1

Make Dry Run and real scans directly controllable from the Web UI.

- Add dashboard buttons for `Dry-Run Scan starten`, `Echten Scan starten` and `Scan stoppen`
- Add `/api/run/dry-run`, `/api/run/real-run`, `/api/run/stop` and `/api/run/status`
- Persist the selected run mode by writing `DRY_RUN` back to `config.yml`
- Log explicit UI requests such as `DRY-RUN SCAN REQUESTED FROM WEB UI` and `REAL RUN REQUESTED FROM WEB UI`
- Add scan status fields for running/stopping, current mode, start time and last run
- Add cooperative stop handling between movies; an active yt-dlp download may finish before the stop takes effect
- Keep scheduler start/stop separate from scan stop to avoid UI confusion

## 0.3.0

Bring the restored MTDP settings experience in line with the Emby-native backend.

- Remove stale Plex/MTDfP label controls from the Web UI; MTDE does not use Plex or MTDfP labels
- Remove the stale Reset Upgrade History control; MTDE has no persisted MTDfP upgrade-attempt database
- Restore/adapt the main upstream settings groups for Emby instead of exposing a reduced two-setting page
- Add Emby API timeout setting
- Add `CHECK_REMOTE_TRAILERS` so users can choose whether Emby remote trailers count as covered
- Add preferred-language selector, yt-dlp progress toggle, cookies path and protected custom yt-dlp options
- Add per-library genre exclusions using upstream-style movie library entries
- Add real hours/cron scheduling
- Add Emby-native new-item detection through lightweight polling and configurable delay
- Add `UPGRADE_TRAILERS: local` to safely replace local trailers below the configured minimum resolution
- Keep the old trailer until a replacement download succeeds
- Measure local trailer resolution with ffprobe for UI statistics/upgrades
- Keep legacy `Trailer` / `Trailers` detection case-insensitive and Dry Run non-writing
- Preserve compatibility with early MTDE flat `MOVIE_LIBRARIES` / `SKIP_GENRES` configs
- Keep the project AI-assisted / vibe-coded disclosure in the README

## 0.2.0

Restore the upstream MTDP Web UI as the basis for the Emby fork.

- Restore the original MTDP dashboard/navigation/layout instead of the temporary minimal UI
- Rebrand the UI as MTDE and replace visible Plex-specific terminology with Emby equivalents
- Add Emby-native Movies library, poster, item-detail, dashboard and connection endpoints for the restored UI
- Add manual trailer search/download support from the original-style movie detail dialog
- Keep the internal `plexpass` UI status key temporarily as a compatibility field while displaying it as `Remote Trailer`
- Hide TV-specific UI until the TV backend has actually been ported
- Preserve the global `DRY_RUN` safety switch for automatic and manual downloads/deletes
- Preserve case-insensitive support for existing `Trailer`, `Trailers`, `trailer` and `trailers` directories
- Add settings editing from the restored Web UI with live config reload
- Add Emby poster proxy and local trailer playback endpoints
- Keep the project AI-assisted / vibe-coded disclosure in the README

## 0.1.1

- Add global `DRY_RUN` safety switch
- Recognize existing Trailer/Trailers folders case-insensitively
- Reuse existing plural trailer directories
- Add Unraid documentation and AI-assisted development disclosure

## 0.1.0

Initial Emby-native port.

- Replace Plex API dependency with an Emby REST client
- Movies-first library scanning
- Detect local trailers through `LocalTrailerCount` and filesystem fallback
- Download trailers with yt-dlp into Emby's trailer folder
- Per-item Emby refresh after successful downloads
- Docker/Unraid path mappings
- Minimal initial Web UI and CLI dry-run/test modes
- PUID/PGID container support
- GitHub Actions tests and GHCR image build
