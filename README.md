# Missing Trailer Downloader for Emby (MTDE)

MTDE scans Emby movie libraries for missing **local trailers**, searches YouTube with `yt-dlp`, stores trailers in an Emby-compatible trailer folder, and refreshes the affected Emby item.

This repository is a public fork of [`netplexflix/Missing-Trailer-Downloader-For-Plex`](https://github.com/netplexflix/Missing-Trailer-Downloader-For-Plex), adapted for Emby with permission from the upstream project owner.

> **Status:** `0.3.0` is a Movies-first Emby port. The original MTDP Web UI remains the design/interaction base. TV/series UI stays hidden until the TV backend is actually ported.

> **AI-assisted development:** this fork is substantially developed with AI assistance, including OpenAI ChatGPT-assisted coding, refactoring, documentation and tests. The project is intentionally transparent about being **AI-assisted / vibe-coded**. AI-generated or AI-modified code should be reviewed and tested like any other contribution.

## Important: no Plex/MTDfP labels

**MTDE does not use Plex labels or MTDfP labels.**

The upstream MTDP controls `Remove All MTDfP Labels`, `Reset Upgrade History` and the `USE_LABELS` workflow are Plex-specific and are intentionally not part of MTDE. If you saw those controls in `0.2.0`, they were stale frontend remnants from the restored upstream UI and have been removed in `0.3.0`.

The internal Web UI still uses the string `plexpass` in a few JavaScript data fields solely for compatibility with the upstream template. It is displayed as **Remote Trailer** and refers to Emby's remote/online trailer metadata, not Plex.

## Web UI and settings

The Web UI keeps the original MTDP layout: Dashboard, Settings, Movies, Log, movie cards, detail dialog, manual search, trailer playback, coverage statistics and service status.

`0.3.0` restores the useful upstream settings as Emby-native equivalents instead of showing a reduced settings page:

- **General**
  - Dry Run
- **Emby Connection**
  - Emby URL
  - Emby API Key
  - Emby Timeout
- **Trailer Settings**
  - Check Remote Trailers
  - Download Trailers
  - Preferred Language
  - Refresh Emby After Download
  - Show yt-dlp Progress
  - Trailer File Format
  - Minimum / Maximum Trailer Resolution
  - Maximum Trailer Duration
  - YouTube Search Results
  - Trailer Folder
  - Cookies File
  - Upgrade Low-Resolution Trailers
- **YT-DLP Custom Options**
  - Additional CLI-style yt-dlp options, with MTDE-owned path/format/safety options protected
- **Scheduler**
  - Disabled / every X hours / cron
  - New Item Detection
  - Detection Delay
- **Movie Libraries**
  - Multiple Emby movie libraries
  - Per-library genre exclusions

Plex-specific settings such as label handling are deliberately omitted. TV-specific launch behavior is also omitted while the TV backend is not implemented.

## Dry-run safety

Keep this enabled for the first scan:

```yaml
DRY_RUN: true
```

When Dry Run is enabled, MTDE can read Emby data and search YouTube, but it will not:

- create trailer directories
- download trailer files
- delete or replace trailer files
- refresh Emby metadata

The Web UI and automatic/scheduled scans use the same global safety switch.

## Existing MTDP trailer folders

Existing MTDP libraries may contain any of these:

```text
Movie (2026)/Trailer/
Movie (2026)/Trailers/
Movie (2026)/trailer/
Movie (2026)/trailers/
```

MTDE detects `Trailer`/`Trailers` case-insensitively. An existing supported video file counts as a local trailer. An empty legacy folder is safe and does not cause an error. For new downloads MTDE reuses an existing plural `Trailers`/`trailers` directory instead of creating a duplicate that differs only by capitalization.

Supported local trailer extensions:

```text
.mkv .mp4 .m4v .mov .avi .webm .ts .m2ts
```

## Remote trailer behavior

By default:

```yaml
CHECK_REMOTE_TRAILERS: false
```

That means an Emby remote/online trailer does **not** prevent MTDE from downloading a local trailer. Set it to `true` if remote trailers should count as covered.

## Low-resolution upgrades

```yaml
UPGRADE_TRAILERS: "off"
```

Options:

- `off` — never replace existing local trailers automatically
- `local` — if MTDE can measure an existing local trailer below `TRAILER_RESOLUTION_MIN`, it searches for a replacement

The replacement is fail-safe: the old trailer is removed only **after** the new trailer has downloaded successfully. There is no MTDfP label or persistent failed-upgrade database; therefore no `Reset Upgrade History` button is needed.

## Configuration example

```yaml
EMBY_URL: "http://10.20.20.16:8096"
EMBY_API_KEY: "CHANGE_ME"
EMBY_TIMEOUT: 120

MOVIE_LIBRARIES:
  - name: "Movies"
    genres_to_skip:
      - "Short"
      - "Concert"

DRY_RUN: true

CHECK_REMOTE_TRAILERS: false
DOWNLOAD_TRAILERS: true
PREFERRED_LANGUAGE: "german"
REFRESH_EMBY_AFTER_DOWNLOAD: true
SHOW_YT_DLP_PROGRESS: false
TRAILER_FOLDER: "trailers"
TRAILER_FILE_FORMAT: "mkv"
TRAILER_RESOLUTION_MIN: 1080
TRAILER_RESOLUTION_MAX: 2160
MAX_TRAILER_DURATION: 300
SEARCH_RESULTS: 8
UPGRADE_TRAILERS: "off"

YT_DLP_CUSTOM_OPTIONS: []
# COOKIES_FILE: "/cookies/cookies.txt"

SCHEDULE_TYPE: "disabled"
SCHEDULE_HOURS: 24
SCHEDULE_CRON: "0 */6 * * *"
NEW_ITEM_DETECTION: false
NEW_ITEM_DELAY: 60

WEB_PORT: 2121
PATH_MAPPINGS: []
```

Settings changed in the Web UI are written back to `/config/config.yml` and reloaded without restarting MTDE.

## Scheduler and new-item detection

Scheduled scans support:

```yaml
SCHEDULE_TYPE: "hours"
SCHEDULE_HOURS: 6
```

or a standard 5-field cron expression:

```yaml
SCHEDULE_TYPE: "cron"
SCHEDULE_CRON: "0 */6 * * *"
```

Emby does not use Plex's notification mechanism. MTDE therefore implements new-item detection with lightweight Emby polling:

```yaml
NEW_ITEM_DETECTION: true
NEW_ITEM_DELAY: 60
```

The first poll establishes a baseline. Movies detected afterward are queued and trigger a scan after the configured delay.

## Trailer layout

Typical layout:

```text
/data/media/movies/300 (2006)/
├── 300 (2006).mkv
└── trailers/
    └── 300 (2006) - Trailer.mkv
```

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

Dry-run:

```bash
mtde --config /config/config.yml --dry-run
```

Real scan/download requires both `DRY_RUN: false` and `DOWNLOAD_TRAILERS: true`:

```bash
mtde --config /config/config.yml --scan
```

## Current scope / roadmap

Implemented for Movies:

- Emby-native library discovery and metadata
- local/remote trailer state
- trailer search/download/manual search
- legacy Trailer/Trailers handling
- Dry Run
- low-resolution local upgrades
- scheduler + cron
- new-item polling
- original-style MTDP Web UI

Still planned:

- TV/series support and re-enable the TV Shows UI
- richer persisted download/history data
- additional upstream features where they make sense for Emby
- Unraid Community Apps template

## Development

```bash
python -m unittest discover -s tests -v
```

The fork deliberately preserves the MTDP UI heritage while replacing Plex-specific server behavior with an Emby-native backend.
