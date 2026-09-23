from __future__ import annotations

from datetime import datetime
from pathlib import Path
import os
import threading
import time

from flask import Flask, Response, jsonify, render_template, request, send_file
import yaml

from . import __version__
from .config import Settings
from .emby import EmbyClient
from .service import MTDE


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
    }
    scan_lock = threading.Lock()
    cache_lock = threading.Lock()

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

    def start_scan(download: bool = True):
        if state["running"]:
            return False
        threading.Thread(target=run_scan, args=(download,), daemon=True).start()
        return True

    def patched_index() -> str:
        html = render_template("index.html", version=__version__)
        html = html.replace(
            "netplexflix/Missing-Trailer-Downloader-For-Plex",
            "mlo-Tek/Missing-Trailer-Downloader-For-Emby",
        )
        html = html.replace("MTDP", "MTDE")
        html = html.replace("Plex Pass", "Remote Trailer")
        html = html.replace("PLEX_", "EMBY_")
        html = html.replace("/api/test/plex", "/api/test/emby")
        html = html.replace("/api/plex/poster/", "/api/emby/poster/")
        html = html.replace("plex_logo.png", "emby_logo.svg")
        html = html.replace("Plex", "Emby")
        html = html.replace(">Run Now</button>", ">Run Scan</button>")

        extra_css = """
<style id="mtde-emby-port-overrides">
a[data-page="tvshows"], #page-tvshows { display:none !important; }
#section-coverage .donut-card:nth-child(3) { display:none !important; }
#section-coverage .donut-row { grid-template-columns:1fr 1fr !important; }
#btn-stop, #btn-start { display:none !important; }
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
  function hideUnsupportedSettings(){
    document.querySelectorAll('.settings-section').forEach(section => {
      const h = section.querySelector('h2');
      if (h && h.textContent.trim().startsWith('TV Show Libraries')) section.style.display='none';
    });
  }
  const observer = new MutationObserver(hideUnsupportedSettings);
  observer.observe(document.documentElement,{childList:true,subtree:true});
  hideUnsupportedSettings();
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
        status_name = "running" if state["running"] else ("error" if state["error_message"] else "idle")
        return jsonify({
            "status": status_name,
            "error_message": state["error_message"],
            "has_schedule": True,
            "schedule_type": "manual",
            "next_run_seconds": None,
            "next_run_time": None,
            "last_run_time": state["last_run"],
            "last_refreshed": state["last_refreshed"],
            "dry_run": service.settings.dry_run,
            "download_trailers": service.settings.download_trailers,
            "watcher": {"enabled": False, "connected": False, "pending": 0},
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
        return jsonify({"ok": False, "error": "An active MTDE scan cannot be interrupted yet"}), 409

    @app.post("/api/scheduler/start")
    def scheduler_start():
        return jsonify({"ok": True})

    @app.get("/api/update")
    def update_status():
        return jsonify({"status": "up_to_date", "latest": __version__})

    def setting(key: str, label: str, section: str, kind: str, value, description: str = "", **extra):
        data = {"key": key, "label": label, "section": section, "type": kind, "value": value, "description": description}
        data.update(extra)
        return data

    @app.get("/api/config/settings")
    def get_settings():
        s = service.settings
        options = [
            setting("DRY_RUN", "Dry Run", "General", "bool", s.dry_run, "Global safety switch. No media writes, deletions or Emby refreshes."),
            setting("DOWNLOAD_TRAILERS", "Download Trailers", "General", "bool", s.download_trailers, "Allow automatic/manual trailer downloads when Dry Run is off."),
            setting("EMBY_URL", "Emby URL", "Emby Connection", "string", s.emby_url),
            setting("EMBY_API_KEY", "Emby API Key", "Emby Connection", "string", s.emby_api_key, sensitive=True),
            setting("PREFERRED_LANGUAGE", "Preferred Language", "Trailer Search", "string", s.preferred_language),
            setting("SEARCH_RESULTS", "Search Results", "Trailer Search", "int", s.search_results),
            setting("MAX_TRAILER_DURATION", "Max Trailer Duration (seconds)", "Trailer Search", "int", s.max_trailer_duration),
            setting("TRAILER_RESOLUTION_MIN", "Minimum Resolution", "Output", "int", s.trailer_resolution_min),
            setting("TRAILER_RESOLUTION_MAX", "Maximum Resolution", "Output", "int", s.trailer_resolution_max),
            setting("TRAILER_FILE_FORMAT", "Trailer File Format", "Output", "select", s.trailer_file_format,
                    options=[{"value": "mkv", "label": "MKV"}, {"value": "mp4", "label": "MP4"}]),
            setting("TRAILER_FOLDER", "Trailer Folder", "Output", "string", s.trailer_folder),
            setting("REFRESH_EMBY_AFTER_DOWNLOAD", "Refresh Emby After Download", "Advanced", "bool", s.refresh_emby_after_download),
        ]
        libraries = {
            "movie": [{"name": name, "genres_to_skip": list(s.skip_genres)} for name in s.movie_libraries],
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
            for key in (
                "DRY_RUN", "DOWNLOAD_TRAILERS", "EMBY_URL", "EMBY_API_KEY",
                "PREFERRED_LANGUAGE", "SEARCH_RESULTS", "MAX_TRAILER_DURATION",
                "TRAILER_RESOLUTION_MIN", "TRAILER_RESOLUTION_MAX",
                "TRAILER_FILE_FORMAT", "TRAILER_FOLDER", "REFRESH_EMBY_AFTER_DOWNLOAD",
            ):
                if key in options:
                    raw[key] = options[key]
            movie_libs = libraries.get("movie") or []
            names = [str(x.get("name") or "").strip() for x in movie_libs if str(x.get("name") or "").strip()]
            if names:
                raw["MOVIE_LIBRARIES"] = names
            genres: list[str] = []
            for lib in movie_libs:
                for genre in lib.get("genres_to_skip") or []:
                    genre = str(genre).strip()
                    if genre and genre not in genres:
                        genres.append(genre)
            raw["SKIP_GENRES"] = genres

            tmp = config_path.with_suffix(config_path.suffix + ".tmp")
            tmp.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
            new_settings = Settings.from_yaml(tmp)
            tmp.replace(config_path)
            service.update_settings(new_settings)
            state["dry_run"] = new_settings.dry_run
            state["download_trailers"] = new_settings.download_trailers
            state["error_message"] = ""
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
        try:
            info = EmbyClient(url, key).system_info()
            return jsonify({"success": True, "message": f"Connected to {info.get('ServerName', 'Emby')} {info.get('Version', '')}"})
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
            genres = {name: list(service.settings.skip_genres) for name in service.settings.movie_libraries}
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
            return jsonify({"results": [], "has_more": False})
        try:
            candidates = service.downloader.search(title, int(year) if str(year).isdigit() else None)
            results = []
            for c in candidates:
                duration = c.duration or 0
                mins, secs = divmod(duration, 60)
                results.append({
                    "url": c.url,
                    "title": c.title,
                    "channel": c.channel or "",
                    "duration_str": f"{mins}:{secs:02d}" if duration else "",
                    "resolution": f"{c.height}p" if c.height else "",
                    "thumbnail": c.thumbnail or "",
                    "view_count": c.view_count or 0,
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
            return jsonify({"ok": False, "error": "Missing Emby item id or trailer URL"}), 400
        try:
            path = service.download_manual(item_id, url, str(payload.get("title") or ""))
            invalidate_cache()
            add_log(f"DOWNLOADED | item {item_id} | {path}")
            return jsonify({"ok": True, "path": str(path)})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409

    @app.post("/api/trailer/delete")
    def delete_trailer():
        payload = request.get_json(silent=True) or {}
        try:
            service.delete_local_trailer(str(payload.get("ratingKey") or ""), str(payload.get("trailerFile") or ""))
            invalidate_cache()
            add_log(f"DELETED | {payload.get('trailerFile')}")
            return jsonify({"ok": True})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409

    @app.get("/api/trailer/stream")
    def trailer_stream():
        requested = str(request.args.get("path") or "")
        try:
            allowed = {str(x.get("trailerFile") or "") for x in load_movies() if x.get("trailerFile")}
            if requested not in allowed:
                return jsonify({"error": "Trailer path is not part of the configured Emby libraries"}), 403
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
            services.append({"service": "plex", "name": "Emby", "online": True, "responseTime": elapsed, "version": info.get("Version")})
        except Exception as exc:
            services.append({"service": "plex", "name": "Emby", "online": False, "message": str(exc)})
        try:
            from yt_dlp.version import __version__ as ytdlp_version
            services.append({"service": "ytdlp", "name": "yt-dlp", "online": True, "version": ytdlp_version, "updateAvailable": False})
        except Exception as exc:
            services.append({"service": "ytdlp", "name": "yt-dlp", "online": False, "message": str(exc)})
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
                "total_shows": 0,
                "movies_local_trailers": local,
                "movies_plexpass_trailers": remote,
                "movies_missing_trailers": missing,
                "movies_skipped_genres": skipped,
                "movies_disk_bytes": disk,
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
                lib_items = [x for x in items if x.get("library") == name]
                libraries.append({
                    "name": name,
                    "type": "movie",
                    "total": len(lib_items),
                    "local": sum(1 for x in lib_items if x["trailerStatus"] == "local"),
                    "plexpass": sum(1 for x in lib_items if x["trailerStatus"] == "plexpass"),
                    "missing": sum(1 for x in lib_items if x["trailerStatus"] == "missing" and not x.get("genreSkipped")),
                    "skipped": sum(1 for x in lib_items if x.get("genreSkipped")),
                })
            return jsonify({"resolution": {}, "resolution_plexpass": {}, "language": {}, "libraries": libraries})
        except Exception as exc:
            return jsonify({"error": str(exc), "resolution": {}, "resolution_plexpass": {}, "language": {}, "libraries": []}), 500

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
                    "title": item.get("title"),
                    "year": item.get("year"),
                    "media_type": "movie",
                    "downloaded_at": datetime.fromtimestamp(mtime).isoformat(timespec="seconds"),
                    "plex_rating_key": item.get("ratingKey"),
                    "poster_url": f"/api/emby/poster/{item.get('ratingKey')}",
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
        return jsonify({"ok": False, "error": "Update the MTDE container to update yt-dlp"}), 409

    @app.post("/api/upgrade-attempts/reset")
    def reset_upgrade_attempts():
        return jsonify({"ok": True, "removed": 0})

    return app
