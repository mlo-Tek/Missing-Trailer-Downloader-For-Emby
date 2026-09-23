# Unraid installation

MTDE is not in Community Apps yet. Install it as a normal Docker container using the GHCR image.

## 1. Create appdata and configuration

```bash
mkdir -p /mnt/cache/appdata/mtde
cat > /mnt/cache/appdata/mtde/config.yml <<'EOF'
EMBY_URL: "http://EMBY-IP:8096"
EMBY_API_KEY: "CHANGE_ME"
EMBY_TIMEOUT: 120

MOVIE_LIBRARIES:
  - name: "Movies"
    genres_to_skip: []

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

SCHEDULE_TYPE: "disabled"
SCHEDULE_HOURS: 24
SCHEDULE_CRON: "0 */6 * * *"
NEW_ITEM_DETECTION: false
NEW_ITEM_DELAY: 60

WEB_PORT: 2121
PATH_MAPPINGS: []
EOF
```

Replace `EMBY-IP`, `CHANGE_ME` and the library names.

## 2. Add the Docker container

For an Unraid setup where Emby already sees the media under `/data/media`, give MTDE the same path. This avoids unnecessary path translation.

In **Docker -> Add Container** use:

| Field | Value |
| --- | --- |
| Name | `MTDE` |
| Repository | `ghcr.io/mlo-tek/missing-trailer-downloader-for-emby:latest` |
| WebUI | `http://[IP]:[PORT:2121]/` |
| Container Port | `2121` |
| Config container path | `/config` |
| Config host path | `/mnt/cache/appdata/mtde` |
| Media container path | `/data/media` |
| Media host path | `/mnt/user/data/media` |
| `PUID` | `99` |
| `PGID` | `100` |
| `TZ` | `Europe/Berlin` |

The media mapping must be **read/write** after Dry Run is disabled.

When using a custom Unraid network with a dedicated container IP, the WebUI is simply:

```text
http://CONTAINER-IP:2121
```

When using normal bridge networking, map host port `2121` to container port `2121`.

## 3. First run: Dry Run

Keep:

```yaml
DRY_RUN: true
```

Start the container and open the Web UI. Run a scan. MTDE can read Emby and search YouTube but does not create, download, replace or delete trailer files and does not refresh Emby metadata.

Existing MTDP folders are safe. MTDE recognizes these names case-insensitively:

```text
Trailer
Trailers
trailer
trailers
```

An empty legacy trailer folder is not an error. A folder containing a supported video file counts as an existing local trailer. Existing plural `Trailers`/`trailers` directories are reused for later downloads.

## 4. Enable downloads

After reviewing the Dry Run results, either change the switch in the Web UI or set:

```yaml
DRY_RUN: false
```

The Web UI writes settings back to `/config/config.yml`, so a manual container restart is not normally required after saving settings there.

## Path mappings

If both Emby and MTDE see media as `/data/media`, keep:

```yaml
PATH_MAPPINGS: []
```

Only use a mapping when Emby and MTDE genuinely have different internal paths. Example:

```yaml
PATH_MAPPINGS:
  - emby: "/data/media"
    local: "/media"
```

If scan results show `path_missing`, compare the path reported by Emby with the path mounted inside MTDE before disabling Dry Run.
