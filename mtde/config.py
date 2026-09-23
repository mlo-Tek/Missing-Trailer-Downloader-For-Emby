from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from croniter import croniter


_LANGUAGE_ALIASES = {
    "": "original",
    "original": "original",
    "english": "english",
    "german": "german",
    "german deutsch": "german",
    "deutsch": "german",
    "french": "french",
    "spanish": "spanish",
    "italian": "italian",
    "japanese": "japanese",
    "korean": "korean",
    "portuguese": "portuguese",
    "russian": "russian",
    "chinese": "chinese",
}


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

    dry_run: bool = True
    emby_timeout: int = 120

    check_remote_trailers: bool = False
    download_trailers: bool = True
    preferred_language: str = "original"
    refresh_emby_after_download: bool = True
    show_ytdlp_progress: bool = False
    trailer_file_format: str = "mkv"
    trailer_resolution_min: int = 1080
    trailer_resolution_max: int = 2160
    max_trailer_duration: int = 300
    search_results: int = 15
    trailer_folder: str = "trailers"
    yt_dlp_custom_options: list[str] = field(default_factory=list)
    cookies_file: str | None = None
    upgrade_trailers: str = "off"

    schedule_type: str = "disabled"
    schedule_hours: int = 24
    schedule_cron: str = ""
    new_item_detection: bool = False
    new_item_delay: int = 60

    web_port: int = 2121
    path_mappings: list[PathMapping] = field(default_factory=list)

    # Compatibility with the early MTDE config format.
    skip_genres: list[str] = field(default_factory=list)
    movie_genres_to_skip: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Settings":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}

        mappings = [
            PathMapping(str(x["emby"]), str(x["local"]))
            for x in raw.get("PATH_MAPPINGS", [])
            if isinstance(x, dict) and x.get("emby") and x.get("local")
        ]

        legacy_genres = [str(x) for x in raw.get("SKIP_GENRES", [])]
        raw_libs = raw.get("MOVIE_LIBRARIES", []) or []
        movie_libraries: list[str] = []
        per_library: dict[str, list[str]] = {}
        for entry in raw_libs:
            if isinstance(entry, dict):
                name = str(entry.get("name") or "").strip()
                if not name:
                    continue
                movie_libraries.append(name)
                per_library[name] = [str(x) for x in (entry.get("genres_to_skip") or [])]
            else:
                name = str(entry).strip()
                if name:
                    movie_libraries.append(name)
                    per_library[name] = list(legacy_genres)

        language_raw = str(raw.get("PREFERRED_LANGUAGE", "original")).strip().casefold()
        preferred_language = _LANGUAGE_ALIASES.get(language_raw, language_raw or "original")

        settings = cls(
            emby_url=str(raw.get("EMBY_URL", "")).rstrip("/"),
            emby_api_key=str(raw.get("EMBY_API_KEY", "")),
            movie_libraries=movie_libraries,
            dry_run=bool(raw.get("DRY_RUN", True)),
            emby_timeout=int(raw.get("EMBY_TIMEOUT", 120)),
            check_remote_trailers=bool(raw.get("CHECK_REMOTE_TRAILERS", False)),
            download_trailers=bool(raw.get("DOWNLOAD_TRAILERS", True)),
            preferred_language=preferred_language,
            refresh_emby_after_download=bool(raw.get("REFRESH_EMBY_AFTER_DOWNLOAD", raw.get("REFRESH_METADATA", True))),
            show_ytdlp_progress=bool(raw.get("SHOW_YT_DLP_PROGRESS", False)),
            trailer_file_format=str(raw.get("TRAILER_FILE_FORMAT", "mkv")).lower(),
            trailer_resolution_min=int(raw.get("TRAILER_RESOLUTION_MIN", 1080)),
            trailer_resolution_max=int(raw.get("TRAILER_RESOLUTION_MAX", 2160)),
            max_trailer_duration=int(raw.get("MAX_TRAILER_DURATION", 300)),
            search_results=max(15, int(raw.get("SEARCH_RESULTS", 15))),
            trailer_folder=str(raw.get("TRAILER_FOLDER", "trailers")),
            yt_dlp_custom_options=[str(x) for x in raw.get("YT_DLP_CUSTOM_OPTIONS", [])],
            cookies_file=raw.get("COOKIES_FILE") or None,
            upgrade_trailers=str(raw.get("UPGRADE_TRAILERS", "off")).lower(),
            schedule_type=str(raw.get("SCHEDULE_TYPE", "disabled")).lower(),
            schedule_hours=int(raw.get("SCHEDULE_HOURS", 24)),
            schedule_cron=str(raw.get("SCHEDULE_CRON", "")).strip(),
            new_item_detection=bool(raw.get("NEW_ITEM_DETECTION", False)),
            new_item_delay=int(raw.get("NEW_ITEM_DELAY", 60)),
            web_port=int(raw.get("WEB_PORT", 2121)),
            path_mappings=mappings,
            skip_genres=legacy_genres,
            movie_genres_to_skip=per_library,
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
        if self.emby_timeout < 5:
            raise ValueError("EMBY_TIMEOUT must be at least 5 seconds")
        if self.trailer_file_format not in {"mkv", "mp4"}:
            raise ValueError("TRAILER_FILE_FORMAT must be mkv or mp4")
        if self.trailer_resolution_min > self.trailer_resolution_max:
            raise ValueError("TRAILER_RESOLUTION_MIN cannot exceed TRAILER_RESOLUTION_MAX")
        if self.trailer_resolution_min < 0 or self.trailer_resolution_max <= 0:
            raise ValueError("Trailer resolutions must be positive")
        if self.max_trailer_duration <= 0:
            raise ValueError("MAX_TRAILER_DURATION must be greater than 0")
        if self.search_results < 15:
            raise ValueError("SEARCH_RESULTS must be at least 15 to match upstream MTDP search depth")
        if not self.trailer_folder or "/" in self.trailer_folder or "\\" in self.trailer_folder:
            raise ValueError("TRAILER_FOLDER must be a single folder name")
        if self.upgrade_trailers not in {"off", "local"}:
            raise ValueError("UPGRADE_TRAILERS must be off or local")
        if self.schedule_type not in {"disabled", "hours", "cron"}:
            raise ValueError("SCHEDULE_TYPE must be disabled, hours or cron")
        if self.schedule_hours < 1:
            raise ValueError("SCHEDULE_HOURS must be at least 1")
        if self.schedule_type == "cron":
            if not self.schedule_cron:
                raise ValueError("SCHEDULE_CRON is required when SCHEDULE_TYPE is cron")
            if not croniter.is_valid(self.schedule_cron):
                raise ValueError("SCHEDULE_CRON is not a valid 5-field cron expression")
        if self.new_item_delay < 0:
            raise ValueError("NEW_ITEM_DELAY must be 0 or greater")

    def genres_for_library(self, name: str) -> list[str]:
        return list(self.movie_genres_to_skip.get(name, self.skip_genres))

    def map_path(self, path: str) -> str:
        for mapping in self.path_mappings:
            mapped = mapping.map(path)
            if mapped != path:
                return mapped
        return path
