# Missing Trailer Downloader for Emby (MTDE)

MTDE scans Emby movie libraries for titles without a **local trailer**, searches YouTube with `yt-dlp`, stores a trailer in an Emby-compatible trailer subfolder, and refreshes the affected Emby item.

This repository is a public fork of [`netplexflix/Missing-Trailer-Downloader-For-Plex`](https://github.com/netplexflix/Missing-Trailer-Downloader-For-Plex), adapted for Emby with permission from the upstream project owner.

> **Status:** early Emby port. Movies are implemented first. TV support and more of the original MTDP Web UI will follow.

> **AI-assisted development:** this fork is substantially developed with AI assistance, including OpenAI ChatGPT-assisted coding, refactoring, documentation, and tests. The project is therefore intentionally transparent about being **AI-assisted / vibe-coded**. AI-generated or AI-modified code should still be reviewed and tested like any other contribution.

## Current features

- Emby is the source of truth; Radarr/Sonarr are not required
- Multiple Emby movie libraries
- Detects local trailers using Emby's `LocalTrailerCount` plus a filesystem fallback
- Recognizes existing `trailers`, `Trailers`, `trailer`, and `Trailer` directories case-insensitively
- Empty legacy trailer folders are safe and do not cause scan errors
- Reuses an existing plural `Trailers`/`trailers` directory for new downloads to avoid duplicate folders caused only by capitalization
- Remote/online Emby trailers do **not** block downloading a local trailer
- YouTube search and download via `yt-dlp`
- Preferred search language
- Minimum/maximum trailer resolution
- Maximum trailer duration
- Genre exclusions
- MKV or MP4 output
- Per-item Emby refresh after a successful download
- Emby-path -> container-path mappings for Docker/Unraid
- Web UI on port `2121`
- Global `DRY_RUN` safety switch plus a dedicated Dry-Run button/CLI mode
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
- rename or delete existing files/folders
- refresh Emby metadata

The Web UI also disables the real download button while the global safety switch is active.

The CLI `--dry-run` mode always remains dry regardless of the configured download settings.

## Existing MTDP trailer folders

MTDP installations may already have folders such as:

```text
Movie (2026)/Trailers/
Movie (2026)/Trailer/
Movie (2026)/trailers/
```

MTDE scans the common singular/plural variants case-insensitively. If a supported video file already exists there, the movie is reported as `has_local_trailer` and is skipped.

An **empty** legacy folder is simply treated as empty; it does not trigger an error. For real downloads, MTDE reuses an existing plural `Trailers`/`trailers` folder. Otherwise it creates the configured `TRAILER_FOLDER` (default: `trailers`).

## Trailer layout

For a movie such as:

```text
/media/movies/300 (2006)/300 (2006).mkv
```

MTDE normally writes:

```text
/media/movies/300 (2006)/
├── 300 (2006).mkv
└── trailers/
    └── 300 (2006) - Trailer.mkv
```

If the movie already has a plural `Trailers` directory from MTDP, that directory is reused instead of creating a second lowercase directory.

## Emby API key

Create a dedicated API key in the Emby Server dashboard under **Advanced -> Security**.

MTDE uses Emby's REST API for library discovery, movie metadata, local-trailer state, and item refreshes.

## Configuration

Copy the example configuration:

```bash
cp config/config.example.yml config/config.yml
```

Recommended first-run configuration:

```yaml
EMBY_URL: "http://emby:8096"
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
```

After checking the dry-run results, change:

```yaml
DRY_RUN: false
```

and restart the container to enable actual downloads.

### Path mappings

The filesystem path returned by Emby may differ from the path visible inside the MTDE container.

Example: Emby reports:

```text
/data/media/movies/300 (2006)/300 (2006).mkv
```

but MTDE has the same host media mounted as `/media`. Configure:

```yaml
PATH_MAPPINGS:
  - emby: "/data/media"
    local: "/media"
```

If the dry-run shows `path_missing`, fix this mapping before disabling `DRY_RUN`.

## Unraid

MTDE is not in Community Apps yet. It can be installed directly from GHCR.

Create the config directory first:

```bash
mkdir -p /mnt/cache/appdata/mtde
```

Create `/mnt/cache/appdata/mtde/config.yml` from `config/config.example.yml`, then add a container in **Docker -> Add Container** with these values:

| Field | Value |
| --- | --- |
| Name | `MTDE` |
| Repository | `ghcr.io/mlo-tek/missing-trailer-downloader-for-emby:latest` |
| Network Type | `bridge` |
| WebUI | `http://[IP]:[PORT:2121]/` |
| Container Port | `2121` |
| Host Port | `2121` |
| Config container path | `/config` |
| Config host path | `/mnt/cache/appdata/mtde` |
| Media container path | `/media` |
| Media host path | `/mnt/user/data/media` |
| `PUID` | `99` |
| `PGID` | `100` |
| `TZ` | `Europe/Berlin` |

The media mapping must be **read/write** once downloads are enabled.

For the complete first-run procedure, including the initial dry-run and path-mapping check, see [`docs/UNRAID.md`](docs/UNRAID.md).

After the container starts, open:

```text
http://UNRAID-IP:2121
```

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
      - /path/to/media:/media
      # - ./cookies:/cookies:ro
    restart: unless-stopped
```

## CLI

Test Emby connectivity:

```bash
mtde --config /config/config.yml --test
```

Dry-run without media writes or Emby refreshes:

```bash
mtde --config /config/config.yml --dry-run
```

Scan and download, provided `DRY_RUN: false` and `DOWNLOAD_TRAILERS: true`:

```bash
mtde --config /config/config.yml --scan
```

## Safety behavior

MTDE does not currently delete or replace existing trailers. A movie is skipped when Emby reports a local trailer or when a supported video file is found in a recognized trailer folder.

Supported local trailer extensions currently include:

```text
.mkv .mp4 .m4v .mov .avi .webm .ts .m2ts
```

## Roadmap

- TV/series trailers
- Upgrade/replacement logic for low-resolution trailers
- Better manual search and candidate selection in the Web UI
- Download history/statistics
- Scheduled scans
- Emby new-item event/polling support
- More of the original MTDP Web UI functionality, adapted to Emby
- Unraid Community Apps template

## Development

```bash
python -m unittest discover -s tests -v
```

The Emby port keeps the upstream fork relationship and project inspiration while replacing the Plex-specific server integration with an Emby-native API layer.
