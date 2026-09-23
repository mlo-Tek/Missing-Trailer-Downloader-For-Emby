from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import os
import threading
import time

from croniter import croniter
from flask import Flask, Response, jsonify, render_template, request, send_file
import yaml

from . import __version__
from .config import Settings
from .emby import EmbyClient
from .service import MTDE


LANGUAGE_OPTIONS = [
    ("original", "Original"),
    ("english", "English"),
    ("german", "German"),
    ("french", "French"),
    ("spanish", "Spanish"),
    ("italian", "Italian"),
    ("japanese", "Japanese"),
    ("korean", "Korean"),
    ("portuguese", "Portuguese"),
    ("russian", "Russian"),
    ("chinese", "Chinese"),
]

RESOLUTION_OPTIONS = [
    {"value": 480, "label": "480p"},
    {"value": 576, "label": "576p"},
    {"value": 720, "label": "720p"},
    {"value": 1080, "label": "1080p"},
    {"value": 1440, "label": "1440p"},
    {"value": 2160, "label": "2160p (4K)"},
]


def create_app(service: MTDE) -> Flask:
    app = Flask(__name__)
    state = {
        "running": False,
        "last_run": None,
        "results": [],
        "dry_run": service.settings.dry_run,
        "download_trailers": service.settings.download_trailers,
        "error_message": "",
        "log_lines": [],
        "movies": [],
        "cache_at": 0.0,
        "last_refreshed": None,
        "scheduler_paused": False,
        "scheduler_next": None,
        "scheduler_signature": None,
        "watcher": {
            "enabled": False,
            "connected": False,
            "pending": 0,
            "error": "",
        },
    }
    scan_lock = threading.Lock()
    cache_lock = threading.Lock()
    watcher_seen: set[str] = set()
    watcher_pending: dict[str, float] = {}
    watcher_initialized = False

    def add_log(line: str) -> None:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        state["log_lines"].append(f"{stamp} | {line}")
        state["log_lines"] = state["log_lines"][-3000:]

    def invalidate_cache() -> None:
        state["cache_at"] = 0.0

    def load_movies(force: bool = False) -> list[dict]:
        now = time.monotonic()
        if not force and state["movies"] and now - float(state["cache_at"]) < 30:
            return list(state["movies"])
        with cache_lock:
            now = time.monotonic()
            if not force and state["movies"] and now - float(state["cache_at"]) < 30:
                return list(state["movies"])
            items = service.list_movies_ui()
            state["movies"] = items
            state["cache_at"] = now
            state["last_refreshed"] = datetime.now().isoformat(timespec="seconds")
            return list(items)

    def run_scan(download: bool) -> None:
        with scan_lock:
            if state["running"]:
                return
            state["running"] = True
        state["error_message"] = ""
        add_log("Starting movie scan" + (" (DRY RUN)" if service.settings.dry_run else ""))
        try:
            results = service.scan(download=download)
            state["results"] = service.serialize(results)
            for result in results:
                info = f" | {result.message}" if result.message else ""
                add_log(f"{result.status.upper():18} | {result.library} | {result.title}{info}")
            state["last_run"] = datetime.now().isoformat(timespec="seconds")
            invalidate_cache()
            add_log(f"Completed scan: {len(results)} movie(s) checked")
        except Exception as exc:
            state["error_message"] = str(exc)
            add_log(f"ERROR | scan failed: {exc}")
        finally:
            state["running"] = False

    def start_scan(download: bool = True) -> bool:
        if state["running"]:
            return False
        threading.Thread(target=run_scan, args=(download,), daemon=True).start()
        return True

    def schedule_signature() -> tuple:
        s = service.settings
        return (s.schedule_type, s.schedule_hours, s.schedule_cron, state["scheduler_paused"])

    def next_scheduled(after: datetime) -> datetime | None:
        s = service.settings
        if state["scheduler_paused"] or s.schedule_type == "disabled":
            return None
        if s.schedule_type == "hours":
            return after + timedelta(hours=s.schedule_hours)
        if s.schedule_type == "cron":
            return croniter(s.schedule_cron, after).get_next(datetime)
        return None

    def scheduler_loop() -> None:
        while True:
            try:
                sig = schedule_signature()
                if sig != state["scheduler_signature"]:
                    state["scheduler_signature"] = sig
                    state["scheduler_next"] = next_scheduled(datetime.now())
                nxt = state["scheduler_next"]
                if nxt and datetime.now() >= nxt:
                    if start_scan(True):
                        add_log("Scheduled scan triggered")
                    state["scheduler_next"] = next_scheduled(datetime.now())
            except Exception as exc:
                add_log(f"ERROR | scheduler: {exc}")
                state["scheduler_next"] = None
            time.sleep(1)

    def watcher_loop() -> None:
        nonlocal watcher_initialized
        while True:
            s = service.settings
            if not s.new_item_detection:
                state["watcher"] = {
                    "enabled": False,
                    "connected": False,
                    "pending": 0,
                    "error": "",
                }
                watcher_seen.clear()
                watcher_pending.clear()
                watcher_initialized = False
                time.sleep(5)
                continue

            state["watcher"]["enabled"] = True
            try:
                current: set[str] = set()
                for library in s.movie_libraries:
                    current.update(movie.id for movie in service.emby.recent_movies(library, limit=50))

                if not watcher_initialized:
                    watcher_seen.update(current)
                    watcher_initialized = True
                else:
                    now_ts = time.time()
                    for item_id in current - watcher_seen:
                        watcher_pending[item_id] = now_ts + s.new_item_delay
                    watcher_seen.update(current)

                    due = [item_id for item_id, due_at in watcher_pending.items() if due_at <= now_ts]
                    if due and not state["running"]:
                        if start_scan(True):
                            add_log(f"New-item detection triggered scan for {len(due)} new movie(s)")
                        for item_id in due:
                            watcher_pending.pop(item_id, None)

                state["watcher"].update({
                    "connected": True,
                    "pending": len(watcher_pending),
                    "error": "",
                })
            except Exception as exc:
                state["watcher"].update({
                    "connected": False,
                    "pending": len(watcher_pending),
                    "error": str(exc),
                })
            time.sleep(15)

    threading.Thread(target=scheduler_loop, daemon=True).start()
    threading.Thread(target=watcher_loop, daemon=True).start()

    def patched_index() -> str:
        html = render_template("index.html", version=__version__)
        html = html.replace(
            "netplexflix/Missing-Trailer-Downloader-For-Plex",
            "mlo-Tek/Missing-Trailer-Downloader-For-Emby",
        )
        html = html.replace("MTDP", "MTDE")
        html = html.replace("Plex Pass", "Remote Trailer")
        html = html.replace("PLEX_", "EMBY_")
        html = html.replace("CHECK_EMBY_PASS_TRAILERS", "CHECK_REMOTE_TRAILERS")
        html = html.replace("/api/test/plex", "/api/test/emby")
        html = html.replace("/api/plex/poster/", "/api/emby/poster/")
        html = html.replace("plex_logo.png", "emby_logo.svg")
        html = html.replace("Plex", "Emby")
        html = html.replace(">Run Now</button>", ">Run Scan</button>")

        # The upstream UI injects Plex/MTDfP label maintenance controls into
        # General. MTDE does not use labels at all, so disable that block.
        html = html.replace(
            "if (section === 'General') {",
            "if (false && section === 'General') {",
            1,
        )

        extra_css = """
<style id="mtde-emby-port-overrides">
a[data-page="tvshows"], #page-tvshows { display:none !important; }
#section-coverage .donut-card:nth-child(3) { display:none !important; }
#section-coverage .donut-row { grid-template-columns:1fr 1fr !important; }
.mtde-port-note {
    background:rgba(167,139,250,.10);border:1px solid var(--border);
    border-left:3px solid var(--accent);border-radius:var(--radius);
    padding:10px 14px;margin-bottom:18px;font-size:13px;color:var(--text-secondary)
}
.mtde-port-note strong { color:var(--text-primary); }
.mtde-port-note.dry { border-left-color:var(--warning);background:rgba(210,153,34,.08); }
</style>
"""
        banner = (
            '<div class="mtde-port-note dry"><strong>DRY RUN is active.</strong> '
            'Scanning and YouTube searches are allowed, but MTDE will not create, '
            'delete or download trailer files and will not refresh Emby metadata.</div>'
            if service.settings.dry_run
            else '<div class="mtde-port-note"><strong>Emby port:</strong> Movies are enabled. '
                 'TV support is still being ported from upstream MTDP.</div>'
        )
        html = html.replace("</style>\n</head>", "</style>" + extra_css + "\n</head>", 1)
        html = html.replace(
            "<!-- Recently Downloaded Trailers -->",
            banner + "\n<!-- Recently Downloaded Trailers -->",
            1,
        )
        helper_js = """
<script>
(function(){
  function cleanUnsupported(){
    document.querySelectorAll('.settings-section').forEach(section => {
      const h = section.querySelector('h2');
      if (h && h.textContent.trim().startsWith('TV Show Libraries')) section.style.display='none';
    });
    ['btn-remove-labels','btn-reset-upgrades'].forEach(id => {
      const el=document.getElementById(id);
      if (el && el.closest('.setting-item')) el.closest('.setting-item').remove();
    });
  }
  const observer = new MutationObserver(cleanUnsupported);
  observer.observe(document.documentElement,{childList:true,subtree:true});
  cleanUnsupported();
})();
</script>
"""
        return html.replace("</body>", helper_js + "\n</body>")

    @app.get("/")
    def index():
        return patched_index()

    @app.get("/api/auth/status")
    def auth_status():
        return jsonify({"setup_required": False, "authenticated": True})

    @app.post("/api/auth/login")
    @app.post("/api/auth/logout")
    @app.post("/api/auth/setup")
    def auth_noop():
        return jsonify({"ok": True})

    @app.get("/api/status")
    def status():
        state["dry_run"] = service.settings.dry_run
        state["download_trailers"] = service.settings.download_trailers
        status_name = "running" if state["running"] else ("error" if state["error_message"] else ("stopped" if state["scheduler_paused"] else "idle"))
        nxt = state["scheduler_next"]
        seconds = max(0, int((nxt - datetime.now()).total_seconds())) if nxt else None
        return jsonify({
            "status": status_name,
            "error_message": state["error_message"],
            "has_schedule": service.settings.schedule_type != "disabled",
            "schedule_type": service.settings.schedule_type,
            "next_run_seconds": seconds,
            "next_run_time": nxt.isoformat(timespec="seconds") if nxt else None,
            "last_run_time": state["last_run"],
            "last_refreshed": state["last_refreshed"],
            "dry_run": service.settings.dry_run,
            "download_trailers": service.settings.download_trailers,
            "watcher": dict(state["watcher"]),
            "cache_progress": {"refreshing": False},
            "scan_progress": {"scanning": state["running"]},
        })

    @app.get("/api/server")
    def server():
        try:
            info = service.test_connection()
            return jsonify({"ok": True, "name": info.get("ServerName"), "version": info.get("Version")})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 502

    @app.post("/api/scan")
    @app.post("/api/scheduler/run-now")
    def scan():
        requested_download = request.args.get("download", "true").lower() not in {"0", "false", "no"}
        if not start_scan(requested_download):
            return jsonify({"ok": False, "error": "scan already running"}), 409
        return jsonify({
            "ok": True,
            "requested_download": requested_download,
            "effective_download": requested_download and service.settings.download_trailers and not service.settings.dry_run,
            "dry_run": service.settings.dry_run,
        }), 202

    @app.post("/api/scheduler/stop")
    def scheduler_stop():
        state["scheduler_paused"] = True
        state["scheduler_signature"] = None
        state["scheduler_next"] = None
        return jsonify({"ok": True})

    @app.post("/api/scheduler/start")
    def scheduler_start():
        state["scheduler_paused"] = False
        state["scheduler_signature"] = None
        return jsonify({"ok": True})

    @app.get("/api/update")
    def update_status():
        return jsonify({"status": "up_to_date", "latest": __version__})

    def setting(key: str, label: str, section: str, kind: str, value, description: str = "", **extra):
        data = {
            "key": key,
            "label": label,
            "section": section,
            "type": kind,
            "value": value,
            "description": description,
        }
        data.update(extra)
        return data

    @app.get("/api/config/settings")
    def get_settings():
        s = service.settings
        options = [
            setting(
                "DRY_RUN", "Dry Run", "General", "bool", s.dry_run,
                "Global safety switch. No trailer writes/deletions and no Emby refreshes.",
            ),

            setting("EMBY_URL", "Emby URL", "Emby Connection", "string", s.emby_url),
            setting("EMBY_API_KEY", "Emby API Key", "Emby Connection", "string", s.emby_api_key, sensitive=True),
            setting(
                "EMBY_TIMEOUT", "Emby Timeout (seconds)", "Emby Connection", "number", s.emby_timeout,
                "HTTP timeout for Emby API calls.", min=5,
            ),

            setting(
                "CHECK_REMOTE_TRAILERS", "Check Remote Trailers", "Trailer Settings", "bool",
                s.check_remote_trailers,
                "When enabled, an Emby remote/online trailer counts as covered and MTDE will not download a local trailer.",
            ),
            setting(
                "DOWNLOAD_TRAILERS", "Download Trailers", "Trailer Settings", "bool",
                s.download_trailers,
                "Allow automatic and manual local trailer downloads when Dry Run is off.",
            ),
            setting(
                "PREFERRED_LANGUAGE", "Preferred Language", "Trailer Settings", "select",
                s.preferred_language,
                "Preferred language terms used for YouTube trailer searches.",
                options=[{"value": value, "label": label} for value, label in LANGUAGE_OPTIONS],
            ),
            setting(
                "REFRESH_EMBY_AFTER_DOWNLOAD", "Refresh Emby After Download", "Trailer Settings", "bool",
                s.refresh_emby_after_download,
                "Refresh only the affected Emby item after a successful trailer download or deletion.",
            ),
            setting(
                "SHOW_YT_DLP_PROGRESS", "Show yt-dlp Progress", "Trailer Settings", "bool",
                s.show_ytdlp_progress,
                "Show yt-dlp warnings/progress in the container log.",
            ),
            setting(
                "TRAILER_FILE_FORMAT", "Trailer File Format", "Trailer Settings", "select",
                s.trailer_file_format,
                options=[{"value": "mkv", "label": "MKV"}, {"value": "mp4", "label": "MP4"}],
            ),
            setting(
                "TRAILER_RESOLUTION_MAX", "Maximum Trailer Resolution", "Trailer Settings", "select",
                s.trailer_resolution_max, options=RESOLUTION_OPTIONS,
            ),
            setting(
                "TRAILER_RESOLUTION_MIN", "Minimum Trailer Resolution", "Trailer Settings", "select",
                s.trailer_resolution_min, options=RESOLUTION_OPTIONS,
            ),
            setting(
                "MAX_TRAILER_DURATION", "Maximum Trailer Duration (seconds)", "Trailer Settings", "number",
                s.max_trailer_duration, min=1,
            ),
            setting(
                "SEARCH_RESULTS", "YouTube Search Results", "Trailer Settings", "number",
                s.search_results, "How many results to inspect per search query.", min=1,
            ),
            setting(
                "TRAILER_FOLDER", "Trailer Folder", "Trailer Settings", "string",
                s.trailer_folder,
                "Folder name beside the movie file. Existing Trailer/Trailers variants are detected case-insensitively.",
            ),
            setting(
                "COOKIES_FILE", "Cookies File", "Trailer Settings", "string",
                s.cookies_file or "",
                "Optional Netscape-format cookies file path, e.g. /cookies/cookies.txt.",
            ),
            setting(
                "UPGRADE_TRAILERS", "Upgrade Low-Resolution Trailers", "Trailer Settings", "select",
                s.upgrade_trailers,
                "When enabled, local trailers below the configured minimum resolution are replaced only after a better download succeeds.",
                options=[
                    {"value": "off", "label": "Off"},
                    {"value": "local", "label": "Local trailers"},
                ],
            ),

            setting(
                "YT_DLP_CUSTOM_OPTIONS", "yt-dlp Custom Options", "YT-DLP Custom Options", "string_list",
                s.yt_dlp_custom_options,
                "Optional yt-dlp CLI-style options. MTDE blocks options that would override output paths, safety or format selection.",
            ),

            setting(
                "SCHEDULE_TYPE", "Schedule Type", "Scheduler", "select", s.schedule_type,
                "Choose an interval, cron expression, or disable scheduled scans.",
                options=[
                    {"value": "hours", "label": "Every X hours"},
                    {"value": "cron", "label": "Cron expression"},
                    {"value": "disabled", "label": "Disabled"},
                ],
            ),
            setting(
                "SCHEDULE_HOURS", "Hours Interval", "Scheduler", "number", s.schedule_hours,
                "Run every X hours when Schedule Type is Every X hours.", min=1,
            ),
            setting(
                "SCHEDULE_CRON", "Cron Expression", "Scheduler", "string", s.schedule_cron,
                "Standard 5-field cron expression.",
            ),
            setting(
                "NEW_ITEM_DETECTION", "New Item Detection", "Scheduler", "bool", s.new_item_detection,
                "Poll Emby for newly added movies and trigger a scan after the configured delay.",
            ),
            setting(
                "NEW_ITEM_DELAY", "Detection Delay (seconds)", "Scheduler", "number", s.new_item_delay,
                "Wait after detecting a new Emby movie before starting the scan.", min=0,
            ),
        ]
        libraries = {
            "movie": [
                {"name": name, "genres_to_skip": s.genres_for_library(name)}
                for name in s.movie_libraries
            ],
            "tv": [],
        }
        return jsonify({"options": options, "libraries": libraries})

    @app.post("/api/config/settings")
    def save_settings():
        payload = request.get_json(silent=True) or {}
        options = payload.get("options") or {}
        libraries = payload.get("libraries") or {}
        config_path = Path(os.environ.get("MTDE_CONFIG", "/config/config.yml"))
        try:
            raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            allowed = {
                "DRY_RUN", "EMBY_URL", "EMBY_API_KEY", "EMBY_TIMEOUT",
                "CHECK_REMOTE_TRAILERS", "DOWNLOAD_TRAILERS", "PREFERRED_LANGUAGE",
                "REFRESH_EMBY_AFTER_DOWNLOAD", "SHOW_YT_DLP_PROGRESS",
                "TRAILER_FILE_FORMAT", "TRAILER_RESOLUTION_MIN", "TRAILER_RESOLUTION_MAX",
                "MAX_TRAILER_DURATION", "SEARCH_RESULTS", "TRAILER_FOLDER", "COOKIES_FILE",
                "UPGRADE_TRAILERS", "YT_DLP_CUSTOM_OPTIONS", "SCHEDULE_TYPE", "SCHEDULE_HOURS",
                "SCHEDULE_CRON", "NEW_ITEM_DETECTION", "NEW_ITEM_DELAY",
            }
            for key in allowed:
                if key in options:
                    raw[key] = options[key]

            movie_libs = libraries.get("movie") or []
            normalized_libs = []
            for lib in movie_libs:
                name = str(lib.get("name") or "").strip()
                if not name:
                    continue
                normalized_libs.append({
                    "name": name,
                    "genres_to_skip": [
                        str(genre).strip()
                        for genre in (lib.get("genres_to_skip") or [])
                        if str(genre).strip()
                    ],
                })
            if normalized_libs:
                raw["MOVIE_LIBRARIES"] = normalized_libs
            raw.pop("SKIP_GENRES", None)

            tmp = config_path.with_suffix(config_path.suffix + ".tmp")
            tmp.write_text(
                yaml.safe_dump(raw, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            new_settings = Settings.from_yaml(tmp)
            tmp.replace(config_path)
            service.update_settings(new_settings)
            state["dry_run"] = new_settings.dry_run
            state["download_trailers"] = new_settings.download_trailers
            state["error_message"] = ""
            state["scheduler_signature"] = None
            invalidate_cache()
            add_log("Settings saved and reloaded")
            return jsonify({"ok": True})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.post("/api/test/emby")
    def test_emby():
        payload = request.get_json(silent=True) or {}
        url = str(payload.get("EMBY_URL") or service.settings.emby_url)
        key = str(payload.get("EMBY_API_KEY") or service.settings.emby_api_key)
        timeout = int(payload.get("EMBY_TIMEOUT") or service.settings.emby_timeout)
        try:
            info = EmbyClient(url, key, timeout=timeout).system_info()
            return jsonify({
                "success": True,
                "message": f"Connected to {info.get('ServerName', 'Emby')} {info.get('Version', '')}",
            })
        except Exception as exc:
            return jsonify({"success": False, "message": str(exc)}), 400

    @app.get("/api/library/movies")
    def library_movies():
        try:
            force = request.args.get("refresh", "false").lower() in {"1", "true", "yes"}
            items = load_movies(force=force)
            sort = request.args.get("sort", "title")
            if sort == "added":
                items.sort(key=lambda x: x.get("dateAdded") or "", reverse=True)
            else:
                items.sort(key=lambda x: (x.get("title") or "").casefold())
            genres = {
                name: service.settings.genres_for_library(name)
                for name in service.settings.movie_libraries
            }
            return jsonify({"loading": False, "items": items, "genresToSkip": genres})
        except Exception as exc:
            add_log(f"ERROR | library load failed: {exc}")
            return jsonify({"loading": False, "items": [], "genresToSkip": {}, "error": str(exc)}), 500

    @app.get("/api/library/tvshows")
    def library_tvshows():
        return jsonify({"loading": False, "items": [], "genresToSkip": {}})

    @app.get("/api/library/item/<item_id>")
    def library_item(item_id: str):
        try:
            return jsonify(service.item_detail_ui(item_id))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 404

    @app.get("/api/emby/poster/<item_id>")
    def emby_poster(item_id: str):
        try:
            r = service.emby.fetch_primary_image(item_id)
            if not r.ok:
                return Response(status=r.status_code)
            return Response(r.content, content_type=r.headers.get("Content-Type", "image/jpeg"))
        except Exception:
            return Response(status=404)

    @app.post("/api/search/trailer")
    def search_trailer():
        payload = request.get_json(silent=True) or {}
        title = str(payload.get("title") or "").strip()
        year = payload.get("year")
        if not title:
            return jsonify({"results": [], "has_more": False, "error": "title is required"}), 400
        try:
            candidates = service.downloader.search(title, int(year) if str(year).isdigit() else None)
            results = []
            for candidate in candidates:
                duration = candidate.duration or 0
                results.append({
                    "url": candidate.url,
                    "title": candidate.title,
                    "duration": candidate.duration,
                    "duration_str": f"{duration // 60}:{duration % 60:02d}" if candidate.duration is not None else "",
                    "channel": candidate.channel or "",
                    "thumbnail": candidate.thumbnail or "",
                    "resolution": f"{candidate.height}p" if candidate.height else "",
                    "view_count": candidate.view_count or 0,
                })
            return jsonify({"results": results, "has_more": False})
        except Exception as exc:
            return jsonify({"results": [], "has_more": False, "error": str(exc)}), 500

    @app.post("/api/download/trailer")
    def download_trailer():
        payload = request.get_json(silent=True) or {}
        item_id = str(payload.get("ratingKey") or "")
        url = str(payload.get("url") or "")
        if not item_id or not url:
            return jsonify({"ok": False, "error": "ratingKey and url are required"}), 400
        try:
            path = service.download_manual(
                item_id,
                url,
                str(payload.get("title") or ""),
                ignore_minimum=bool(payload.get("skipQualityMin", False)),
            )
            invalidate_cache()
            add_log(f"DOWNLOADED | item {item_id} | {path}")
            return jsonify({"ok": True, "path": str(path)})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409

    @app.post("/api/trailer/delete")
    def delete_trailer():
        payload = request.get_json(silent=True) or {}
        try:
            service.delete_local_trailer(
                str(payload.get("ratingKey") or ""),
                str(payload.get("trailerFile") or ""),
            )
            invalidate_cache()
            add_log(f"DELETED | {payload.get('trailerFile')}")
            return jsonify({"ok": True})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409

    @app.get("/api/trailer/stream")
    def trailer_stream():
        requested = str(request.args.get("path") or "")
        try:
            allowed = {
                str(item.get("trailerFile") or "")
                for item in load_movies()
                if item.get("trailerFile")
            }
            if requested not in allowed:
                return Response(status=403)
            path = Path(requested)
            if not path.is_file():
                return Response(status=404)
            return send_file(path, conditional=True)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 404

    @app.get("/api/dashboard/services")
    def dashboard_services():
        services = []
        started = time.perf_counter()
        try:
            info = service.test_connection()
            elapsed = int((time.perf_counter() - started) * 1000)
            services.append({
                "service": "plex",
                "name": "Emby",
                "online": True,
                "version": str(info.get("Version") or ""),
                "responseTime": elapsed,
            })
        except Exception as exc:
            services.append({
                "service": "plex",
                "name": "Emby",
                "online": False,
                "message": str(exc),
            })
        try:
            import yt_dlp
            services.append({
                "service": "ytdlp",
                "name": "yt-dlp",
                "online": True,
                "version": yt_dlp.version.__version__,
                "updateAvailable": False,
            })
        except Exception as exc:
            services.append({
                "service": "ytdlp",
                "name": "yt-dlp",
                "online": False,
                "message": str(exc),
            })
        return jsonify(services)

    def movie_stats():
        items = load_movies()
        total = len(items)
        local = sum(1 for x in items if x["trailerStatus"] == "local")
        remote = sum(1 for x in items if x["trailerStatus"] == "plexpass")
        skipped = sum(1 for x in items if x.get("genreSkipped"))
        missing = sum(1 for x in items if x["trailerStatus"] == "missing" and not x.get("genreSkipped"))
        disk = 0
        for item in items:
            path = item.get("trailerFile")
            if path:
                try:
                    disk += Path(path).stat().st_size
                except OSError:
                    pass
        return items, total, local, remote, missing, skipped, disk

    @app.get("/api/dashboard/stats")
    def dashboard_stats():
        try:
            _, total, local, remote, missing, skipped, disk = movie_stats()
            return jsonify({
                "total_movies": total,
                "movies_local_trailers": local,
                "movies_plexpass_trailers": remote,
                "movies_missing_trailers": missing,
                "movies_skipped_genres": skipped,
                "movies_disk_bytes": disk,
                "total_shows": 0,
                "shows_local_trailers": 0,
                "shows_plexpass_trailers": 0,
                "shows_missing_trailers": 0,
                "shows_skipped_genres": 0,
                "shows_disk_bytes": 0,
            })
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.get("/api/dashboard/breakdowns")
    def dashboard_breakdowns():
        try:
            items, _, _, _, _, _, _ = movie_stats()
            libraries = []
            for name in service.settings.movie_libraries:
                subset = [item for item in items if item.get("library") == name]
                libraries.append({
                    "name": name,
                    "type": "movie",
                    "total": len(subset),
                    "local": sum(1 for x in subset if x["trailerStatus"] == "local"),
                    "plexpass": sum(1 for x in subset if x["trailerStatus"] == "plexpass"),
                    "missing": sum(1 for x in subset if x["trailerStatus"] == "missing" and not x.get("genreSkipped")),
                    "skipped": sum(1 for x in subset if x.get("genreSkipped")),
                })

            resolution: dict[str, int] = {}
            for item in items:
                if item["trailerStatus"] == "local" and item.get("trailerResolution"):
                    key = item["trailerResolution"]
                    resolution[key] = resolution.get(key, 0) + 1

            return jsonify({
                "resolution": resolution,
                "resolution_plexpass": {},
                "language": {},
                "libraries": libraries,
            })
        except Exception as exc:
            return jsonify({
                "error": str(exc),
                "resolution": {},
                "resolution_plexpass": {},
                "language": {},
                "libraries": [],
            }), 500

    @app.get("/api/dashboard/recent-trailers")
    def recent_trailers():
        try:
            recent = []
            for item in load_movies():
                path_text = item.get("trailerFile")
                if not path_text:
                    continue
                try:
                    mtime = Path(path_text).stat().st_mtime
                except OSError:
                    continue
                recent.append((mtime, {
                    "title": item.get("title") or "",
                    "year": item.get("year"),
                    "media_type": "movie",
                    "downloaded_at": datetime.fromtimestamp(mtime).isoformat(),
                    "plex_rating_key": item.get("ratingKey"),
                    "poster_url": "",
                }))
            recent.sort(key=lambda x: x[0], reverse=True)
            return jsonify({"items": [x[1] for x in recent[:20]]})
        except Exception as exc:
            return jsonify({"items": [], "error": str(exc)})

    @app.get("/api/log")
    def log():
        limit = max(1, min(int(request.args.get("limit", 1000)), 3000))
        return jsonify({"lines": state["log_lines"][-limit:]})

    @app.post("/api/ytdlp/update")
    def ytdlp_update():
        return jsonify({
            "ok": False,
            "error": "yt-dlp is managed by the MTDE container; update the container image instead.",
        }), 409

    # Kept only for old cached frontend JavaScript. MTDE does not use labels or
    # a persisted upgrade-attempt database.
    @app.post("/api/upgrade-attempts/reset")
    def reset_upgrade_attempts():
        return jsonify({"ok": True, "removed": 0})

    return app
