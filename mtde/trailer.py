from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import unicodedata
from typing import Any


VIDEO_EXTENSIONS = {".mkv", ".mp4", ".m4v", ".mov", ".avi", ".webm", ".ts", ".m2ts"}
LEGACY_TRAILER_FOLDER_NAMES = {"trailer", "trailers"}

# Kept in sync with upstream MTDP Movies.py. MTDE only adapts the media-server
# integration; trailer search/matching should remain upstream-compatible.
NEGATIVE_TITLE_KEYWORDS = [
    "reaction", "react", "review", "behind the scenes",
    "making of", "breakdown", "explained", "analysis", "fan made",
    "fan-made", "parody", "spoof", "honest trailer", "honest trailers",
    "everything wrong", "pitch meeting", "recap", "summary",
    "cast interview", "press tour", "red carpet",
    "deleted scene", "bloopers", "gag reel", "easter egg",
    "theory", "theories", "predictions", "ending explained",
    "watch along", "commentary", "video essay", "ranking",
    "top 10", "every trailer", "all trailers", "trailer compilation",
]

# Small MTDE additions based on bad matches observed in Dry Run. These are
# content types, not title heuristics, so they complement rather than replace
# the upstream matching logic.
ADDITIONAL_NEGATIVE_TITLE_KEYWORDS = [
    "live stream", "24 hours", "24 hours+",
    "full episode", "full episodes",
    "concept trailer", "erklärungsvideo",
    "kinderlied", "kinderlieder",
]

PREFERRED_CHANNEL_KEYWORDS = [
    "official", "vevo", "pictures", "studios", "entertainment",
    "warner", "universal", "sony", "disney", "paramount", "lionsgate",
    "a24", "fox", "mgm", "hbo", "netflix", "hulu", "amazon", "apple tv",
    "peacock", "showtime", "starz", "amc", "fx", "bbc", "cbs", "nbc", "abc",
]

TRAILER_NOISE_WORDS = {
    "official", "new", "exclusive", "international", "final", "first",
    "full", "main", "original", "extended", "teaser", "trailer",
    "hd", "4k", "uhd", "imax", "dolby", "restoration",
    "tv", "spot", "clip", "promo", "preview", "sneak", "peek",
}

LANGUAGE_KEYWORDS = {
    "german": ["deutsch", "german", "auf deutsch", "de"],
    "french": ["français", "francais", "french", "vf", "vostfr", "fr"],
    "spanish": ["español", "espanol", "spanish", "castellano", "es"],
    "italian": ["italiano", "italian", "it"],
    "japanese": ["日本語", "japanese", "jp", "ja"],
    "korean": ["한국어", "korean", "ko"],
    "portuguese": ["português", "portugues", "portuguese", "pt", "dublado"],
    "russian": ["русский", "russian", "ru"],
    "chinese": ["中文", "chinese", "zh"],
    "english": ["english", "en"],
}


def is_likely_trailer(video_title: str) -> bool:
    """Upstream MTDP non-trailer title filter plus narrow MTDE safety additions."""
    title_lower = video_title.lower()
    blocked = NEGATIVE_TITLE_KEYWORDS + ADDITIONAL_NEGATIVE_TITLE_KEYWORDS
    return not any(keyword in title_lower for keyword in blocked)


def normalize_title_for_match(text: str) -> str:
    """Normalize titles the same way as upstream MTDP."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.replace("&", " and ")
    text = re.sub(r"[-–—/_]", " ", text)
    text = re.sub(r"[^\w\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def is_standalone_title_match(movie_title_lower: str, video_title_lower: str) -> bool:
    """Upstream MTDP standalone title guard, including short-title protection."""
    if not movie_title_lower:
        return False
    pattern = r"\b" + re.escape(movie_title_lower) + r"\b"
    match = re.search(pattern, video_title_lower)
    if not match:
        return False

    movie_words = movie_title_lower.split()
    if len(movie_words) <= 2:
        prefix = video_title_lower[:match.start()].strip()
        if prefix:
            prefix = re.sub(r"[|\-:!]", " ", prefix).strip()
            prefix_words = prefix.split()
            significant = [
                word
                for word in prefix_words
                if word not in TRAILER_NOISE_WORDS and len(word) > 2
            ]
            if significant:
                return False
    return True


def verify_title_match(video_title: str, movie_title: str, year: int | None) -> bool:
    """Port of upstream MTDP's eight-level movie-title verification."""
    video_title_lower = video_title.lower()
    movie_title_lower = movie_title.lower()
    year_str = str(year) if year is not None else ""
    has_year = bool(year_str and year_str in video_title_lower)

    sanitized_movie = normalize_title_for_match(movie_title_lower)
    sanitized_video = normalize_title_for_match(video_title_lower)

    # Levels 1-5: year present.
    if has_year:
        if is_standalone_title_match(movie_title_lower, video_title_lower):
            return True

        movie_title_parts = movie_title_lower.split(":")
        if len(movie_title_parts) > 1:
            if all(part.strip() in video_title_lower for part in movie_title_parts):
                return True

        if is_standalone_title_match(sanitized_movie, sanitized_video):
            return True

        if len(movie_title_lower) > 20:
            partial_title = movie_title_lower[: int(len(movie_title_lower) * 0.7)]
            if partial_title in video_title_lower:
                return True

        movie_words = set(sanitized_movie.split())
        video_words = set(sanitized_video.split())
        stopwords = {"the", "a", "an", "of", "and", "in", "to", "for", "is", "on", "at"}
        movie_significant = movie_words - stopwords
        if movie_significant and len(movie_significant) >= 2:
            overlap = movie_significant & video_words
            if len(overlap) / len(movie_significant) >= 0.8:
                return True

    # Levels 6-7: no year, require trailer + specific title.
    has_trailer_keyword = "trailer" in video_title_lower
    is_specific_title = len(movie_title_lower.split()) >= 3 or len(movie_title_lower) >= 15

    if has_trailer_keyword and is_specific_title:
        if (
            is_standalone_title_match(movie_title_lower, video_title_lower)
            or is_standalone_title_match(sanitized_movie, sanitized_video)
        ):
            return True

        movie_title_parts = movie_title_lower.split(":")
        if len(movie_title_parts) > 1:
            if all(part.strip() in video_title_lower for part in movie_title_parts):
                return True

    # Level 8: short title without year.
    if has_trailer_keyword and not is_specific_title:
        if is_standalone_title_match(movie_title_lower, video_title_lower):
            return True
        if is_standalone_title_match(sanitized_movie, sanitized_video):
            return True

    return False


def _matches_language_keyword(text: str, keywords: list[str]) -> bool:
    for keyword in keywords:
        if len(keyword) <= 3:
            if re.search(r"\b" + re.escape(keyword) + r"\b", text):
                return True
        elif keyword in text:
            return True
    return False


@dataclass
class Candidate:
    url: str
    title: str
    duration: int | None
    height: int | None
    channel: str | None
    thumbnail: str | None = None
    view_count: int | None = None
    search_position: int = 99
    query_index: int = 0


class TrailerDownloader:
    def __init__(
        self,
        preferred_language: str,
        min_height: int,
        max_height: int,
        max_duration: int,
        search_results: int,
        output_format: str,
        cookies_file: str | None = None,
        show_progress: bool = False,
        custom_options: list[str] | None = None,
    ):
        self.preferred_language = preferred_language.strip().casefold() or "original"
        self.min_height = min_height
        self.max_height = max_height
        self.max_duration = max_duration
        self.search_results = max(15, int(search_results))
        self.output_format = output_format
        self.cookies_file_warning: str | None = None
        self.cookies_file = self._usable_cookies_file(cookies_file)
        self.show_progress = show_progress
        self.custom_options = list(custom_options or [])

    def _usable_cookies_file(self, cookies_file: str | None) -> str | None:
        if not cookies_file:
            return None
        path = Path(cookies_file)
        try:
            if not path.is_file():
                self.cookies_file_warning = (
                    f"COOKIES_FILE ignored: {cookies_file} does not exist or is not a file"
                )
                return None
            with path.open("rb"):
                pass
        except OSError as exc:
            self.cookies_file_warning = (
                f"COOKIES_FILE ignored: {cookies_file} is not readable ({exc})"
            )
            return None
        return str(path)

    def queries(self, title: str, year: int | None) -> list[str]:
        # Same three queries and order as upstream MTDP.
        year_text = str(year) if year is not None else ""
        language_suffix = (
            f" {self.preferred_language}"
            if self.preferred_language != "original"
            else ""
        )
        queries = [
            f"{title} {year_text} official trailer{language_suffix}".strip(),
            f"{title} trailer {year_text}{language_suffix}".strip(),
            f"{title} {year_text} movie trailer{language_suffix}".strip(),
        ]
        return list(dict.fromkeys(queries))

    def _custom_opts(self) -> dict[str, Any]:
        if not self.custom_options:
            return {}
        import yt_dlp

        try:
            parsed = yt_dlp.parse_options(self.custom_options)
            custom = dict(parsed.ydl_opts or {})
        except (Exception, SystemExit) as exc:
            raise ValueError(f"Invalid YT_DLP_CUSTOM_OPTIONS: {exc}") from exc

        protected = {
            "outtmpl", "paths", "download_archive", "skip_download",
            "simulate", "format", "merge_output_format", "cookiefile",
            "progress_hooks", "postprocessor_hooks",
        }
        for key in protected:
            custom.pop(key, None)
        return custom

    def _common_opts(self) -> dict[str, Any]:
        opts: dict[str, Any] = {
            "quiet": not self.show_progress,
            "no_warnings": not self.show_progress,
            "noplaylist": True,
        }
        if self.cookies_file:
            opts["cookiefile"] = self.cookies_file
        opts.update(self._custom_opts())
        return opts

    def search(self, title: str, year: int | None) -> list[Candidate]:
        """Search using the upstream query order and candidate pre-filters."""
        seen: set[str] = set()
        found: list[Candidate] = []
        opts = self._common_opts() | {"extract_flat": True, "skip_download": True}
        import yt_dlp

        with yt_dlp.YoutubeDL(opts) as ydl:
            for query_index, query in enumerate(self.queries(title, year)):
                data = ydl.extract_info(
                    f"ytsearch{self.search_results}:{query}", download=False
                ) or {}
                for position, entry in enumerate(data.get("entries") or []):
                    if not entry:
                        continue
                    duration = entry.get("duration")
                    # Upstream rejects unknown duration and >5 minutes.
                    if not duration or int(duration) > self.max_duration:
                        continue
                    video_title = str(entry.get("title") or "")
                    if not is_likely_trailer(video_title):
                        continue

                    url = entry.get("webpage_url")
                    if not url and entry.get("id"):
                        url = f"https://www.youtube.com/watch?v={entry['id']}"
                    url = url or entry.get("url")
                    if not url or str(url) in seen:
                        continue
                    seen.add(str(url))

                    found.append(
                        Candidate(
                            url=str(url),
                            title=video_title,
                            duration=int(duration),
                            height=int(entry["height"]) if entry.get("height") else None,
                            channel=entry.get("channel") or entry.get("uploader"),
                            thumbnail=entry.get("thumbnail"),
                            view_count=(
                                int(entry["view_count"])
                                if entry.get("view_count") is not None
                                else None
                            ),
                            search_position=position,
                            query_index=query_index,
                        )
                    )
        return found

    def _score(self, candidate: Candidate, year: int | None) -> int:
        """Port of upstream MTDP score_video()."""
        score = 0
        channel = (candidate.channel or "").lower()
        title = (candidate.title or "").lower()

        if "official" in title:
            score += 2
        if "trailer" in title:
            score += 2
        for keyword in PREFERRED_CHANNEL_KEYWORDS:
            if keyword in channel:
                score += 3
                break

        view_count = candidate.view_count or 0
        if view_count > 1_000_000:
            score += 2
        elif view_count > 100_000:
            score += 1

        if candidate.search_position == 0:
            score += 3
        elif candidate.search_position == 1:
            score += 2
        elif candidate.search_position <= 3:
            score += 1

        if year is not None:
            movie_year = str(year)
            years_in_title = re.findall(r"\b((?:19|20)\d{2})\b", title)
            if years_in_title and movie_year not in years_in_title:
                score -= 3

        if self.preferred_language != "original":
            lang_keywords = LANGUAGE_KEYWORDS.get(
                self.preferred_language, [self.preferred_language]
            )
            matches_preferred = _matches_language_keyword(
                title, lang_keywords
            ) or _matches_language_keyword(channel, lang_keywords)
            if matches_preferred:
                score += 25
            else:
                other_language_keywords: list[str] = []
                for language, keywords in LANGUAGE_KEYWORDS.items():
                    if language != self.preferred_language:
                        other_language_keywords.extend(
                            keyword for keyword in keywords if len(keyword) >= 4
                        )
                if _matches_language_keyword(title, other_language_keywords):
                    score -= 15

        return score

    def choose(
        self,
        candidates: list[Candidate],
        movie_title: str,
        year: int | None,
    ) -> Candidate | None:
        """Select like upstream: query-by-query, score first, verify title second."""
        if not candidates:
            return None

        query_indexes = sorted({candidate.query_index for candidate in candidates})
        for query_index in query_indexes:
            group = [
                candidate
                for candidate in candidates
                if candidate.query_index == query_index
            ]
            group.sort(key=lambda candidate: self._score(candidate, year), reverse=True)
            for candidate in group:
                if verify_title_match(candidate.title, movie_title, year):
                    return candidate
        return None

    def download(
        self,
        candidate: Candidate,
        output_stem: Path,
        ignore_minimum: bool = False,
    ) -> Path:
        output_stem.parent.mkdir(parents=True, exist_ok=True)
        outtmpl = str(output_stem) + ".%(ext)s"
        if ignore_minimum:
            fmt = (
                f"bestvideo[height<={self.max_height}]+bestaudio/"
                f"best[height<={self.max_height}]/best"
            )
        else:
            fmt = (
                f"bestvideo[height<={self.max_height}][height>={self.min_height}]+bestaudio/"
                f"best[height<={self.max_height}][height>={self.min_height}]"
            )
        opts = self._common_opts() | {
            "format": fmt,
            "outtmpl": outtmpl,
            "merge_output_format": self.output_format,
            "restrictfilenames": False,
        }
        import yt_dlp

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(candidate.url, download=True)
            requested = info.get("requested_downloads") or []
            paths = [
                Path(item.get("filepath"))
                for item in requested
                if item.get("filepath")
            ]
            prepared = Path(ydl.prepare_filename(info))
        expected = output_stem.with_suffix("." + self.output_format)
        if expected.exists():
            return expected
        for path in paths + [prepared]:
            if path.exists():
                return path
        matches = sorted(
            output_stem.parent.glob(output_stem.name + ".*"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if matches:
            return matches[0]
        raise FileNotFoundError(
            f"yt-dlp completed but no output file was found for {output_stem}"
        )


def probe_video_height(path: str | Path) -> int | None:
    """Return video height with ffprobe, or None when it cannot be determined."""
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=height", "-of", "csv=p=0", str(path),
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if proc.returncode != 0:
            return None
        value = proc.stdout.strip().splitlines()[0]
        return int(value) if value.isdigit() else None
    except (OSError, IndexError, ValueError, subprocess.TimeoutExpired):
        return None


def _movie_directory(movie_path: str | Path) -> Path:
    path = Path(movie_path)
    return path if path.is_dir() else path.parent


def trailer_directories(movie_path: str | Path, trailer_folder: str) -> list[Path]:
    """Return known trailer directories without failing on missing/inaccessible legacy folders."""
    movie_dir = _movie_directory(movie_path)
    if not movie_dir.is_dir():
        return []

    accepted = {trailer_folder.casefold(), *LEGACY_TRAILER_FOLDER_NAMES}
    found: list[Path] = []
    try:
        for child in movie_dir.iterdir():
            try:
                if child.is_dir() and child.name.casefold() in accepted:
                    found.append(child)
            except OSError:
                continue
    except OSError:
        return []

    return sorted(
        found,
        key=lambda p: (
            p.name.casefold() != trailer_folder.casefold(),
            p.name.casefold(),
            p.name,
        ),
    )


def find_local_trailers(movie_path: str | Path, trailer_folder: str) -> list[Path]:
    """Find local trailers in configured and legacy Trailer/Trailers folders, case-insensitively."""
    files: list[Path] = []
    seen: set[Path] = set()
    for trailer_dir in trailer_directories(movie_path, trailer_folder):
        try:
            children = list(trailer_dir.iterdir())
        except OSError:
            continue
        for path in children:
            try:
                is_video = (
                    path.is_file() and path.suffix.casefold() in VIDEO_EXTENSIONS
                )
            except OSError:
                continue
            if is_video and path not in seen:
                seen.add(path)
                files.append(path)
    return sorted(files, key=lambda p: str(p).casefold())


def select_trailer_directory(movie_path: str | Path, trailer_folder: str) -> Path:
    """Reuse an existing plural trailers folder (any case); otherwise use the configured folder."""
    movie_dir = _movie_directory(movie_path)
    configured = movie_dir / trailer_folder
    if configured.is_dir():
        return configured

    for existing in trailer_directories(movie_path, trailer_folder):
        if existing.name.casefold() == "trailers":
            return existing

    return configured
