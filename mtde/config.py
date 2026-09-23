from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class PathMapping:
    emby: str
    local: str

    def map(self, path: str) -> str:
        src = self.emby.rstrip("/\\")
        if path == src:
            return self.local.rstrip("/\\")
        for sep in ("/", "\\"):
            prefix = src + sep
            if path.startswith(prefix):
                suffix = path[len(prefix):].replace("\\", "/")
                return str(Path(self.local) / Path(suffix))
        return path


@dataclass
class Settings:
    emby_url: str
    emby_api_key: str
    movie_libraries: list[str]
    preferred_language: str = "german deutsch"
    download_trailers: bool = True
    dry_run: bool = True
    trailer_folder: str = "trailers"
    trailer_file_format: str = "mkv"
    trailer_resolution_min: int = 1080
    trailer_resolution_max: int = 2160
    max_trailer_duration: int = 300
    search_results: int = 8
    skip_genres: list[str] = field(default_factory=list)
    refresh_emby_after_download: bool = True
    schedule_hours: int = 0
    web_port: int = 2121
    path_mappings: list[PathMapping] = field(default_factory=list)
    cookies_file: str | None = None

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Settings":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        mappings = [
            PathMapping(str(x["emby"]), str(x["local"]))
            for x in raw.get("PATH_MAPPINGS", [])
            if isinstance(x, dict) and x.get("emby") and x.get("local")
        ]
        libs = raw.get("MOVIE_LIBRARIES", [])
        if libs and isinstance(libs[0], dict):
            libs = [x.get("name") for x in libs if x.get("name")]
        settings = cls(
            emby_url=str(raw.get("EMBY_URL", "")).rstrip("/"),
            emby_api_key=str(raw.get("EMBY_API_KEY", "")),
            movie_libraries=[str(x) for x in libs],
            preferred_language=str(raw.get("PREFERRED_LANGUAGE", "german deutsch")),
            download_trailers=bool(raw.get("DOWNLOAD_TRAILERS", True)),
            dry_run=bool(raw.get("DRY_RUN", True)),
            trailer_folder=str(raw.get("TRAILER_FOLDER", "trailers")),
            trailer_file_format=str(raw.get("TRAILER_FILE_FORMAT", "mkv")).lower(),
            trailer_resolution_min=int(raw.get("TRAILER_RESOLUTION_MIN", 1080)),
            trailer_resolution_max=int(raw.get("TRAILER_RESOLUTION_MAX", 2160)),
            max_trailer_duration=int(raw.get("MAX_TRAILER_DURATION", 300)),
            search_results=int(raw.get("SEARCH_RESULTS", 8)),
            skip_genres=[str(x) for x in raw.get("SKIP_GENRES", [])],
            refresh_emby_after_download=bool(raw.get("REFRESH_EMBY_AFTER_DOWNLOAD", True)),
            schedule_hours=int(raw.get("SCHEDULE_HOURS", 0)),
            web_port=int(raw.get("WEB_PORT", 2121)),
            path_mappings=mappings,
            cookies_file=raw.get("COOKIES_FILE") or None,
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not self.emby_url:
            raise ValueError("EMBY_URL is required")
        if not self.emby_api_key:
            raise ValueError("EMBY_API_KEY is required")
        if not self.movie_libraries:
            raise ValueError("At least one MOVIE_LIBRARIES entry is required")
        if self.trailer_file_format not in {"mkv", "mp4"}:
            raise ValueError("TRAILER_FILE_FORMAT must be mkv or mp4")
        if self.trailer_resolution_min > self.trailer_resolution_max:
            raise ValueError("TRAILER_RESOLUTION_MIN cannot exceed TRAILER_RESOLUTION_MAX")
        if not self.trailer_folder or "/" in self.trailer_folder or "\\" in self.trailer_folder:
            raise ValueError("TRAILER_FOLDER must be a single folder name")

    def map_path(self, path: str) -> str:
        for mapping in self.path_mappings:
            mapped = mapping.map(path)
            if mapped != path:
                return mapped
        return path
