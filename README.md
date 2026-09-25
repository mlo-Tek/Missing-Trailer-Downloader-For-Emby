# Missing Trailer Downloader for Emby (MTDE)

MTDE scans Emby **Movie and TV Show libraries** for missing local trailers, searches YouTube with `yt-dlp`, stores trailers in Emby-compatible locations, and refreshes the affected Emby item.

This repository is a public fork of [`netplexflix/Missing-Trailer-Downloader-For-Plex`](https://github.com/netplexflix/Missing-Trailer-Downloader-For-Plex), adapted for Emby with permission from the upstream project owner.

> **0.4.0 architecture:** MTDP remains the behavioral reference. Movies and TV Shows keep separate upstream-style search/matching flows. The fork replaces Plex-specific library/item/trailer/refresh access with Emby equivalents and retains only narrowly scoped Emby/safety additions that were validated during real MTDE runs.

> **AI-assisted development:** this fork is substantially developed with AI assistance, including OpenAI ChatGPT-assisted coding, refactoring, documentation and tests. AI-generated or AI-modified code should be reviewed and tested like any other contribution.

## Upstream parity

Like MTDP in Docker, a normal MTDE run processes **both** configured media types consecutively:

1. all `MOVIE_LIBRARIES`
2. all `TV_LIBRARIES`

Movies use the MTDP Movies-style search/matcher. TV Shows use the separate MTDP `Modules/TV.py` search/matcher and its TV-specific YouTube queries. The Emby fork does not run TV Shows through the movie matcher.

The following are intentionally Emby-specific:

- Plex connection/token calls -> Emby URL/API key
- Plex sections/items -> Emby libraries/items
- Plex extras/trailer state -> Emby `LocalTrailerCount`, `RemoteTrailers` plus filesystem verification
- Plex metadata refresh -> Emby item/library refresh
- Plex labels/MTDfP labels are omitted because they are Plex-specific
- optional `PATH_MAPPINGS` when Emby and MTDE see media under different container paths

## Web UI

The Web UI keeps the MTDP layout and exposes:

- Dashboard
- Movies
- TV Shows
- Settings
- Log
- trailer coverage/statistics
- manual search/download
- trailer playback
- Emby item/library refresh

Movie and TV libraries are configured independently, including per-library genre exclusions.

## Configuration

```yaml
EMBY_URL: "http://10.20.20.16:8096"
EMBY_API_KEY: "CHANGE_ME"
EMBY_TIMEOUT: 120

MOVIE_LIBRARIES:
  - name: "Filme Kids"
    genres_to_skip: []
  - name: "Filme"
    genres_to_skip: []

TV_LIBRARIES:
  - name: "Serien Kids"
    genres_to_skip: []

DRY_RUN: true

CHECK_REMOTE_TRAILERS: false
DOWNLOAD_TRAILERS: true
PREFERRED_LANGUAGE: "german"
REFRESH_EMBY_AFTER_DOWNLOAD: true
SHOW_YT_DLP_PROGRESS: false

TRAILER_FOLDER: "trailers"
TRAILER_FILE_FORMAT: "mkv"
TRAILER_RESOLUTION_MIN: 480
TRAILER_RESOLUTION_MAX: 2160
MAX_TRAILER_DURATION: 300
SEARCH_RESULTS: 15
UPGRADE_TRAILERS: "local"

YT_DLP_CUSTOM_OPTIONS: []
COOKIES_FILE: ""

SCHEDULE_TYPE: "disabled"
SCHEDULE_HOURS: 24
SCHEDULE_CRON: "0 */6 * * *"
NEW_ITEM_DETECTION: false
NEW_ITEM_DELAY: 60

WEB_PORT: 2121
PATH_MAPPINGS: []
```

Settings changed in the Web UI are written back to `/config/config.yml` and reloaded without restarting MTDE.

## Dry Run

Keep this enabled for the first scan after a major update:

```yaml
DRY_RUN: true
```

When Dry Run is active MTDE may read Emby metadata and search YouTube, but it will not:

- create/download trailer files
- delete or replace trailer files
- refresh Emby metadata

The same switch applies to Movies and TV Shows.

## Movie trailer layout

Movie trailers use the existing MTDE/MTDP-compatible Trailer/Trailers folder handling. Folder names are detected case-insensitively and an existing plural folder is reused.

Example:

```text
/data/media/movies/300 (2006)/
├── 300 (2006).mkv
└── Trailers/
    └── 300 (2006) - Trailer.mkv
```

Supported local trailer extensions include:

```text
.mkv .mp4 .m4v .mov .avi .webm .ts .m2ts
```

## TV Show trailer layout

TV behavior follows upstream `Modules/TV.py` conventions. A TV Show is considered to have a local trailer when MTDE finds either:

- a video in the series root whose filename ends in `-trailer`, or
- a supported video in the series `Trailers/` directory

New TV trailer downloads are written to `Trailers/` and use the upstream-style series filename, resolution tag, and language tag when the selected source explicitly matches the preferred language.

Example:

```text
/data/media/tv/Bluey (2018)/
└── Trailers/
    └── Bluey.1080p.de-trailer.mkv
```

## Remote trailers

By default:

```yaml
CHECK_REMOTE_TRAILERS: false
```

An Emby remote/online trailer therefore does **not** prevent MTDE from downloading a local trailer. Set it to `true` if Emby remote trailers should count as covered.

## Low-resolution upgrades

```yaml
UPGRADE_TRAILERS: "local"
TRAILER_RESOLUTION_MIN: 480
```

For Movies, a local trailer below the configured minimum is searched again. The existing file is removed only after a better replacement has downloaded and been verified.

TV Shows retain the upstream TV upgrade behavior: a better replacement may be kept even if it is still below the configured target; the old trailer is never removed before a usable replacement exists.

## Scheduler

Scheduled runs execute the same combined Movies-then-TV scan as a manual run.

```yaml
SCHEDULE_TYPE: "hours"
SCHEDULE_HOURS: 6
```

or:

```yaml
SCHEDULE_TYPE: "cron"
SCHEDULE_CRON: "0 */6 * * *"
```

## Web UI performance

Movie/TV library data and dashboard statistics use a persistent stale-while-revalidate cache under `/config/cache`. Expired data can be shown immediately while a refresh runs in the background. Trailer ffprobe results are cached for unchanged files.

The Dashboard Resolution card intentionally displays only the six useful tiers:

```text
2160p  1440p  1080p  720p  480p  360p
```

Exact ffprobe heights remain available internally and are not changed by this display filter.

## Unraid

Image:

```text
ghcr.io/mlo-tek/missing-trailer-downloader-for-emby:latest
```

Recommended mappings:

| Host | Container | Mode |
| --- | --- | --- |
| `/mnt/cache/appdata/mtde` | `/config` | RW |
| `/mnt/user/data/media` | `/data/media` | RW |

Environment:

```text
PUID=99
PGID=100
TZ=Europe/Berlin
```

Web UI:

```text
http://UNRAID-IP:2121
```

If Emby also sees the media as `/data/media`, use:

```yaml
PATH_MAPPINGS: []
```

Only use path mappings when Emby and MTDE genuinely see the same files under different container paths.

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

Dry Run across configured Movie and TV libraries:

```bash
mtde --config /config/config.yml --dry-run
```

Real scan/download requires both `DRY_RUN: false` and `DOWNLOAD_TRAILERS: true`:

```bash
mtde --config /config/config.yml --scan
```

## Development

```bash
python -m unittest discover -s tests -v
```

The fork deliberately preserves MTDP's Movies/TV behavior and UI heritage while replacing Plex-specific media-server access with Emby-native equivalents.
