from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import threading
from typing import Iterable

from .config import Settings
from .emby import EmbyClient, EmbyMovie
from .trailer import Candidate, TrailerDownloader, find_local_trailers, select_trailer_directory


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
        self._scan_lock = threading.Lock()
        self.update_settings(settings)

    def update_settings(self, settings: Settings) -> None:
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

    def _local_files(self, movie: EmbyMovie) -> list[Path]:
        return find_local_trailers(self._mapped_movie_path(movie), self.settings.trailer_folder)

    def movie_ui(self, library: str, movie: EmbyMovie) -> dict:
        local_files = self._local_files(movie)
        if movie.local_trailer_count > 0 or local_files:
            status = "local"
        elif movie.remote_trailers:
            status = "plexpass"
        else:
            status = "missing"
        trailer_file = str(local_files[0]) if local_files else ""
        return {
            "ratingKey": movie.id,
            "title": movie.name,
            "year": movie.year,
            "library": library,
            "genres": movie.genres,
            "genreSkipped": bool(self._skip_genre(movie)),
            "trailerStatus": status,
            "trailerFile": trailer_file,
            "trailerResolution": "",
            "trailerLanguage": "",
            "mediaPath": str(self._mapped_movie_path(movie)),
            "type": "movie",
            "dateAdded": movie.date_created,
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
            "actors": [str(x.get("Name") or "") for x in people if str(x.get("Type") or "").casefold() == "actor"],
            "plexpassExtraKey": "",
        })
        return ui

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
                library, movie.id, movie.name, movie.year, "has_local_trailer",
                "; ".join(message_parts),
                str(local_files[0]) if local_files else None,
            )

        skipped = self._skip_genre(movie)
        if skipped:
            return ScanResult(library, movie.id, movie.name, movie.year, "genre_skipped", skipped)

        movie_dir = mapped_movie_path if mapped_movie_path.is_dir() else mapped_movie_path.parent
        if not movie_dir.exists():
            return ScanResult(library, movie.id, movie.name, movie.year, "path_missing", str(movie_dir))

        try:
            candidates = self.downloader.search(movie.name, movie.year)
            chosen = self.downloader.choose(candidates, movie.name, movie.year)
            if not chosen:
                return ScanResult(library, movie.id, movie.name, movie.year, "no_match")
            if not do_download:
                return ScanResult(library, movie.id, movie.name, movie.year, "would_download", chosen.title)

            file_path = self._download_candidate(movie, chosen)
            return ScanResult(library, movie.id, movie.name, movie.year, "downloaded", chosen.title, str(file_path))
        except Exception as exc:
            return ScanResult(library, movie.id, movie.name, movie.year, "error", str(exc))

    def _download_candidate(self, movie: EmbyMovie, candidate: Candidate) -> Path:
        movie_path = self._mapped_movie_path(movie)
        trailer_dir = select_trailer_directory(movie_path, self.settings.trailer_folder)
        safe_title = "".join(c if c not in '<>:"/\\|?*' else " " for c in movie.name).strip()
        year = f" ({movie.year})" if movie.year else ""
        output_stem = trailer_dir / f"{safe_title}{year} - Trailer"
        file_path = self.downloader.download(candidate, output_stem)
        if self.settings.refresh_emby_after_download:
            self.emby.refresh_item(movie.id)
        return file_path

    def download_manual(self, item_id: str, url: str, result_title: str = "") -> Path:
        if self.settings.dry_run:
            raise RuntimeError("DRY_RUN is active; no files were written")
        if not self.settings.download_trailers:
            raise RuntimeError("DOWNLOAD_TRAILERS is disabled")
        movie = self.emby.get_movie(item_id)
        existing = self._local_files(movie)
        if movie.local_trailer_count > 0 or existing:
            if existing:
                return existing[0]
            raise RuntimeError("Emby already reports a local trailer for this movie")
        candidate = Candidate(url=url, title=result_title or movie.name, duration=None, height=None, channel=None)
        return self._download_candidate(movie, candidate)

    def delete_local_trailer(self, item_id: str, requested_path: str) -> None:
        if self.settings.dry_run:
            raise RuntimeError("DRY_RUN is active; deletion is disabled")
        movie = self.emby.get_movie(item_id)
        allowed = {p.resolve() for p in self._local_files(movie)}
        target = Path(requested_path).resolve()
        if target not in allowed:
            raise PermissionError("Requested file is not a detected local trailer for this Emby item")
        target.unlink()
        if self.settings.refresh_emby_after_download:
            self.emby.refresh_item(movie.id)

    @staticmethod
    def serialize(results: Iterable[ScanResult]) -> list[dict]:
        return [asdict(x) for x in results]
