from __future__ import annotations

from pathlib import Path
from typing import Any

from .hardening import (
    _config_root,
    _parse_download_history,
    candidate_safety_reason,
    is_partial_output_path,
)
from .trailer import find_local_trailers, trailer_directories


def classify_suspicious_local_files(
    local_files: list[Path],
    history: dict[str, dict[str, Any]],
    movie_title: str,
    year: int | None,
) -> list[tuple[Path, str]]:
    """Return only local trailers that MTDE can prove are unsafe.

    A normal local trailer is never removed merely because its title looks odd.
    Automatic repair requires an exact path match in MTDE's persistent download
    history plus a candidate title that fails the current safety layer.
    """
    suspicious: list[tuple[Path, str]] = []
    for path in local_files:
        record = history.get(str(path))
        if not record:
            continue
        candidate = str(record.get("candidate") or "").strip()
        if not candidate:
            continue
        reason = candidate_safety_reason(candidate, movie_title, year)
        if reason:
            suspicious.append((path, reason))
    return suspicious


def _fragment_files(service, movie) -> list[Path]:
    found: list[Path] = []
    mapped = service._mapped_movie_path(movie)
    for trailer_dir in trailer_directories(mapped, service.settings.trailer_folder):
        try:
            children = list(trailer_dir.iterdir())
        except OSError:
            continue
        for path in children:
            try:
                if path.is_file() and is_partial_output_path(path):
                    found.append(path)
            except OSError:
                continue
    return found


def _path_is_inside_movie(service, movie, path: Path) -> bool:
    mapped = service._mapped_movie_path(movie)
    movie_dir = mapped if mapped.is_dir() else mapped.parent
    try:
        resolved_movie = movie_dir.resolve()
        resolved_path = path.resolve()
    except OSError:
        return False
    return resolved_movie in resolved_path.parents


def _drop_probe_cache(service, path: Path) -> None:
    try:
        with service._probe_cache_lock:
            service._probe_cache.pop(str(path), None)
    except Exception:
        pass


def install_auto_repair() -> None:
    """Make the normal scan repair only proven-bad MTDE-owned trailers.

    The separate MTDE Repair UI remains useful as an audit tool, but a normal
    scan no longer needs it for files whose provenance and unsafe source are
    already unambiguous in MTDE's own persistent logs.
    """
    from . import service as service_module

    if getattr(service_module, "_mtde_auto_repair_installed", False):
        return

    original_scan = service_module.MTDE.scan
    original_process_movie = service_module.MTDE._process_movie

    def scan_with_repair_history(self, *args, **kwargs):
        # Parse once per scan, not once per movie. Old successful downloads stay
        # traceable across later HAS_LOCAL_TRAILER-only scans.
        self._auto_repair_history = _parse_download_history(_config_root() / "logs")
        try:
            return original_scan(self, *args, **kwargs)
        finally:
            self.__dict__.pop("_auto_repair_history", None)

    def process_movie_with_auto_repair(self, library, movie, do_download, progress=None):
        mapped = self._mapped_movie_path(movie)
        local_files = find_local_trailers(mapped, self.settings.trailer_folder)
        history = getattr(self, "_auto_repair_history", {})
        suspicious = classify_suspicious_local_files(local_files, history, movie.name, movie.year)
        fragments = _fragment_files(self, movie)

        # Fragments are deterministic yt-dlp leftovers. They are never valid
        # final trailers and are already ignored by find_local_trailers().
        for path in fragments:
            if do_download:
                if not _path_is_inside_movie(self, movie, path):
                    self._log(progress, "repair_fragment_error", library, movie.name, f"refusing path outside movie folder: {path}")
                    continue
                try:
                    path.unlink(missing_ok=True)
                    _drop_probe_cache(self, path)
                    self._log(progress, "repair_fragment", library, movie.name, str(path))
                except OSError as exc:
                    self._log(progress, "repair_fragment_error", library, movie.name, f"{path} | {exc}")
            else:
                self._log(progress, "would_repair_fragment", library, movie.name, str(path))

        if not suspicious:
            return original_process_movie(self, library, movie, do_download, progress=progress)

        # In Dry Run / non-download mode, do not touch the file. Report exactly
        # what a real run would repair. This intentionally wins over
        # HAS_LOCAL_TRAILER so the stale bad file is visible in the run log.
        if not do_download:
            details = []
            for path, reason in suspicious:
                record = history.get(str(path), {})
                candidate = str(record.get("candidate") or "")
                message = f"{path} | {reason} | source: {candidate}"
                self._log(progress, "would_repair_suspicious_trailer", library, movie.name, message)
                details.append(message)
            return service_module.ScanResult(
                library,
                movie.id,
                movie.name,
                movie.year,
                "would_repair_suspicious_trailer",
                "; ".join(details),
                str(suspicious[0][0]),
            )

        deleted_any = False
        for path, reason in suspicious:
            record = history.get(str(path), {})
            candidate = str(record.get("candidate") or "")
            if not _path_is_inside_movie(self, movie, path):
                self._log(
                    progress,
                    "repair_suspicious_error",
                    library,
                    movie.name,
                    f"refusing path outside movie folder: {path}",
                )
                continue
            try:
                path.unlink(missing_ok=True)
                _drop_probe_cache(self, path)
                deleted_any = True
                self._log(
                    progress,
                    "repair_suspicious_trailer",
                    library,
                    movie.name,
                    f"deleted {path} | {reason} | source: {candidate}",
                )
            except OSError as exc:
                self._log(
                    progress,
                    "repair_suspicious_error",
                    library,
                    movie.name,
                    f"{path} | {exc}",
                )

        if deleted_any:
            try:
                self.emby.refresh_item(movie.id)
                self._log(progress, "repair_emby_refresh", library, movie.name, "refresh requested")
            except Exception as exc:
                self._log(progress, "repair_emby_warning", library, movie.name, str(exc))

        # Re-enter the normal MTDE flow after deletion. If no safe replacement
        # can be found/downloaded, the movie remains Missing instead of keeping
        # a known-wrong trailer.
        return original_process_movie(self, library, movie, do_download, progress=progress)

    service_module.MTDE.scan = scan_with_repair_history
    service_module.MTDE._process_movie = process_movie_with_auto_repair
    service_module._mtde_auto_repair_installed = True
