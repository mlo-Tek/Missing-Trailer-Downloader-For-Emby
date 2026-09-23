# Missing Trailer Downloader for Emby (MTDE)

MTDE scans Emby movie libraries for titles without a **local trailer**, searches YouTube with `yt-dlp`, stores a trailer in Emby's supported `trailers/` subfolder, and refreshes the affected Emby item.

This repository is a public fork of [`netplexflix/Missing-Trailer-Downloader-For-Plex`](https://github.com/netplexflix/Missing-Trailer-Downloader-For-Plex), adapted for Emby with permission from the upstream project owner.

> **Status:** early `0.1.0` Emby port. Movies are implemented first. TV support and the richer upstream-style UI will follow.

## Current features

- Emby is the source of truth; Radarr/Sonarr are not required
- Multiple Emby movie libraries
- Detects local trailers using Emby's `LocalTrailerCount` plus a filesystem fallback
- Remote/online Emby trailers do **not** block downloading a local trailer
- YouTube search and download via `yt-dlp`
- Preferred search language
- Minimum/maximum trailer resolution
- Maximum trailer duration
- Genre exclusions
- MKV or MP4 output
- Emby-compatible `trailers/` folder next to the movie
- Refreshes only the affected Emby item after a successful download
- Emby-path -> container-path mappings for Docker/Unraid
- Web UI on port `2121`
- Dry-run and connection-test CLI modes
- Docker/Unraid-friendly PUID/PGID support

## Trailer layout

For a movie such as:

```text
/media/movies/300 (2006)/300 (2006).mkv
```

MTDE writes:

```text
/media/movies/300 (2006)/
├── 300 (2006).mkv
└── trailers/
    └── 300 (2006) - Trailer.mkv
```

The lowercase `trailers` folder is intentional and is supported by Emby.

## Emby API key

Create a dedicated API key in the Emby Server dashboard under **Advanced -> Security**.

MTDE uses Emby's REST API for library discovery, movie metadata, local-trailer state, and item refreshes.

## Configuration

Copy the example configuration:

```bash
cp config/config.example.yml config/config.yml
```

Minimum configuration:

```yaml
EMBY_URL: "http://emby:8096"
EMBY_API_KEY: "CHANGE_ME"

MOVIE_LIBRARIES:
  - "Movies"

PREFERRED_LANGUAGE: "german deutsch"
TRAILER_FOLDER: "trailers"
TRAILER_FILE_FORMAT: "mkv"
TRAILER_RESOLUTION_MIN: 1080
TRAILER_RESOLUTION_MAX: 2160
```

### Path mappings

The filesystem path returned by Emby may differ from the path visible inside the MTDE container.

Example: Emby reports:

```text
/data/media/movies/300 (2006)/300 (2006).mkv
```

but MTDE has the host media mounted as `/media`. Configure:

```yaml
PATH_MAPPINGS:
  - emby: "/data/media"
    local: "/media"
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

Then open:

```text
http://SERVER-IP:2121
```

## CLI

Test Emby connectivity:

```bash
mtde --config /config/config.yml --test
```

Dry-run without writing files:

```bash
mtde --config /config/config.yml --dry-run
```

Scan and download:

```bash
mtde --config /config/config.yml --scan
```

## Safety behavior

MTDE `0.1.x` does not delete or replace existing trailers. A movie is skipped when Emby reports a local trailer or when a supported video file already exists in the configured `trailers/` folder.

## Roadmap

- TV/series trailers
- Upgrade/replacement logic for low-resolution trailers
- Better manual search and candidate selection in the Web UI
- Download history/statistics
- Scheduled scans
- Emby new-item event/polling support
- More of the original MTDP Web UI functionality, adapted to Emby

## Development

```bash
python -m unittest discover -s tests -v
```

The initial Emby port keeps the upstream fork relationship and project inspiration while replacing the Plex-specific server integration with an Emby-native API layer.
