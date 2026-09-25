from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Iterator

import yaml
from flask import jsonify, request


_UI_CACHE_TTL_SECONDS = 1800


def _config_path() -> Path:
    return Path(os.environ.get("MTDE_CONFIG", "/config/config.yml"))


def _cache_root() -> Path:
    return _config_path().parent / "cache"


def _atomic_write_json(path: Path, payload: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def _parse_library_entries(raw_entries: Any, legacy_genres: list[str] | None = None) -> tuple[list[str], dict[str, list[str]]]:
    names: list[str] = []
    per_library: dict[str, list[str]] = {}
    fallback = list(legacy_genres or [])
    for entry in raw_entries or []:
        if isinstance(entry, dict):
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            names.append(name)
            per_library[name] = [str(x).strip() for x in (entry.get("genres_to_skip") or []) if str(x).strip()]
        else:
            name = str(entry or "").strip()
            if name:
                names.append(name)
                per_library[name] = list(fallback)
    return names, per_library


def _ensure_tv_settings(settings) -> None:
    if hasattr(settings, "tv_libraries") and hasattr(settings, "tv_genres_to_skip"):
        return
    raw = yaml.safe_load(_config_path().read_text(encoding="utf-8")) if _config_path().exists() else {}
    raw = raw or {}
    legacy = [str(x) for x in (raw.get("TV_GENRES_TO_SKIP") or [])]
    names, per_library = _parse_library_entries(raw.get("TV_LIBRARIES") or [], legacy)
    setattr(settings, "tv_libraries", names)
    setattr(settings, "tv_genres_to_skip", per_library)


def find_series_local_trailers(service, series) -> list[Path]:
    """Find series-level trailers using the upstream MTDP TV conventions.

    Series trailers may live in a Trailer/Trailers folder or directly in the
    series root as a file whose stem ends in '-trailer'.
    """
    from .hardening import is_partial_output_path
    from .trailer import VIDEO_EXTENSIONS, find_local_trailers

    mapped = Path(service.settings.map_path(series.path))
    series_dir = mapped if mapped.is_dir() else mapped.parent
    found = list(find_local_trailers(series_dir, service.settings.trailer_folder))
    seen = set(found)
    try:
        children = list(series_dir.iterdir())
    except OSError:
        children = []
    for path in children:
        try:
            valid = (
                path.is_file()
                and path.suffix.casefold() in VIDEO_EXTENSIONS
                and path.stem.casefold().endswith("-trailer")
                and not is_partial_output_path(path)
            )
        except OSError:
            valid = False
        if valid and path not in seen:
            seen.add(path)
            found.append(path)
    return sorted(found, key=lambda p: str(p).casefold())


def _install_settings_tv_support() -> None:
    from .config import Settings

    if getattr(Settings, "_mtde_tv_settings_installed", False):
        return

    original_from_yaml = Settings.from_yaml

    def from_yaml_with_tv(cls, path):
        settings = original_from_yaml(path)
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        legacy = [str(x) for x in (raw.get("TV_GENRES_TO_SKIP") or [])]
        names, per_library = _parse_library_entries(raw.get("TV_LIBRARIES") or [], legacy)
        setattr(settings, "tv_libraries", names)
        setattr(settings, "tv_genres_to_skip", per_library)
        return settings

    def genres_for_tv_library(self, name: str) -> list[str]:
        return list(getattr(self, "tv_genres_to_skip", {}).get(name, []))

    Settings.from_yaml = classmethod(from_yaml_with_tv)
    Settings.genres_for_tv_library = genres_for_tv_library
    Settings._mtde_tv_settings_installed = True


def _install_emby_series_support() -> None:
    from .emby import EmbyClient

    if getattr(EmbyClient, "_mtde_series_support_installed", False):
        return

    def iter_series(self, library_name: str, page_size: int = 500) -> Iterator:
        parent_id = self.resolve_library(library_name)
        start = 0
        while True:
            params = {
                "ParentId": parent_id,
                "Recursive": "true",
                "IncludeItemTypes": "Series",
                "Fields": self._fields(),
                "StartIndex": start,
                "Limit": page_size,
                "SortBy": "SortName",
                "SortOrder": "Ascending",
            }
            response = self.session.get(self._url("Items"), params=params, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
            items = payload.get("Items", [])
            for item in items:
                series = self._movie_from_item(item)
                if series.path:
                    yield series
            start += len(items)
            total = int(payload.get("TotalRecordCount") or len(items))
            if not items or start >= total:
                break

    EmbyClient.iter_series = iter_series
    EmbyClient._mtde_series_support_installed = True


def _probe_cache_path() -> Path:
    return _cache_root() / "probe-heights.json"


def _load_probe_cache(service) -> None:
    payload = _read_json(_probe_cache_path(), {})
    if not isinstance(payload, dict):
        return
    loaded: dict[str, tuple[int, int, int | None]] = {}
    for key, row in payload.items():
        if not isinstance(row, list) or len(row) != 3:
            continue
        try:
            stamp = int(row[0])
            size = int(row[1])
            height = None if row[2] is None else int(row[2])
        except (TypeError, ValueError):
            continue
        loaded[str(key)] = (stamp, size, height)
    with service._probe_cache_lock:
        service._probe_cache.update(loaded)


def _save_probe_cache(service) -> None:
    with service._probe_cache_lock:
        payload = {key: [value[0], value[1], value[2]] for key, value in service._probe_cache.items()}
    _atomic_write_json(_probe_cache_path(), payload)


def _install_service_ui_support() -> None:
    from .service import MTDE

    if getattr(MTDE, "_mtde_ui_tv_perf_installed", False):
        return

    original_init = MTDE.__init__
    original_movie_ui = MTDE.movie_ui
    original_list_movies_ui = MTDE.list_movies_ui
    original_scan = MTDE.scan

    def init_with_persistent_probe_cache(self, settings):
        original_init(self, settings)
        _load_probe_cache(self)

    def movie_ui_with_file_stats(self, library, movie):
        item = original_movie_ui(self, library, movie)
        path_text = str(item.get("trailerFile") or "")
        if path_text:
            try:
                stat = Path(path_text).stat()
                item["trailerSize"] = int(stat.st_size)
                item["trailerMtime"] = float(stat.st_mtime)
            except OSError:
                item["trailerSize"] = 0
                item["trailerMtime"] = 0.0
        else:
            item["trailerSize"] = 0
            item["trailerMtime"] = 0.0
        return item

    def list_movies_ui_with_persisted_probes(self, *args, **kwargs):
        items = original_list_movies_ui(self, *args, **kwargs)
        _save_probe_cache(self)
        return items

    def series_ui(self, library, series):
        local_files = find_series_local_trailers(self, series)
        stale_emby_local = series.local_trailer_count > 0 and not local_files
        if local_files:
            status = "local"
        elif self.settings.check_remote_trailers and series.remote_trailers:
            status = "plexpass"
        else:
            status = "missing"

        blocked = {x.casefold() for x in self.settings.genres_for_tv_library(library)}
        genre_skipped = any(str(genre).casefold() in blocked for genre in series.genres)
        trailer_file = str(local_files[0]) if local_files else ""
        height = self._probe_height_cached(local_files[0]) if local_files else None
        resolution = f"{height}p" if height else ""
        size = 0
        mtime = 0.0
        if local_files:
            try:
                stat = local_files[0].stat()
                size = int(stat.st_size)
                mtime = float(stat.st_mtime)
            except OSError:
                pass

        return {
            "ratingKey": series.id,
            "title": series.name,
            "year": series.year,
            "library": library,
            "genres": series.genres,
            "genreSkipped": genre_skipped,
            "trailerStatus": status,
            "trailerFile": trailer_file,
            "trailerResolution": resolution,
            "trailerLanguage": "",
            "mediaPath": str(Path(self.settings.map_path(series.path))),
            "type": "show",
            "dateAdded": series.date_created,
            "embyLocalTrailerCount": series.local_trailer_count,
            "staleEmbyLocalTrailer": stale_emby_local,
            "trailerSize": size,
            "trailerMtime": mtime,
        }

    def list_tvshows_ui(self, sort: str = "title") -> list[dict]:
        _ensure_tv_settings(self.settings)
        pairs = []
        for library in self.settings.tv_libraries:
            pairs.extend((library, series) for series in self.emby.iter_series(library))
        workers = min(12, max(4, (os.cpu_count() or 4)))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="mtde-tv-ui") as pool:
            items = list(pool.map(lambda pair: self.series_ui(pair[0], pair[1]), pairs))
        if sort == "added":
            items.sort(key=lambda x: x.get("dateAdded") or "", reverse=True)
        else:
            items.sort(key=lambda x: (x.get("title") or "").casefold())
        _save_probe_cache(self)
        return items

    def scan_with_probe_persist(self, *args, **kwargs):
        try:
            return original_scan(self, *args, **kwargs)
        finally:
            _save_probe_cache(self)

    MTDE.__init__ = init_with_persistent_probe_cache
    MTDE.movie_ui = movie_ui_with_file_stats
    MTDE.list_movies_ui = list_movies_ui_with_persisted_probes
    MTDE.series_ui = series_ui
    MTDE.list_tvshows_ui = list_tvshows_ui
    MTDE.scan = scan_with_probe_persist
    MTDE._mtde_ui_tv_perf_installed = True


class _UICache:
    def __init__(self, service):
        self.service = service
        self.lock = threading.RLock()
        self.items: dict[str, list[dict]] = {"movie": [], "tv": []}
        self.saved_at: dict[str, float] = {"movie": 0.0, "tv": 0.0}
        self.refreshing: dict[str, bool] = {"movie": False, "tv": False}
        self.errors: dict[str, str] = {"movie": "", "tv": ""}
        self._load("movie")
        self._load("tv")

    def _path(self, kind: str) -> Path:
        return _cache_root() / ("ui-movies.json" if kind == "movie" else "ui-tvshows.json")

    def _load(self, kind: str) -> None:
        payload = _read_json(self._path(kind), {})
        if not isinstance(payload, dict):
            return
        items = payload.get("items")
        if not isinstance(items, list):
            return
        with self.lock:
            self.items[kind] = items
            try:
                self.saved_at[kind] = float(payload.get("saved_at") or 0.0)
            except (TypeError, ValueError):
                self.saved_at[kind] = 0.0

    def _persist(self, kind: str, items: list[dict], saved_at: float) -> None:
        _atomic_write_json(self._path(kind), {"saved_at": saved_at, "items": items})

    def clear(self, kind: str | None = None) -> None:
        kinds = (kind,) if kind else ("movie", "tv")
        with self.lock:
            for value in kinds:
                self.items[value] = []
                self.saved_at[value] = 0.0
                self.errors[value] = ""
                try:
                    self._path(value).unlink(missing_ok=True)
                except OSError:
                    pass

    def _build(self, kind: str) -> None:
        try:
            if kind == "movie":
                items = self.service.list_movies_ui()
            else:
                _ensure_tv_settings(self.service.settings)
                items = self.service.list_tvshows_ui() if self.service.settings.tv_libraries else []
            saved_at = time.time()
            with self.lock:
                self.items[kind] = list(items)
                self.saved_at[kind] = saved_at
                self.errors[kind] = ""
            self._persist(kind, list(items), saved_at)
        except Exception as exc:
            with self.lock:
                self.errors[kind] = str(exc)
        finally:
            with self.lock:
                self.refreshing[kind] = False

    def request_refresh(self, kind: str) -> None:
        with self.lock:
            if self.refreshing[kind]:
                return
            self.refreshing[kind] = True
        threading.Thread(target=self._build, args=(kind,), daemon=True, name=f"mtde-ui-cache-{kind}").start()

    def snapshot(self, kind: str, force: bool = False) -> tuple[list[dict], bool, str]:
        now = time.time()
        with self.lock:
            items = list(self.items[kind])
            age = now - self.saved_at[kind] if self.saved_at[kind] else float("inf")
            refreshing = self.refreshing[kind]
            error = self.errors[kind]
        if force or not items or age >= _UI_CACHE_TTL_SECONDS:
            self.request_refresh(kind)
            with self.lock:
                refreshing = self.refreshing[kind]
                error = self.errors[kind]
        return items, refreshing, error

    def any_refreshing(self) -> bool:
        with self.lock:
            return any(self.refreshing.values())

    def newest_refresh_iso(self) -> str | None:
        with self.lock:
            ts = max(self.saved_at.values())
        return datetime.fromtimestamp(ts).isoformat(timespec="seconds") if ts else None


def _library_stats(items: list[dict]) -> tuple[int, int, int, int, int, int]:
    total = len(items)
    local = sum(1 for item in items if item.get("trailerStatus") == "local")
    remote = sum(1 for item in items if item.get("trailerStatus") == "plexpass")
    skipped = sum(1 for item in items if item.get("genreSkipped"))
    missing = sum(1 for item in items if item.get("trailerStatus") == "missing" and not item.get("genreSkipped"))
    disk = sum(int(item.get("trailerSize") or 0) for item in items)
    return total, local, remote, missing, skipped, disk


def _install_fast_web_and_tv_ui() -> None:
    from .config import Settings
    from . import web as web_module

    if getattr(web_module, "_mtde_fast_tv_ui_installed", False):
        return

    original_create_app = web_module.create_app

    def create_app_fast(service):
        _ensure_tv_settings(service.settings)
        app = original_create_app(service)
        cache = _UICache(service)
        cache.request_refresh("movie")
        if service.settings.tv_libraries:
            cache.request_refresh("tv")

        original_index = app.view_functions.get("index")
        if original_index is not None:
            def index_with_tv_visible():
                html = original_index()
                if not isinstance(html, str):
                    return html
                html = html.replace('a[data-page="tvshows"], #page-tvshows { display:none !important; }\n', '')
                html = html.replace('#section-coverage .donut-card:nth-child(3) { display:none !important; }\n', '')
                html = html.replace('#section-coverage .donut-row { grid-template-columns:1fr 1fr !important; }\n', '')
                html = html.replace("if (h && h.textContent.trim().startsWith('TV Show Libraries')) section.style.display='none';", "")
                tv_refresh = r'''
<script id="mtde-tv-refresh-patch">
window.refreshTvShows = async function(){
  try {
    const grid=document.getElementById('tvshows-grid');
    if(grid) grid.innerHTML='<div class="library-loading"><span class="spinner"></span> Refreshing TV shows...</div>';
    await apiFetch('/api/library/tvshows?refresh=true');
    tvShowsData=[];
    _tvLoaded=false;
    await fetchTvShows();
  } catch(e) {
    if(window.showToast) showToast('TV shows refresh failed: '+e.message,'error');
    fetchTvShows();
  }
};
</script>
'''
                return html.replace("</body>", tv_refresh + "\n</body>", 1)
            app.view_functions["index"] = index_with_tv_visible

        original_get_settings = app.view_functions.get("get_settings")
        if original_get_settings is not None:
            def get_settings_with_tv():
                response = app.make_response(original_get_settings())
                data = response.get_json(silent=True) or {}
                _ensure_tv_settings(service.settings)
                libraries = data.setdefault("libraries", {})
                libraries["tv"] = [
                    {"name": name, "genres_to_skip": service.settings.genres_for_tv_library(name)}
                    for name in service.settings.tv_libraries
                ]
                return jsonify(data)
            app.view_functions["get_settings"] = get_settings_with_tv

        original_save_settings = app.view_functions.get("save_settings")
        if original_save_settings is not None:
            def save_settings_with_tv():
                payload = request.get_json(silent=True) or {}
                response = app.make_response(original_save_settings())
                if response.status_code >= 400:
                    return response
                libraries = payload.get("libraries") or {}
                tv_libs = libraries.get("tv") or []
                normalized = []
                for lib in tv_libs:
                    name = str(lib.get("name") or "").strip()
                    if name:
                        normalized.append({
                            "name": name,
                            "genres_to_skip": [str(g).strip() for g in (lib.get("genres_to_skip") or []) if str(g).strip()],
                        })
                path = _config_path()
                raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
                raw = raw or {}
                raw["TV_LIBRARIES"] = normalized
                tmp = path.with_suffix(path.suffix + ".tmp")
                tmp.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
                tmp.replace(path)
                service.update_settings(Settings.from_yaml(path))
                _ensure_tv_settings(service.settings)
                cache.clear()
                cache.request_refresh("movie")
                if service.settings.tv_libraries:
                    cache.request_refresh("tv")
                return jsonify({"ok": True})
            app.view_functions["save_settings"] = save_settings_with_tv

        def library_movies_fast():
            force = request.args.get("refresh", "false").lower() in {"1", "true", "yes"}
            items, refreshing, error = cache.snapshot("movie", force=force)
            sort = request.args.get("sort", "title")
            if sort == "added":
                items.sort(key=lambda x: x.get("dateAdded") or "", reverse=True)
            else:
                items.sort(key=lambda x: (x.get("title") or "").casefold())
            genres = {name: service.settings.genres_for_library(name) for name in service.settings.movie_libraries}
            return jsonify({
                "loading": bool(refreshing and (force or not items)),
                "items": items,
                "genresToSkip": genres,
                "error": error or None,
            })

        def library_tvshows_fast():
            force = request.args.get("refresh", "false").lower() in {"1", "true", "yes"}
            items, refreshing, error = cache.snapshot("tv", force=force)
            sort = request.args.get("sort", "title")
            if sort == "added":
                items.sort(key=lambda x: x.get("dateAdded") or "", reverse=True)
            else:
                items.sort(key=lambda x: (x.get("title") or "").casefold())
            _ensure_tv_settings(service.settings)
            genres = {name: service.settings.genres_for_tv_library(name) for name in service.settings.tv_libraries}
            return jsonify({
                "loading": bool(refreshing and (force or not items)),
                "items": items,
                "genresToSkip": genres,
                "error": error or None,
            })

        app.view_functions["library_movies"] = library_movies_fast
        app.view_functions["library_tvshows"] = library_tvshows_fast

        def dashboard_stats_fast():
            movie_items, movie_refreshing, movie_error = cache.snapshot("movie")
            tv_items, tv_refreshing, tv_error = cache.snapshot("tv")
            mt, ml, mr, mm, ms, md = _library_stats(movie_items)
            tt, tl, tr, tm, ts, td = _library_stats(tv_items)
            return jsonify({
                "total_movies": mt,
                "movies_local_trailers": ml,
                "movies_plexpass_trailers": mr,
                "movies_missing_trailers": mm,
                "movies_skipped_genres": ms,
                "movies_disk_bytes": md,
                "total_shows": tt,
                "shows_local_trailers": tl,
                "shows_plexpass_trailers": tr,
                "shows_missing_trailers": tm,
                "shows_skipped_genres": ts,
                "shows_disk_bytes": td,
                "loading": bool((movie_refreshing and not movie_items) or (tv_refreshing and service.settings.tv_libraries and not tv_items)),
                "cache_error": movie_error or tv_error or "",
            })
        app.view_functions["dashboard_stats"] = dashboard_stats_fast

        def dashboard_breakdowns_fast():
            movie_items, _, _ = cache.snapshot("movie")
            tv_items, _, _ = cache.snapshot("tv")
            libraries = []
            _ensure_tv_settings(service.settings)
            for name, kind, source in [
                *[(name, "movie", movie_items) for name in service.settings.movie_libraries],
                *[(name, "show", tv_items) for name in service.settings.tv_libraries],
            ]:
                subset = [item for item in source if item.get("library") == name]
                libraries.append({
                    "name": name,
                    "type": kind,
                    "total": len(subset),
                    "local": sum(1 for item in subset if item.get("trailerStatus") == "local"),
                    "plexpass": sum(1 for item in subset if item.get("trailerStatus") == "plexpass"),
                    "missing": sum(1 for item in subset if item.get("trailerStatus") == "missing" and not item.get("genreSkipped")),
                    "skipped": sum(1 for item in subset if item.get("genreSkipped")),
                })
            resolution: dict[str, int] = {}
            for item in movie_items + tv_items:
                if item.get("trailerStatus") == "local" and item.get("trailerResolution"):
                    key = str(item["trailerResolution"])
                    resolution[key] = resolution.get(key, 0) + 1
            return jsonify({"resolution": resolution, "resolution_plexpass": {}, "language": {}, "libraries": libraries})
        app.view_functions["dashboard_breakdowns"] = dashboard_breakdowns_fast

        def recent_trailers_fast():
            movie_items, _, _ = cache.snapshot("movie")
            tv_items, _, _ = cache.snapshot("tv")
            recent = []
            for item in movie_items + tv_items:
                mtime = float(item.get("trailerMtime") or 0.0)
                if not mtime:
                    continue
                recent.append((mtime, {
                    "title": item.get("title") or "",
                    "year": item.get("year"),
                    "media_type": "show" if item.get("type") == "show" else "movie",
                    "downloaded_at": datetime.fromtimestamp(mtime).isoformat(),
                    "plex_rating_key": item.get("ratingKey"),
                    "poster_url": "",
                }))
            recent.sort(key=lambda value: value[0], reverse=True)
            return jsonify({"items": [value[1] for value in recent[:20]]})
        app.view_functions["recent_trailers"] = recent_trailers_fast

        original_status = app.view_functions.get("status")
        last_seen_run = {"value": None}
        if original_status is not None:
            def status_with_cache_state():
                response = app.make_response(original_status())
                data = response.get_json(silent=True) or {}
                last_run = data.get("last_run_time")
                if last_run and last_run != last_seen_run["value"]:
                    last_seen_run["value"] = last_run
                    cache.request_refresh("movie")
                    if getattr(service.settings, "tv_libraries", []):
                        cache.request_refresh("tv")
                data["cache_progress"] = {"refreshing": cache.any_refreshing()}
                data["last_refreshed"] = cache.newest_refresh_iso() or data.get("last_refreshed")
                return jsonify(data)
            app.view_functions["status"] = status_with_cache_state

        for endpoint in ("download_trailer", "delete_trailer"):
            original_view = app.view_functions.get(endpoint)
            if original_view is None:
                continue
            def make_wrapper(view):
                def wrapped(*args, **kwargs):
                    response = app.make_response(view(*args, **kwargs))
                    if response.status_code < 400:
                        cache.request_refresh("movie")
                        if getattr(service.settings, "tv_libraries", []):
                            cache.request_refresh("tv")
                    return response
                return wrapped
            app.view_functions[endpoint] = make_wrapper(original_view)

        return app

    web_module.create_app = create_app_fast
    web_module._mtde_fast_tv_ui_installed = True


def install_ui_tv_performance() -> None:
    _install_settings_tv_support()
    _install_emby_series_support()
    _install_service_ui_support()
    _install_fast_web_and_tv_ui()
