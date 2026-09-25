from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
import inspect
import os
from pathlib import Path
import threading
from typing import Callable, Iterable

from .config import Settings
from .emby import EmbyClient, EmbyMovie
from .trailer import (
    Candidate,
    TrailerDownloader,
    find_local_trailers,
    probe_video_height,
    select_trailer_directory,
)
from .tv import (
    TVTrailerDownloader,
    finalize_series_filename,
    find_series_local_trailers,
    sanitize_series_title,
    select_series_trailer_directory,
)


@dataclass
class ScanResult:
    library: str
    item_id: str
    title: str
    year: int | None
    status: str
    message: str = ""
    trailer_path: str | None = None


ProgressCallback = Callable[[str], None]
StopCallback = Callable[[], bool]


class MTDE:
    def __init__(self, settings: Settings):
        self._scan_lock = threading.Lock()
        self._probe_cache_lock = threading.Lock()
        self._probe_cache: dict[str, tuple[int, int, int | None]] = {}
        self.update_settings(settings)

    def update_settings(self, settings: Settings) -> None:
        self.settings = settings
        self.emby = EmbyClient(
            settings.emby_url,
            settings.emby_api_key,
            timeout=settings.emby_timeout,
        )
        downloader_kwargs = dict(
            preferred_language=settings.preferred_language,
            min_height=settings.trailer_resolution_min,
            max_height=settings.trailer_resolution_max,
            max_duration=settings.max_trailer_duration,
            search_results=settings.search_results,
            output_format=settings.trailer_file_format,
            cookies_file=settings.cookies_file,
            show_progress=settings.show_ytdlp_progress,
            custom_options=settings.yt_dlp_custom_options,
        )
        self.downloader = TrailerDownloader(**downloader_kwargs)
        # Keep TV matching separate exactly like upstream MTDP Modules/TV.py.
        self.tv_downloader = TVTrailerDownloader(**downloader_kwargs)

    def test_connection(self) -> dict:
        return self.emby.system_info()

    def _mapped_media_path(self, media: EmbyMovie) -> Path:
        return Path(self.settings.map_path(media.path))

    # Kept for compatibility with the existing movie safety/repair layers.
    def _mapped_movie_path(self, movie: EmbyMovie) -> Path:
        return self._mapped_media_path(movie)

    def _skip_genre(self, library: str, movie: EmbyMovie) -> str | None:
        blocked = {x.casefold() for x in self.settings.genres_for_library(library)}
        for genre in movie.genres:
            if genre.casefold() in blocked:
                return genre
        return None

    def _skip_tv_genre(self, library: str, series: EmbyMovie) -> str | None:
        blocked = {x.casefold() for x in self.settings.genres_for_tv_library(library)}
        for genre in series.genres:
            if genre.casefold() in blocked:
                return genre
        return None

    def _local_files(self, movie: EmbyMovie) -> list[Path]:
        return find_local_trailers(self._mapped_movie_path(movie), self.settings.trailer_folder)

    def _series_local_files(self, series: EmbyMovie) -> list[Path]:
        return find_series_local_trailers(self._mapped_media_path(series))

    def _probe_height_cached(self, path: Path) -> int | None:
        key = str(path)
        try:
            stat = path.stat()
            stamp = int(stat.st_mtime_ns)
            size = int(stat.st_size)
        except OSError:
            return probe_video_height(path)

        with self._probe_cache_lock:
            cached = self._probe_cache.get(key)
            if cached and cached[0] == stamp and cached[1] == size:
                return cached[2]

        height = probe_video_height(path)
        with self._probe_cache_lock:
            self._probe_cache[key] = (stamp, size, height)
        return height

    @staticmethod
    def _caller_progress_callback() -> ProgressCallback | None:
        frame = inspect.currentframe()
        try:
            caller = frame.f_back.f_back if frame and frame.f_back else None
            while caller:
                maybe = caller.f_locals.get("add_log")
                if callable(maybe):
                    return maybe
                caller = caller.f_back
        finally:
            del frame
        return None

    @staticmethod
    def _log(progress: ProgressCallback | None, status: str, library: str, title: str, message: str = "") -> None:
        if not progress:
            return
        suffix = f" | {message}" if message else ""
        progress(f"{status.upper():18} | {library} | {title}{suffix}")

    def movie_ui(self, library: str, movie: EmbyMovie) -> dict:
        local_files = self._local_files(movie)
        stale_emby_local = movie.local_trailer_count > 0 and not local_files
        if local_files:
            status = "local"
        elif self.settings.check_remote_trailers and movie.remote_trailers:
            status = "plexpass"
        else:
            status = "missing"

        trailer_file = str(local_files[0]) if local_files else ""
        height = self._probe_height_cached(local_files[0]) if local_files else None
        resolution = f"{height}p" if height else ""

        return {
            "ratingKey": movie.id,
            "title": movie.name,
            "year": movie.year,
            "library": library,
            "genres": movie.genres,
            "genreSkipped": bool(self._skip_genre(library, movie)),
            "trailerStatus": status,
            "trailerFile": trailer_file,
            "trailerResolution": resolution,
            "trailerLanguage": "",
            "mediaPath": str(self._mapped_movie_path(movie)),
            "type": "movie",
            "dateAdded": movie.date_created,
            "embyLocalTrailerCount": movie.local_trailer_count,
            "staleEmbyLocalTrailer": stale_emby_local,
        }

    def series_ui(self, library: str, series: EmbyMovie) -> dict:
        local_files = self._series_local_files(series)
        stale_emby_local = series.local_trailer_count > 0 and not local_files
        if local_files:
            status = "local"
        elif self.settings.check_remote_trailers and series.remote_trailers:
            status = "plexpass"
        else:
            status = "missing"
        trailer_file = str(local_files[0]) if local_files else ""
        height = self._probe_height_cached(local_files[0]) if local_files else None
        resolution = f"{height}p" if height else ""
        return {
            "ratingKey": series.id,
            "title": series.name,
            "year": series.year,
            "library": library,
            "genres": series.genres,
            "genreSkipped": bool(self._skip_tv_genre(library, series)),
            "trailerStatus": status,
            "trailerFile": trailer_file,
            "trailerResolution": resolution,
            "trailerLanguage": "",
            "mediaPath": str(self._mapped_media_path(series)),
            "type": "show",
            "dateAdded": series.date_created,
            "embyLocalTrailerCount": series.local_trailer_count,
            "staleEmbyLocalTrailer": stale_emby_local,
        }

    def list_movies_ui(self, sort: str = "title") -> list[dict]:
        pairs: list[tuple[str, EmbyMovie]] = []
        for library in self.settings.movie_libraries:
            pairs.extend((library, movie) for movie in self.emby.iter_movies(library))
        workers = min(12, max(4, (os.cpu_count() or 4)))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="mtde-ui") as pool:
            items = list(pool.map(lambda pair: self.movie_ui(pair[0], pair[1]), pairs))
        if sort == "added":
            items.sort(key=lambda x: x.get("dateAdded") or "", reverse=True)
        else:
            items.sort(key=lambda x: (x.get("title") or "").casefold())
        return items

    def list_tvshows_ui(self, sort: str = "title") -> list[dict]:
        pairs: list[tuple[str, EmbyMovie]] = []
        for library in self.settings.tv_libraries:
            pairs.extend((library, series) for series in self.emby.iter_series(library))
        workers = min(12, max(4, (os.cpu_count() or 4)))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="mtde-tv-ui") as pool:
            items = list(pool.map(lambda pair: self.series_ui(pair[0], pair[1]), pairs))
        if sort == "added":
            items.sort(key=lambda x: x.get("dateAdded") or "", reverse=True)
        else:
            items.sort(key=lambda x: (x.get("title") or "").casefold())
        return items

    def item_detail_ui(self, item_id: str) -> dict:
        raw = self.emby.get_item(item_id)
        media = self.emby._movie_from_item(raw)
        if str(raw.get("Type") or "").casefold() == "series":
            ui = self.series_ui("", media)
        else:
            ui = self.movie_ui("", media)
        studios = raw.get("Studios") or []
        people = raw.get("People") or []
        ticks = int(raw.get("RunTimeTicks") or 0)
        ui.update({
            "summary": str(raw.get("Overview") or ""),
            "contentRating": str(raw.get("OfficialRating") or ""),
            "rating": float(raw.get("CommunityRating") or 0),
            "duration": int(ticks / 10_000) if ticks else 0,
            "studio": str((studios[0] or {}).get("Name") or "") if studios else "",
            "actors": [
                str(x.get("Name") or "")
                for x in people
                if str(x.get("Type") or "").casefold() == "actor"
            ],
            "plexpassExtraKey": "",
        })
        return ui

    def scan(
        self,
        download: bool | None = None,
        should_stop: StopCallback | None = None,
        progress: ProgressCallback | None = None,
    ) -> list[ScanResult]:
        """Run upstream-equivalent Movies followed by TV Shows.

        MTDP Docker defaults LAUNCH_METHOD to both. MTDE follows the same behavior:
        every configured movie library is processed first, then every configured
        TV library, with only the Plex calls replaced by Emby calls.
        """
        if not self._scan_lock.acquire(blocking=False):
            raise RuntimeError("A scan is already running")
        should_stop = should_stop or (lambda: False)
        progress = progress or self._caller_progress_callback()
        try:
            requested_download = self.settings.download_trailers if download is None else bool(download)
            do_download = requested_download and self.settings.download_trailers and not self.settings.dry_run
            results: list[ScanResult] = []

            for library in self.settings.movie_libraries:
                if should_stop():
                    result = ScanResult(library, "", library, None, "stopped", "stop requested")
                    results.append(result)
                    self._log(progress, result.status, library, result.title, result.message)
                    return results
                try:
                    self._log(progress, "library_start", library, library, "loading movies from Emby")
                    for movie in self.emby.iter_movies(library):
                        if should_stop():
                            result = ScanResult(library, movie.id, movie.name, movie.year, "stopped", "stop requested")
                            results.append(result)
                            self._log(progress, result.status, library, movie.name, result.message)
                            return results
                        self._log(progress, "checking", library, movie.name)
                        results.append(self._process_movie(library, movie, do_download, progress=progress))
                except Exception as exc:
                    result = ScanResult(library, "", library, None, "library_error", str(exc))
                    results.append(result)
                    self._log(progress, result.status, library, library, result.message)

            for library in self.settings.tv_libraries:
                if should_stop():
                    result = ScanResult(library, "", library, None, "stopped", "stop requested")
                    results.append(result)
                    self._log(progress, result.status, library, result.title, result.message)
                    return results
                try:
                    self._log(progress, "library_start", library, library, "loading TV shows from Emby")
                    for series in self.emby.iter_series(library):
                        if should_stop():
                            result = ScanResult(library, series.id, series.name, series.year, "stopped", "stop requested")
                            results.append(result)
                            self._log(progress, result.status, library, series.name, result.message)
                            return results
                        self._log(progress, "checking", library, series.name)
                        results.append(self._process_series(library, series, do_download, progress=progress))
                except Exception as exc:
                    result = ScanResult(library, "", library, None, "library_error", str(exc))
                    results.append(result)
                    self._log(progress, result.status, library, library, result.message)
            return results
        finally:
            self._scan_lock.release()

    def _process_movie(
        self,
        library: str,
        movie: EmbyMovie,
        do_download: bool,
        progress: ProgressCallback | None = None,
    ) -> ScanResult:
        mapped_movie_path = self._mapped_movie_path(movie)
        local_files = find_local_trailers(mapped_movie_path, self.settings.trailer_folder)

        if local_files:
            if self.settings.upgrade_trailers == "local":
                height = self._probe_height_cached(local_files[0])
                if height is not None and height < self.settings.trailer_resolution_min:
                    return self._upgrade_movie(library, movie, local_files, height, do_download, progress=progress)
            message_parts: list[str] = []
            if movie.local_trailer_count > 0:
                message_parts.append(f"Emby LocalTrailerCount={movie.local_trailer_count}")
            message_parts.append(f"local file: {local_files[0]}")
            if len(local_files) > 1:
                message_parts.append(f"+{len(local_files) - 1} more")
            result = ScanResult(library, movie.id, movie.name, movie.year, "has_local_trailer", "; ".join(message_parts), str(local_files[0]))
            self._log(progress, result.status, library, movie.name, result.message)
            return result

        if movie.local_trailer_count > 0:
            self._log(progress, "stale_emby_trailer_state", library, movie.name, f"Emby LocalTrailerCount={movie.local_trailer_count}, but no local trailer file exists on the mapped media path; continuing with normal search")
        if self.settings.check_remote_trailers and movie.remote_trailers:
            result = ScanResult(library, movie.id, movie.name, movie.year, "has_remote_trailer", f"Emby reports {len(movie.remote_trailers)} remote trailer(s)")
            self._log(progress, result.status, library, movie.name, result.message)
            return result
        skipped = self._skip_genre(library, movie)
        if skipped:
            result = ScanResult(library, movie.id, movie.name, movie.year, "genre_skipped", skipped)
            self._log(progress, result.status, library, movie.name, result.message)
            return result
        movie_dir = mapped_movie_path if mapped_movie_path.is_dir() else mapped_movie_path.parent
        if not movie_dir.exists():
            result = ScanResult(library, movie.id, movie.name, movie.year, "path_missing", str(movie_dir))
            self._log(progress, result.status, library, movie.name, result.message)
            return result
        return self._search_and_download_movie(library, movie, do_download, progress)

    def _search_and_download_movie(self, library, movie, do_download, progress):
        try:
            query_hint = f"{movie.name} {movie.year or ''} official trailer {self.settings.preferred_language}".strip()
            self._log(progress, "searching", library, movie.name, query_hint)
            candidates = self.downloader.search(movie.name, movie.year)
            self._log(progress, "search_results", library, movie.name, f"{len(candidates)} candidate(s)")
            ranked = self.downloader.ranked_candidates(candidates, movie.name, movie.year)
            if not ranked:
                result = ScanResult(library, movie.id, movie.name, movie.year, "no_match")
                self._log(progress, result.status, library, movie.name)
                return result
            chosen = ranked[0]
            self._log(progress, "match", library, movie.name, chosen.title)
            if not do_download:
                result = ScanResult(library, movie.id, movie.name, movie.year, "would_download", chosen.title)
                self._log(progress, result.status, library, movie.name, result.message)
                return result
            errors: list[str] = []
            for index, candidate in enumerate(ranked, start=1):
                self._log(progress, "downloading", library, movie.name, f"candidate {index}/{len(ranked)}: {candidate.title}")
                try:
                    file_path = self._download_candidate(movie, candidate)
                    result = ScanResult(library, movie.id, movie.name, movie.year, "downloaded", candidate.title, str(file_path))
                    self._log(progress, result.status, library, movie.name, str(file_path))
                    return result
                except Exception as exc:
                    errors.append(str(exc))
                    if index < len(ranked):
                        self._log(progress, "candidate_failed", library, movie.name, f"{candidate.title} | {exc} | trying next verified candidate")
            message = f"all {len(ranked)} verified candidate(s) failed"
            if errors:
                message += f"; last error: {errors[-1]}"
            result = ScanResult(library, movie.id, movie.name, movie.year, "error", message)
            self._log(progress, result.status, library, movie.name, result.message)
            return result
        except Exception as exc:
            result = ScanResult(library, movie.id, movie.name, movie.year, "error", str(exc))
            self._log(progress, result.status, library, movie.name, result.message)
            return result

    def _process_series(
        self,
        library: str,
        series: EmbyMovie,
        do_download: bool,
        progress: ProgressCallback | None = None,
    ) -> ScanResult:
        mapped = self._mapped_media_path(series)
        local_files = find_series_local_trailers(mapped)
        if local_files:
            if self.settings.upgrade_trailers == "local":
                heights = [self._probe_height_cached(path) for path in local_files]
                known = [height for height in heights if height is not None]
                best_height = max(known) if known else None
                if best_height is not None and best_height < self.settings.trailer_resolution_min:
                    return self._upgrade_series(library, series, local_files, best_height, do_download, progress)
            message_parts: list[str] = []
            if series.local_trailer_count > 0:
                message_parts.append(f"Emby LocalTrailerCount={series.local_trailer_count}")
            message_parts.append(f"local file: {local_files[0]}")
            if len(local_files) > 1:
                message_parts.append(f"+{len(local_files) - 1} more")
            result = ScanResult(library, series.id, series.name, series.year, "has_local_trailer", "; ".join(message_parts), str(local_files[0]))
            self._log(progress, result.status, library, series.name, result.message)
            return result

        if series.local_trailer_count > 0:
            self._log(progress, "stale_emby_trailer_state", library, series.name, f"Emby LocalTrailerCount={series.local_trailer_count}, but no local TV trailer file exists on the mapped media path; continuing with normal search")
        if self.settings.check_remote_trailers and series.remote_trailers:
            result = ScanResult(library, series.id, series.name, series.year, "has_remote_trailer", f"Emby reports {len(series.remote_trailers)} remote trailer(s)")
            self._log(progress, result.status, library, series.name, result.message)
            return result
        skipped = self._skip_tv_genre(library, series)
        if skipped:
            result = ScanResult(library, series.id, series.name, series.year, "genre_skipped", skipped)
            self._log(progress, result.status, library, series.name, result.message)
            return result
        series_dir = mapped if mapped.is_dir() else mapped.parent
        if not series_dir.exists():
            result = ScanResult(library, series.id, series.name, series.year, "path_missing", str(series_dir))
            self._log(progress, result.status, library, series.name, result.message)
            return result

        try:
            query_hint = f"{series.name} {series.year or ''} TV show official trailer {self.settings.preferred_language}".strip()
            self._log(progress, "searching", library, series.name, query_hint)
            candidates = self.tv_downloader.search(series.name, series.year)
            self._log(progress, "search_results", library, series.name, f"{len(candidates)} candidate(s)")
            ranked = self.tv_downloader.ranked_candidates(candidates, series.name, series.year)
            if not ranked:
                result = ScanResult(library, series.id, series.name, series.year, "no_match")
                self._log(progress, result.status, library, series.name)
                return result
            chosen = ranked[0]
            self._log(progress, "match", library, series.name, chosen.title)
            if not do_download:
                result = ScanResult(library, series.id, series.name, series.year, "would_download", chosen.title)
                self._log(progress, result.status, library, series.name, result.message)
                return result
            errors: list[str] = []
            for index, candidate in enumerate(ranked, start=1):
                self._log(progress, "downloading", library, series.name, f"candidate {index}/{len(ranked)}: {candidate.title}")
                try:
                    file_path = self._download_series_candidate(series, candidate)
                    result = ScanResult(library, series.id, series.name, series.year, "downloaded", candidate.title, str(file_path))
                    self._log(progress, result.status, library, series.name, str(file_path))
                    return result
                except Exception as exc:
                    errors.append(str(exc))
                    if index < len(ranked):
                        self._log(progress, "candidate_failed", library, series.name, f"{candidate.title} | {exc} | trying next verified candidate")
            message = f"all {len(ranked)} verified candidate(s) failed"
            if errors:
                message += f"; last error: {errors[-1]}"
            result = ScanResult(library, series.id, series.name, series.year, "error", message)
            self._log(progress, result.status, library, series.name, result.message)
            return result
        except Exception as exc:
            result = ScanResult(library, series.id, series.name, series.year, "error", str(exc))
            self._log(progress, result.status, library, series.name, result.message)
            return result

    def _upgrade_movie(self, library, movie, local_files, old_height, do_download, progress=None) -> ScanResult:
        try:
            self._log(progress, "upgrade_search", library, movie.name, f"existing trailer is {old_height}p")
            candidates = self.downloader.search(movie.name, movie.year)
            self._log(progress, "search_results", library, movie.name, f"{len(candidates)} candidate(s)")
            ranked = self.downloader.ranked_candidates(candidates, movie.name, movie.year)
            if not ranked:
                result = ScanResult(library, movie.id, movie.name, movie.year, "upgrade_no_match", f"existing trailer is {old_height}p", str(local_files[0]))
                self._log(progress, result.status, library, movie.name, result.message)
                return result
            chosen = ranked[0]
            self._log(progress, "upgrade_match", library, movie.name, chosen.title)
            if not do_download:
                result = ScanResult(library, movie.id, movie.name, movie.year, "would_upgrade", f"{old_height}p -> {chosen.title}", str(local_files[0]))
                self._log(progress, result.status, library, movie.name, result.message)
                return result
            trailer_dir = select_trailer_directory(self._mapped_movie_path(movie), self.settings.trailer_folder)
            temp_stem = trailer_dir / f".mtde-upgrade-{movie.id}"
            errors: list[str] = []
            for index, candidate in enumerate(ranked, start=1):
                self._log(progress, "upgrade_downloading", library, movie.name, f"candidate {index}/{len(ranked)}: {candidate.title}")
                try:
                    new_file = self.downloader.download(candidate, temp_stem)
                    new_height = self._probe_height_cached(new_file)
                    if new_height is None or new_height < self.settings.trailer_resolution_min or new_height <= old_height:
                        new_file.unlink(missing_ok=True)
                        raise RuntimeError(f"downloaded trailer is {new_height or 'unknown'}p; requires >= {self.settings.trailer_resolution_min}p and better than {old_height}p")
                    safe_title = "".join(c if c not in '<>:"/\\|?*' else " " for c in movie.name).strip()
                    year = f" ({movie.year})" if movie.year else ""
                    final_file = trailer_dir / f"{safe_title}{year} - Trailer{new_file.suffix}"
                    for old_file in local_files:
                        old_file.unlink(missing_ok=True)
                    new_file.replace(final_file)
                    if self.settings.refresh_emby_after_download:
                        self.emby.refresh_item(movie.id)
                    result = ScanResult(library, movie.id, movie.name, movie.year, "upgraded", f"{old_height}p -> {new_height}p | {candidate.title}", str(final_file))
                    self._log(progress, result.status, library, movie.name, str(final_file))
                    return result
                except Exception as exc:
                    errors.append(str(exc))
                    if index < len(ranked):
                        self._log(progress, "candidate_failed", library, movie.name, f"{candidate.title} | {exc} | trying next verified candidate")
            message = f"all {len(ranked)} verified upgrade candidate(s) failed"
            if errors:
                message += f"; last error: {errors[-1]}"
            result = ScanResult(library, movie.id, movie.name, movie.year, "upgrade_error", message, str(local_files[0]))
            self._log(progress, result.status, library, movie.name, result.message)
            return result
        except Exception as exc:
            result = ScanResult(library, movie.id, movie.name, movie.year, "upgrade_error", str(exc), str(local_files[0]))
            self._log(progress, result.status, library, movie.name, result.message)
            return result

    def _upgrade_series(self, library, series, local_files, old_height, do_download, progress=None) -> ScanResult:
        """Port upstream TV upgrade behavior: only replace after a better file exists."""
        try:
            self._log(progress, "upgrade_search", library, series.name, f"existing trailer is {old_height}p")
            candidates = self.tv_downloader.search(series.name, series.year)
            self._log(progress, "search_results", library, series.name, f"{len(candidates)} candidate(s)")
            ranked = self.tv_downloader.ranked_candidates(candidates, series.name, series.year)
            if not ranked:
                result = ScanResult(library, series.id, series.name, series.year, "upgrade_no_match", f"existing trailer is {old_height}p", str(local_files[0]))
                self._log(progress, result.status, library, series.name, result.message)
                return result
            chosen = ranked[0]
            self._log(progress, "upgrade_match", library, series.name, chosen.title)
            if not do_download:
                result = ScanResult(library, series.id, series.name, series.year, "would_upgrade", f"{old_height}p -> {chosen.title}", str(local_files[0]))
                self._log(progress, result.status, library, series.name, result.message)
                return result
            trailer_dir = select_series_trailer_directory(self._mapped_media_path(series))
            temp_stem = trailer_dir / f".mtde-upgrade-{series.id}"
            errors: list[str] = []
            for index, candidate in enumerate(ranked, start=1):
                self._log(progress, "upgrade_downloading", library, series.name, f"candidate {index}/{len(ranked)}: {candidate.title}")
                try:
                    new_file = self.tv_downloader.download(candidate, temp_stem, ignore_minimum=True)
                    new_height = self._probe_height_cached(new_file)
                    if new_height is None or new_height <= old_height:
                        new_file.unlink(missing_ok=True)
                        raise RuntimeError(f"downloaded TV trailer is {new_height or 'unknown'}p; it is not better than {old_height}p")
                    final_file = finalize_series_filename(new_file, series.name, candidate, self.settings.preferred_language)
                    for old_file in local_files:
                        if old_file != final_file:
                            old_file.unlink(missing_ok=True)
                    if self.settings.refresh_emby_after_download:
                        self.emby.refresh_item(series.id)
                    status = "upgraded" if new_height >= self.settings.trailer_resolution_min else "upgraded_below_min"
                    result = ScanResult(library, series.id, series.name, series.year, status, f"{old_height}p -> {new_height}p | {candidate.title}", str(final_file))
                    self._log(progress, result.status, library, series.name, str(final_file))
                    return result
                except Exception as exc:
                    errors.append(str(exc))
                    if index < len(ranked):
                        self._log(progress, "candidate_failed", library, series.name, f"{candidate.title} | {exc} | trying next verified candidate")
            message = f"all {len(ranked)} verified upgrade candidate(s) failed"
            if errors:
                message += f"; last error: {errors[-1]}"
            result = ScanResult(library, series.id, series.name, series.year, "upgrade_error", message, str(local_files[0]))
            self._log(progress, result.status, library, series.name, result.message)
            return result
        except Exception as exc:
            result = ScanResult(library, series.id, series.name, series.year, "upgrade_error", str(exc), str(local_files[0]))
            self._log(progress, result.status, library, series.name, result.message)
            return result

    def _download_candidate(self, movie: EmbyMovie, candidate: Candidate, ignore_minimum: bool = False) -> Path:
        movie_path = self._mapped_movie_path(movie)
        trailer_dir = select_trailer_directory(movie_path, self.settings.trailer_folder)
        safe_title = "".join(c if c not in '<>:"/\\|?*' else " " for c in movie.name).strip()
        year = f" ({movie.year})" if movie.year else ""
        output_stem = trailer_dir / f"{safe_title}{year} - Trailer"
        file_path = self.downloader.download(candidate, output_stem, ignore_minimum=ignore_minimum)
        if self.settings.refresh_emby_after_download:
            self.emby.refresh_item(movie.id)
        return file_path

    def _download_series_candidate(self, series: EmbyMovie, candidate: Candidate, ignore_minimum: bool = False) -> Path:
        trailer_dir = select_series_trailer_directory(self._mapped_media_path(series))
        output_stem = trailer_dir / f"{sanitize_series_title(series.name)}-trailer"
        file_path = self.tv_downloader.download(candidate, output_stem, ignore_minimum=ignore_minimum)
        file_path = finalize_series_filename(file_path, series.name, candidate, self.settings.preferred_language)
        if self.settings.refresh_emby_after_download:
            self.emby.refresh_item(series.id)
        return file_path

    def download_manual(self, item_id: str, url: str, result_title: str = "", ignore_minimum: bool = False) -> Path:
        if self.settings.dry_run:
            raise RuntimeError("DRY_RUN is active; no files were written")
        if not self.settings.download_trailers:
            raise RuntimeError("DOWNLOAD_TRAILERS is disabled")
        item_type, media = self.emby.get_media(item_id)
        candidate = Candidate(url=url, title=result_title or media.name, duration=None, height=None, channel=None)
        if item_type.casefold() == "series":
            existing = self._series_local_files(media)
            if existing:
                return existing[0]
            return self._download_series_candidate(media, candidate, ignore_minimum=ignore_minimum)
        existing = self._local_files(media)
        if existing:
            return existing[0]
        return self._download_candidate(media, candidate, ignore_minimum=ignore_minimum)

    def delete_local_trailer(self, item_id: str, requested_path: str) -> None:
        if self.settings.dry_run:
            raise RuntimeError("DRY_RUN is active; deletion is disabled")
        item_type, media = self.emby.get_media(item_id)
        files = self._series_local_files(media) if item_type.casefold() == "series" else self._local_files(media)
        allowed = {path.resolve() for path in files}
        target = Path(requested_path).resolve()
        if target not in allowed:
            raise PermissionError("Requested file is not a detected local trailer for this Emby item")
        target.unlink()
        if self.settings.refresh_emby_after_download:
            self.emby.refresh_item(media.id)

    @staticmethod
    def serialize(results: Iterable[ScanResult]) -> list[dict]:
        return [asdict(result) for result in results]
