# Unraid installation

MTDE is not in Community Apps yet. Install it as a normal Docker container using the GHCR image.

## 1. Create the appdata directory and configuration

Open the Unraid terminal:

```bash
mkdir -p /mnt/cache/appdata/mtde
cat > /mnt/cache/appdata/mtde/config.yml <<'EOF'
EMBY_URL: "http://EMBY-IP:8096"
EMBY_API_KEY: "CHANGE_ME"

MOVIE_LIBRARIES:
  - "Movies"

# Safety switch. Keep this true for the first scan.
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

# Only needed when Emby reports a different path than MTDE sees.
# Example: Emby returns /data/media/... but MTDE mounts the same files as /media/...
PATH_MAPPINGS:
  - emby: "/data/media"
    local: "/media"
EOF
```

Replace `EMBY-IP`, `CHANGE_ME`, and the library names. If Emby already reports paths beginning with `/media`, remove the `PATH_MAPPINGS` block.

## 2. Add the Docker container

In **Docker -> Add Container** use:

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

The media mapping must be **read/write**, otherwise MTDE cannot create local trailer files once dry-run is disabled.

## 3. First run: dry-run

Keep this in `config.yml`:

```yaml
DRY_RUN: true
```

Start the container and open:

```text
http://UNRAID-IP:2121
```

Use **Dry-Run**. MTDE will scan Emby and search for candidates, but it will not create folders, download trailer files, delete/rename anything, or refresh Emby metadata.

Existing trailer folders created by MTDP are safe. MTDE recognizes `trailers`, `Trailers`, `trailer`, and `Trailer` when checking for existing local trailer files. Empty legacy folders are ignored without error. Existing plural `Trailers`/`trailers` folders are reused for downloads to avoid creating a duplicate folder with different capitalization.

## 4. Enable downloads

When the dry-run output looks correct, change:

```yaml
DRY_RUN: false
```

Restart the MTDE container. The **Fehlende Trailer laden** button is then enabled.

If results show `path_missing`, the Emby path and MTDE container path do not match. Fix `PATH_MAPPINGS` before disabling dry-run.
