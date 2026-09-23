# Missing Trailer Downloader for Emby (MTDE)

MTDE scans Emby movie libraries for titles without a **local trailer**, searches YouTube with `yt-dlp`, stores the result in an Emby-compatible trailer subfolder, and refreshes the affected Emby item.

This repository is a public fork of [`netplexflix/Missing-Trailer-Downloader-For-Plex`](https://github.com/netplexflix/Missing-Trailer-Downloader-For-Plex), adapted for Emby with permission from the upstream project owner.

> **Status:** `0.2.0` is a Movies-first Emby port. The original MTDP Web UI has been restored as the UI basis and is being adapted to the Emby backend. TV/series support is intentionally hidden until it is actually implemented.

> **AI-assisted development:** this fork is substantially developed with AI assistance, including OpenAI ChatGPT-assisted coding, refactoring, documentation, and tests. The project is intentionally transparent about being **AI-assisted / vibe-coded**. AI-generated or AI-modified code should be reviewed and tested like any other contribution.

## Web UI

Starting with `0.2.0`, MTDE uses the **original MTDP Web UI as its design and interaction base** instead of the temporary minimal interface used during the first Emby backend port.

The restored UI currently includes:

- MTDP-style dark/purple dashboard and navigation
- Movies poster grid with missing/local/remote trailer states
- Emby posters and movie detail modal
- Manual YouTube trailer search and download
- Recently downloaded trailer carousel
- Per-library trailer coverage statistics
- Emby and yt-dlp service status
- Settings editing from the Web UI
- Processing log
- Global Dry-Run indication and protection

Some upstream UI concepts remain internally named `plexpass` for compatibility with the original JavaScript data model. They are displayed to users as **Remote Trailer** and are backed by Emby remote-trailer metadata, not Plex.

## Current features

- Emby is the source of truth; Radarr/Sonarr are not required
- Multiple Emby movie libraries
- Detects local trailers using Emby's `LocalTrailerCount` plus a filesystem fallback
- Recognizes existing `trailers`, `Trailers`, `trailer`, and `Trailer` directories case-insensitively
- Empty legacy trailer folders are safe and do not cause scan errors
- Reuses an existing plural `Trailers`/`trailers` directory for new downloads
- Remote/online Emby trailers do **not** block downloading a local trailer during automatic scans
- YouTube search and download via `yt-dlp`
- Preferred search language
- Minimum/maximum trailer resolution
- Maximum trailer duration
- Genre exclusions
- MKV or MP4 output
- Per-item Emby refresh after a successful download
- Optional Emby-path -> container-path mappings
- Web UI on port `2121`
- Global `DRY_RUN` safety switch
- Docker/Unraid-friendly PUID/PGID support
- GitHub Actions tests and GHCR image publishing

## Dry-run safety

New/example configurations default to:

```yaml
DRY_RUN: true
```

When `DRY_RUN` is enabled, MTDE may query Emby and search YouTube for candidates, but it will **not**:

- create trailer directories
- download trailer files
- delete existing trailer files
- rename existing files/folders
- refresh Emby metadata

The CLI `--dry-run` mode is also always non-writing. Keep `DRY_RUN: true` for the first scan on an existing library.

## Existing MTDP trailer folders

Existing MTDP installations may already have folders such as:

```text
Movie (2026)/Trailers/
Movie (2026)/Trailer/
Movie (2026)/trailers/
```

MTDE scans the common singular/plural variants case-insensitively. If a supported video file already exists there, the movie is treated as having a local trailer and is skipped by automatic downloading.

An **empty** legacy folder is simply treated as empty; it does not trigger an error. For real downloads, MTDE reuses an existing plural `Trailers`/`trailers` folder. Otherwise it creates the configured `TRAILER_FOLDER` (default: `trailers`).

## Trailer layout

Typical layout:

```text
/data/media/movies/300 (2006)/
├── 300 (2006).mkv
└── trailers/
    └── 300 (2006) - Trailer.mkv
```

If the movie already has a plural `Trailers` directory from MTDP, that directory is reused instead of creating another directory differing only by capitalization.

## Emby API key

Create a dedicated API key in the Emby Server dashboard under **Advanced -> Security**.

MTDE uses Emby's REST API for library discovery, movie metadata, posters, trailer state, and targeted item refreshes.

## Configuration

Recommended first-run configuration:

```yaml
EMBY_URL: "http://10.20.20.16:8096"
EMBY_API_KEY: "CHANGE_ME"

MOVIE_LIBRARIES:
  - "Movies"

DRY_RUN: true
DOWNLOAD_TRAILERS: true

PREFERRED_LANGUAGE: "german deutsch"
TRAILER_FOLDER: "trailers"
TRAILER_FILE_FORMAT: "mkv"
TRAILER_RESOLUTION_MIN: 1080
TRAILER_RESOLUTION_MAX: 2160
MAX_TRAILER_DURATION: 300
SEARCH_RESULTS: 8

REFRESH_EMBY_AFTER_DOWNLOAD: true
WEB_PORT: 2121

PATH_MAPPINGS: []
```

After checking the Dry-Run results, change:

```yaml
DRY_RUN: false
```

and restart the container, or change the setting in the Web UI.

### Path mappings

The simplest Docker/Unraid setup is to mount the media at the **same container path in Emby and MTDE**. For example, if Emby reports:

```text
/data/media/movies/300 (2006)/300 (2006).mkv
```

mount the host media into MTDE at `/data/media` as well and use:

```yaml
PATH_MAPPINGS: []
```

Only use `PATH_MAPPINGS` when the two containers genuinely see the same host files under different internal paths.

Example:

```yaml
PATH_MAPPINGS:
  - emby: "/data/media"
    local: "/media"
```

## Unraid

MTDE is not in Community Apps yet. It can be installed directly from GHCR.

Create the config directory:

```bash
mkdir -p /mnt/cache/appdata/mtde
```

Create `/mnt/cache/appdata/mtde/config.yml`, then add a container in **Docker -> Add Container**:

| Field | Value |
| --- | --- |
| Name | `MTDE` |
| Repository | `ghcr.io/mlo-tek/missing-trailer-downloader-for-emby:latest` |
| WebUI | `http://[IP]:[PORT:2121]/` |
| Container Port | `2121` |
| Host Port | `2121` when using bridge networking |
| Config container path | `/config` |
| Config host path | `/mnt/cache/appdata/mtde` |
| Media container path | `/data/media` if that matches Emby |
| Media host path | `/mnt/user/data/media` |
| `PUID` | `99` |
| `PGID` | `100` |
| `TZ` | `Europe/Berlin` |

The media mapping must be **read/write** once `DRY_RUN` is disabled.

For more detail see [`docs/UNRAID.md`](docs/UNRAID.md).

## Docker Compose

```yaml
services:
  mtde:
    image: ghcr.io/mlo-tek/missing-trailer-downloader-for-emby:latest
    container_name: MTDE
    ports:
      - "2121:2121"
    environment:
      - TZ=Europe/Berlin
      - PUID=99
      - PGID=100
    volumes:
      - ./config:/config
      - /mnt/user/data/media:/data/media
    restart: unless-stopped
```

## CLI

Test Emby connectivity:

```bash
mtde --config /config/config.yml --test
```

Dry-run:

```bash
mtde --config /config/config.yml --dry-run
```

Scan and download, provided `DRY_RUN: false` and `DOWNLOAD_TRAILERS: true`:

```bash
mtde --config /config/config.yml --scan
```

## Safety behavior

MTDE does not automatically replace existing local trailers. A movie is skipped when Emby reports a local trailer or when a supported video file is found in a recognized trailer folder.

Supported local trailer extensions currently include:

```text
.mkv .mp4 .m4v .mov .avi .webm .ts .m2ts
```

Manual deletion from the Web UI is disabled while `DRY_RUN` is active and is restricted to trailer files that MTDE actually detected for the selected Emby item.

## Roadmap

- TV/series trailer support and re-enable the original TV Shows UI when ready
- Complete remaining upstream MTDP feature adaptations for Emby
- Upgrade/replacement logic for low-resolution trailers
- Persisted download history/statistics
- Scheduled scans
- Emby new-item event/polling support
- Unraid Community Apps template

## Development

```bash
python -m unittest discover -s tests -v
```

The fork deliberately keeps the upstream MTDP UI heritage while replacing the Plex server integration with an Emby-native backend.
