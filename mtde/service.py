from __future__ import annotations

from dataclasses import asdict, dataclass
import inspect
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
        self.update_settings(settings)

    def update_settings(self, settings: Settings) -> None:
        self.settings = settings
        self.emby = EmbyClient(
            settings.emby_url,
            settings.emby_api_key,
            timeout=settings.emby_timeout,
        )
        self.downloader = TrailerDownloader(
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

    def test_connection(self) -> dict:
        return self.emby.system_info()

    def _mapped_movie_path(self, movie: EmbyMovie) -> Path:
        return Path(self.settings.map_path(movie.path))

    def _skip_genre(self, library: str, movie: EmbyMovie) -> str | None:
        blocked = {x.casefold() for x in self.settings.genres_for_library(library)}
        for genre in movie.genres:
            if genre.casefold() in blocked:
                return genre
        return None

    def _local_files(self, movie: EmbyMovie) -> list[Path]:
        return find_local_trailers(self._mapped_movie_path(movie), self.settings.trailer_folder)

    @staticmethod
    def _caller_progress_callback() -> ProgressCallback | None:
        """Best-effort bridge for the Web UI without changing older callers."""
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
        height = probe_video_height(local_files[0]) if local_files else None
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

    def list_movies_ui(self, sort: str = "title") -> list[dict]:
        items: list[dict] = []
        for library in self.settings.movie_libraries:
            for movie in self.emby.iter_movies(library):
                items.append(self.movie_ui(library, movie))
        if sort == "added":
            items.sort(key=lambda x: x.get("dateAdded") or "", reverse=True)
        else:
            items.sort(key=lambda x: (x.get("title") or "").casefold())
        return items

    def item_detail_ui(self, item_id: str) -> dict:
        raw = self.emby.get_item(item_id)
        movie = self.emby._movie_from_item(raw)
        ui = self.movie_ui("", movie)
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
                    break
                try:
                    self._log(progress, "library_start", library, library, "loading movies from Emby")
                    for movie in self.emby.iter_movies(library):
                        if should_stop():
                            result = ScanResult(library, movie.id, movie.name, movie.year, "stopped", "stop requested")
                            results.append(result)
                            self._log(progress, result.status, library, movie.name, result.message)
                            return results
                        self._log(progress, "checking", library, movie.name)
                        result = self._process_movie(library, movie, do_download, progress=progress)
                        results.append(result)
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
                height = probe_video_height(local_files[0])
                if height is not None and height < self.settings.trailer_resolution_min:
                    return self._upgrade_movie(library, movie, local_files, height, do_download, progress=progress)

            message_parts: list[str] = []
            if movie.local_trailer_count > 0:
                message_parts.append(f"Emby LocalTrailerCount={movie.local_trailer_count}")
            message_parts.append(f"local file: {local_files[0]}")
            if len(local_files) > 1:
                message_parts.append(f"+{len(local_files) - 1} more")
            result = ScanResult(
                library,
                movie.id,
                movie.name,
                movie.year,
                "has_local_trailer",
                "; ".join(message_parts),
                str(local_files[0]),
            )
            self._log(progress, result.status, library, movie.name, result.message)
            return result

        if movie.local_trailer_count > 0:
            self._log(
                progress,
                "stale_emby_trailer_state",
                library,
                movie.name,
                f"Emby LocalTrailerCount={movie.local_trailer_count}, but no local trailer file exists on the mapped media path; continuing with normal search",
            )

        if self.settings.check_remote_trailers and movie.remote_trailers:
            result = ScanResult(
                library,
                movie.id,
                movie.name,
                movie.year,
                "has_remote_trailer",
                f"Emby reports {len(movie.remote_trailers)} remote trailer(s)",
            )
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

        try:
            query_hint = f"{movie.name} {movie.year or ''} official trailer {self.settings.preferred_language}".strip()
            self._log(progress, "searching", library, movie.name, query_hint)
            candidates = self.downloader.search(movie.name, movie.year)
            self._log(progress, "search_results", library, movie.name, f"{len(candidates)} candidate(s)")
            chosen = self.downloader.choose(candidates, movie.name, movie.year)
            if not chosen:
                result = ScanResult(library, movie.id, movie.name, movie.year, "no_match")
                self._log(progress, result.status, library, movie.name)
                return result
            self._log(progress, "match", library, movie.name, chosen.title)
            if not do_download:
                result = ScanResult(
                    library,
                    movie.id,
                    movie.name,
                    movie.year,
                    "would_download",
                    chosen.title,
                )
                self._log(progress, result.status, library, movie.name, result.message)
                return result

            self._log(progress, "downloading", library, movie.name, chosen.title)
            file_path = self._download_candidate(movie, chosen)
            result = ScanResult(
                library,
                movie.id,
                movie.name,
                movie.year,
                "downloaded",
                chosen.title,
                str(file_path),
            )
            self._log(progress, result.status, library, movie.name, str(file_path))
            return result
        except Exception as exc:
            result = ScanResult(library, movie.id, movie.name, movie.year, "error", str(exc))
            self._log(progress, result.status, library, movie.name, result.message)
            return result

    def _upgrade_movie(
        self,
        library: str,
        movie: EmbyMovie,
        local_files: list[Path],
        old_height: int,
        do_download: bool,
        progress: ProgressCallback | None = None,
    ) -> ScanResult:
        try:
            self._log(progress, "upgrade_search", library, movie.name, f"existing trailer is {old_height}p")
            candidates = self.downloader.search(movie.name, movie.year)
            self._log(progress, "search_results", library, movie.name, f"{len(candidates)} candidate(s)")
            chosen = self.downloader.choose(candidates, movie.name, movie.year)
            if not chosen:
                result = ScanResult(
                    library, movie.id, movie.name, movie.year,
                    "upgrade_no_match", f"existing trailer is {old_height}p",
                    str(local_files[0]),
                )
                self._log(progress, result.status, library, movie.name, result.message)
                return result
            self._log(progress, "upgrade_match", library, movie.name, chosen.title)
            if not do_download:
                result = ScanResult(
                    library, movie.id, movie.name, movie.year,
                    "would_upgrade", f"{old_height}p -> {chosen.title}",
                    str(local_files[0]),
                )
                self._log(progress, result.status, library, movie.name, result.message)
                return result

            trailer_dir = select_trailer_directory(
                self._mapped_movie_path(movie), self.settings.trailer_folder,
            )
            temp_stem = trailer_dir / f".mtde-upgrade-{movie.id}"
            self._log(progress, "upgrade_downloading", library, movie.name, chosen.title)
            new_file = self.downloader.download(chosen, temp_stem)

            safe_title = "".join(
                c if c not in '<>:"/\\|?*' else " " for c in movie.name
            ).strip()
            year = f" ({movie.year})" if movie.year else ""
            final_file = trailer_dir / f"{safe_title}{year} - Trailer{new_file.suffix}"

            for old_file in local_files:
                try:
                    old_file.unlink(missing_ok=True)
                except OSError:
                    pass
            new_file.replace(final_file)

            if self.settings.refresh_emby_after_download:
                self.emby.refresh_item(movie.id)
            result = ScanResult(
                library, movie.id, movie.name, movie.year,
                "upgraded", f"{old_height}p -> {chosen.title}", str(final_file),
            )
            self._log(progress, result.status, library, movie.name, str(final_file))
            return result
        except Exception as exc:
            result = ScanResult(
                library, movie.id, movie.name, movie.year,
                "upgrade_error", str(exc), str(local_files[0]),
            )
            self._log(progress, result.status, library, movie.name, result.message)
            return result

    def _download_candidate(
        self,
        movie: EmbyMovie,
        candidate: Candidate,
        ignore_minimum: bool = False,
    ) -> Path:
        movie_path = self._mapped_movie_path(movie)
        trailer_dir = select_trailer_directory(movie_path, self.settings.trailer_folder)
        safe_title = "".join(c if c not in '<>:"/\\|?*' else " " for c in movie.name).strip()
        year = f" ({movie.year})" if movie.year else ""
        output_stem = trailer_dir / f"{safe_title}{year} - Trailer"
        file_path = self.downloader.download(
            candidate, output_stem, ignore_minimum=ignore_minimum,
        )
        if self.settings.refresh_emby_after_download:
            self.emby.refresh_item(movie.id)
        return file_path

    def download_manual(
        self,
        item_id: str,
        url: str,
        result_title: str = "",
        ignore_minimum: bool = False,
    ) -> Path:
        if self.settings.dry_run:
            raise RuntimeError("DRY_RUN is active; no files were written")
        if not self.settings.download_trailers:
            raise RuntimeError("DOWNLOAD_TRAILERS is disabled")
        movie = self.emby.get_movie(item_id)
        existing = self._local_files(movie)
        if existing:
            return existing[0]
        candidate = Candidate(
            url=url,
            title=result_title or movie.name,
            duration=None,
            height=None,
            channel=None,
        )
        return self._download_candidate(movie, candidate, ignore_minimum=ignore_minimum)

    def delete_local_trailer(self, item_id: str, requested_path: str) -> None:
        if self.settings.dry_run:
            raise RuntimeError("DRY_RUN is active; deletion is disabled")
        movie = self.emby.get_movie(item_id)
        allowed = {p.resolve() for p in self._local_files(movie)}
        target = Path(requested_path).resolve()
        if target not in allowed:
            raise PermissionError(
                "Requested file is not a detected local trailer for this Emby item"
            )
        target.unlink()
        if self.settings.refresh_emby_after_download:
            self.emby.refresh_item(movie.id)

    @staticmethod
    def serialize(results: Iterable[ScanResult]) -> list[dict]:
        return [asdict(x) for x in results]
