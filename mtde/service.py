from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import threading
from typing import Iterable

from .config import Settings
from .emby import EmbyClient, EmbyMovie
from .trailer import TrailerDownloader, find_local_trailers, select_trailer_directory


@dataclass
class ScanResult:
    library: str
    item_id: str
    title: str
    year: int | None
    status: str
    message: str = ""
    trailer_path: str | None = None


class MTDE:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.emby = EmbyClient(settings.emby_url, settings.emby_api_key)
        self.downloader = TrailerDownloader(
            preferred_language=settings.preferred_language,
            min_height=settings.trailer_resolution_min,
            max_height=settings.trailer_resolution_max,
            max_duration=settings.max_trailer_duration,
            search_results=settings.search_results,
            output_format=settings.trailer_file_format,
            cookies_file=settings.cookies_file,
        )
        self._scan_lock = threading.Lock()

    def test_connection(self) -> dict:
        return self.emby.system_info()

    def _mapped_movie_path(self, movie: EmbyMovie) -> Path:
        return Path(self.settings.map_path(movie.path))

    def _skip_genre(self, movie: EmbyMovie) -> str | None:
        blocked = {x.casefold() for x in self.settings.skip_genres}
        for genre in movie.genres:
            if genre.casefold() in blocked:
                return genre
        return None

    def scan(self, download: bool | None = None) -> list[ScanResult]:
        if not self._scan_lock.acquire(blocking=False):
            raise RuntimeError("A scan is already running")
        try:
            requested_download = self.settings.download_trailers if download is None else bool(download)
            do_download = requested_download and self.settings.download_trailers and not self.settings.dry_run
            results: list[ScanResult] = []
            for library in self.settings.movie_libraries:
                try:
                    movies = self.emby.iter_movies(library)
                    for movie in movies:
                        results.append(self._process_movie(library, movie, do_download))
                except Exception as exc:
                    results.append(ScanResult(library, "", library, None, "library_error", str(exc)))
            return results
        finally:
            self._scan_lock.release()

    def _process_movie(self, library: str, movie: EmbyMovie, do_download: bool) -> ScanResult:
        mapped_movie_path = self._mapped_movie_path(movie)
        local_files = find_local_trailers(mapped_movie_path, self.settings.trailer_folder)
        if movie.local_trailer_count > 0 or local_files:
            message_parts: list[str] = []
            if movie.local_trailer_count > 0:
                message_parts.append(f"Emby LocalTrailerCount={movie.local_trailer_count}")
            if local_files:
                message_parts.append(f"local file: {local_files[0]}")
                if len(local_files) > 1:
                    message_parts.append(f"+{len(local_files) - 1} more")
            return ScanResult(
                library,
                movie.id,
                movie.name,
                movie.year,
                "has_local_trailer",
                "; ".join(message_parts),
                str(local_files[0]) if local_files else None,
            )

        skipped = self._skip_genre(movie)
        if skipped:
            return ScanResult(library, movie.id, movie.name, movie.year, "genre_skipped", skipped)

        movie_path = mapped_movie_path
        movie_dir = movie_path if movie_path.is_dir() else movie_path.parent
        if not movie_dir.exists():
            return ScanResult(library, movie.id, movie.name, movie.year, "path_missing", str(movie_dir))

        try:
            candidates = self.downloader.search(movie.name, movie.year)
            chosen = self.downloader.choose(candidates, movie.name, movie.year)
            if not chosen:
                return ScanResult(library, movie.id, movie.name, movie.year, "no_match")
            if not do_download:
                return ScanResult(library, movie.id, movie.name, movie.year, "would_download", chosen.title)

            trailer_dir = select_trailer_directory(movie_path, self.settings.trailer_folder)
            safe_title = "".join(c if c not in '<>:"/\\|?*' else " " for c in movie.name).strip()
            year = f" ({movie.year})" if movie.year else ""
            output_stem = trailer_dir / f"{safe_title}{year} - Trailer"
            file_path = self.downloader.download(chosen, output_stem)
            if self.settings.refresh_emby_after_download:
                self.emby.refresh_item(movie.id)
            return ScanResult(library, movie.id, movie.name, movie.year, "downloaded", chosen.title, str(file_path))
        except Exception as exc:
            return ScanResult(library, movie.id, movie.name, movie.year, "error", str(exc))

    @staticmethod
    def serialize(results: Iterable[ScanResult]) -> list[dict]:
        return [asdict(x) for x in results]
