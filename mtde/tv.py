from __future__ import annotations

from pathlib import Path
import re
import subprocess
import unicodedata

from .hardening import is_partial_output_path
from .trailer import Candidate, TrailerDownloader, VIDEO_EXTENSIONS

# Ported directly from upstream MTDP Modules/TV.py. Only Plex-object access is
# replaced elsewhere by the Emby adapter; the TV search/matching/scoring flow
# intentionally stays separate from the movie matcher.
UPSTREAM_TV_SOURCE_COMMIT = "6f87eb0330eb44d55d4dd9133b4facc7479cde42"

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

TRAILER_NOISE_WORDS = {
    "official", "new", "exclusive", "international", "final", "first",
    "full", "main", "original", "extended", "teaser", "trailer",
    "hd", "4k", "uhd", "imax", "dolby", "restoration",
    "tv", "spot", "clip", "promo", "preview", "sneak", "peek",
}

LANGUAGE_CODES = {
    "german": "de", "french": "fr", "spanish": "es", "italian": "it",
    "japanese": "ja", "korean": "ko", "portuguese": "pt", "russian": "ru",
    "chinese": "zh", "english": "en",
}

_RES_STANDARDS = (240, 360, 480, 576, 720, 1080, 1440, 2160)


def is_likely_tv_trailer(video_title: str) -> bool:
    title_lower = video_title.lower()
    return not any(keyword in title_lower for keyword in NEGATIVE_TITLE_KEYWORDS)


def normalize_title_for_match(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.replace("&", " and ")
    text = re.sub(r"[-–—/_]", " ", text)
    text = re.sub(r"[^\w\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def is_standalone_title_match(show_title_lower: str, video_title_lower: str) -> bool:
    if not show_title_lower:
        return False
    pattern = r"\b" + re.escape(show_title_lower) + r"\b"
    match = re.search(pattern, video_title_lower)
    if not match:
        return False
    show_words = show_title_lower.split()
    if len(show_words) <= 2:
        prefix = video_title_lower[:match.start()].strip()
        if prefix:
            prefix = re.sub(r"[|\-:!]", " ", prefix).strip()
            prefix_words = prefix.split()
            significant = [
                word for word in prefix_words
                if word not in TRAILER_NOISE_WORDS and len(word) > 2
            ]
            if significant:
                return False
    return True


def verify_tv_title_match(video_title: str, show_title: str, year: int | None) -> bool:
    """Exact TV-title matcher from upstream MTDP Modules/TV.py."""
    video_title_lower = video_title.lower()
    year_str = str(year) if year else None
    base_title = re.sub(r"\s*\(\d{4}\)\s*", "", show_title).lower().strip()
    sanitized_base = normalize_title_for_match(base_title)
    sanitized_video = normalize_title_for_match(video_title_lower)

    if year_str:
        has_year = year_str in video_title_lower
        if is_standalone_title_match(base_title, video_title_lower) and has_year:
            return True
        if is_standalone_title_match(sanitized_base, sanitized_video) and has_year:
            return True
        parts = base_title.split(":")
        if len(parts) > 1 and all(part.strip() in video_title_lower for part in parts) and has_year:
            return True
        if is_standalone_title_match(base_title, video_title_lower) and "trailer" in video_title_lower:
            if len(base_title.split()) >= 3 or len(base_title) >= 15:
                return True
        if is_standalone_title_match(sanitized_base, sanitized_video) and "trailer" in video_title_lower:
            if len(base_title.split()) >= 3 or len(base_title) >= 15:
                return True
        if "trailer" in video_title_lower:
            if is_standalone_title_match(base_title, video_title_lower):
                return True
            if is_standalone_title_match(sanitized_base, sanitized_video):
                return True
        return False

    if is_standalone_title_match(base_title, video_title_lower):
        return True
    if is_standalone_title_match(sanitized_base, sanitized_video):
        return True
    parts = base_title.split(":")
    if len(parts) > 1 and all(part.strip() in video_title_lower for part in parts):
        return True
    return False


class TVTrailerDownloader(TrailerDownloader):
    """Upstream MTDP TV search flow using the shared yt-dlp transport only."""

    def queries(self, title: str, year: int | None) -> list[str]:
        year_text = str(year) if year is not None else ""
        language_suffix = f" {self.preferred_language}" if self.preferred_language != "original" else ""
        return [
            f"{title} {year_text} TV show official trailer{language_suffix}".strip(),
            f"{title} trailer {year_text} TV series{language_suffix}".strip(),
            f"{title} {year_text} series trailer{language_suffix}".strip(),
        ]

    def search(self, title: str, year: int | None) -> list[Candidate]:
        seen: set[str] = set()
        found: list[Candidate] = []
        opts = self._common_opts() | {"extract_flat": True, "skip_download": True}
        import yt_dlp

        with yt_dlp.YoutubeDL(opts) as ydl:
            for query_index, query in enumerate(self.queries(title, year)):
                data = ydl.extract_info(f"ytsearch{self.search_results}:{query}", download=False) or {}
                for position, entry in enumerate(data.get("entries") or []):
                    if not entry:
                        continue
                    duration = entry.get("duration")
                    if not duration or int(duration) > self.max_duration:
                        continue
                    video_title = str(entry.get("title") or "")
                    if not is_likely_tv_trailer(video_title):
                        continue
                    url = entry.get("webpage_url")
                    if not url and entry.get("id"):
                        url = f"https://www.youtube.com/watch?v={entry['id']}"
                    url = url or entry.get("url")
                    if not url or str(url) in seen:
                        continue
                    seen.add(str(url))
                    found.append(Candidate(
                        url=str(url),
                        title=video_title,
                        duration=int(duration),
                        height=int(entry["height"]) if entry.get("height") else None,
                        channel=entry.get("channel") or entry.get("uploader"),
                        thumbnail=entry.get("thumbnail"),
                        view_count=int(entry["view_count"]) if entry.get("view_count") is not None else None,
                        search_position=position,
                        query_index=query_index,
                    ))
        return found

    def ranked_candidates(
        self,
        candidates: list[Candidate],
        show_title: str,
        year: int | None,
    ) -> list[Candidate]:
        # Upstream TV.py processes queries in order, scores inside each query,
        # then takes the first verified downloadable result.
        ranked: list[Candidate] = []
        seen_urls: set[str] = set()
        for query_index in sorted({candidate.query_index for candidate in candidates}):
            group = [candidate for candidate in candidates if candidate.query_index == query_index]
            group.sort(key=lambda candidate: self._score(candidate, year), reverse=True)
            for candidate in group:
                if candidate.url in seen_urls:
                    continue
                if verify_tv_title_match(candidate.title, show_title, year):
                    seen_urls.add(candidate.url)
                    ranked.append(candidate)
        return ranked


def series_directory(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_dir() else value.parent


def find_series_local_trailers(series_path: str | Path) -> list[Path]:
    """Mirror upstream TV.py: root *-trailer files + any video in Trailers/."""
    root = series_directory(series_path)
    if not root.is_dir():
        return []
    found: list[Path] = []
    seen: set[Path] = set()
    try:
        children = list(root.iterdir())
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

    trailers_dir = root / "Trailers"
    if trailers_dir.is_dir():
        try:
            trailer_children = list(trailers_dir.iterdir())
        except OSError:
            trailer_children = []
        for path in trailer_children:
            try:
                valid = (
                    path.is_file()
                    and path.suffix.casefold() in VIDEO_EXTENSIONS
                    and not is_partial_output_path(path)
                )
            except OSError:
                valid = False
            if valid and path not in seen:
                seen.add(path)
                found.append(path)
    return sorted(found, key=lambda path: str(path).casefold())


def select_series_trailer_directory(series_path: str | Path) -> Path:
    return series_directory(series_path) / "Trailers"


def sanitize_series_title(title: str) -> str:
    # Upstream TV.py only replaces ':' for its filename stem.
    return title.replace(":", " -")


def probe_dimensions(path: str | Path) -> tuple[int, int] | None:
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        dims = proc.stdout.strip().split(",")
        if proc.returncode != 0 or len(dims) != 2:
            return None
        return int(dims[0]), int(dims[1])
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def effective_height(width: int, height: int) -> int:
    return max(height or 0, int((width or 0) * 9 / 16))


def classify_resolution(width: int, height: int) -> str:
    value = effective_height(width, height)
    nearest = min(_RES_STANDARDS, key=lambda standard: abs(standard - value))
    return f"{nearest}p"


def candidate_matches_preferred_language(candidate: Candidate, preferred_language: str) -> bool:
    from .trailer import LANGUAGE_KEYWORDS, _matches_language_keyword

    language = preferred_language.casefold()
    if language == "original":
        return False
    keywords = LANGUAGE_KEYWORDS.get(language, [language])
    title = (candidate.title or "").casefold()
    channel = (candidate.channel or "").casefold()
    return _matches_language_keyword(title, keywords) or _matches_language_keyword(channel, keywords)


def finalize_series_filename(
    path: Path,
    title: str,
    candidate: Candidate,
    preferred_language: str,
) -> Path:
    """Apply upstream TV.py resolution and conditional language tags."""
    dims = probe_dimensions(path)
    resolution = classify_resolution(*dims) if dims else ""
    language_code = LANGUAGE_CODES.get(preferred_language.casefold(), "")
    use_language = bool(language_code and candidate_matches_preferred_language(candidate, preferred_language))

    stem = sanitize_series_title(title)
    parts = [stem]
    if resolution:
        parts.append(resolution)
    if use_language:
        parts.append(language_code)
    final_name = ".".join(parts) + f"-trailer{path.suffix}"
    final_path = path.parent / final_name
    if final_path == path:
        return path
    final_path.unlink(missing_ok=True)
    path.replace(final_path)
    return final_path
