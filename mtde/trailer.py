from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
from typing import Any


VIDEO_EXTENSIONS = {".mkv", ".mp4", ".m4v", ".mov", ".avi", ".webm", ".ts", ".m2ts"}
LEGACY_TRAILER_FOLDER_NAMES = {"trailer", "trailers"}

_LANGUAGE_SEARCH = {
    "original": "",
    "english": "english",
    "german": "german deutsch",
    "french": "french français",
    "spanish": "spanish español",
    "italian": "italian italiano",
    "japanese": "japanese",
    "korean": "korean",
    "portuguese": "portuguese português",
    "russian": "russian",
    "chinese": "chinese",
}

_TITLE_STOPWORDS = {
    "a", "an", "and", "auf", "auch", "by", "das", "de", "del", "der", "des",
    "die", "ein", "eine", "einer", "eines", "for", "für", "im", "in", "la",
    "le", "mit", "of", "oder", "on", "the", "und", "von", "zu", "zum", "zur",
}

_REJECT_PATTERNS = [
    r"\b24\s*hours?\b",
    r"\bhours\+\b",
    r"\blive\b",
    r"\bfull\s+episodes?\b",
    r"\bepisodes?\b",
    r"\btheme\b",
    r"\bcover\b",
    r"\bfan\s*trailer\b",
    r"\bconcept\b",
    r"\breaction\b",
    r"\breview\b",
    r"\bexplained\b",
    r"\berklärungsvideo\b",
    r"\bwerbung\b",
    r"\bkinderlieder?\b",
    r"\bmitsingen\b",
]


@dataclass
class Candidate:
    url: str
    title: str
    duration: int | None
    height: int | None
    channel: str | None
    thumbnail: str | None = None
    view_count: int | None = None


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
        self.search_results = search_results
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
                self.cookies_file_warning = f"COOKIES_FILE ignored: {cookies_file} does not exist or is not a file"
                return None
            with path.open("rb"):
                pass
        except OSError as exc:
            self.cookies_file_warning = f"COOKIES_FILE ignored: {cookies_file} is not readable ({exc})"
            return None
        return str(path)

    @property
    def language_terms(self) -> str:
        return _LANGUAGE_SEARCH.get(self.preferred_language, self.preferred_language)

    def queries(self, title: str, year: int | None) -> list[str]:
        year_text = f" {year}" if year else ""
        lang_text = f" {self.language_terms}" if self.language_terms else ""
        queries = [
            f"{title}{year_text} official trailer{lang_text}".strip(),
            f"{title}{year_text} trailer{lang_text}".strip(),
            f"{title}{year_text} official trailer".strip(),
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

        # MTDE owns these values because changing them could bypass the configured
        # media path, format, safety or download behavior.
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
        seen: set[str] = set()
        found: list[Candidate] = []
        opts = self._common_opts() | {"extract_flat": True, "skip_download": True}
        import yt_dlp

        with yt_dlp.YoutubeDL(opts) as ydl:
            for query in self.queries(title, year):
                data = ydl.extract_info(f"ytsearch{self.search_results}:{query}", download=False) or {}
                for entry in data.get("entries") or []:
                    if not entry:
                        continue
                    url = entry.get("webpage_url")
                    if not url and entry.get("id"):
                        url = f"https://www.youtube.com/watch?v={entry['id']}"
                    url = url or entry.get("url")
                    if not url or str(url) in seen:
                        continue
                    seen.add(str(url))
                    duration = entry.get("duration")
                    if duration is not None and int(duration) > self.max_duration:
                        continue
                    found.append(Candidate(
                        url=str(url),
                        title=str(entry.get("title") or ""),
                        duration=int(duration) if duration is not None else None,
                        height=int(entry["height"]) if entry.get("height") else None,
                        channel=entry.get("channel") or entry.get("uploader"),
                        thumbnail=entry.get("thumbnail"),
                        view_count=int(entry["view_count"]) if entry.get("view_count") is not None else None,
                    ))
                if found:
                    break
        return found

    @staticmethod
    def _tokens(text: str) -> list[str]:
        tokens: list[str] = []
        for token in re.findall(r"[\wÀ-ÿ]+", text.casefold()):
            if token in _TITLE_STOPWORDS:
                continue
            if token.isdigit() or len(token) > 2:
                tokens.append(token)
        return tokens

    @classmethod
    def _title_match_ratio(cls, candidate_title: str, movie_title: str) -> float:
        movie_tokens = cls._tokens(movie_title)
        if not movie_tokens:
            return 0.0
        candidate_tokens = set(cls._tokens(candidate_title))
        if not candidate_tokens:
            return 0.0
        digit_tokens = {token for token in movie_tokens if token.isdigit()}
        if digit_tokens and not digit_tokens.issubset(candidate_tokens):
            return 0.0
        return len(set(movie_tokens) & candidate_tokens) / len(set(movie_tokens))

    @classmethod
    def is_safe_candidate(cls, candidate: Candidate, movie_title: str, year: int | None) -> bool:
        text = candidate.title.casefold()
        if any(re.search(pattern, text) for pattern in _REJECT_PATTERNS):
            return False

        years = {int(match) for match in re.findall(r"\b(19\d{2}|20\d{2})\b", text)}
        if year and years and year not in years:
            return False

        # Main guard: the candidate must meaningfully contain the requested movie
        # title. This intentionally skips weak franchise-only matches instead of
        # downloading a wrong sequel, live stream, theme, cover or unrelated clip.
        ratio = cls._title_match_ratio(candidate.title, movie_title)
        if ratio >= 0.50:
            return True

        # Some libraries keep bilingual titles separated by dash/colon. Accept a
        # unique two-word segment when it is fully present, but do not use this to
        # accept one-word franchise-only matches such as only "Asterix" or "Zogg".
        for segment in re.split(r"\s[-:–—]\s", movie_title):
            segment_tokens = cls._tokens(segment)
            if len(segment_tokens) >= 2:
                segment_ratio = cls._title_match_ratio(candidate.title, segment)
                if segment_ratio >= 0.90:
                    return True
        return False

    @staticmethod
    def _score(candidate: Candidate, movie_title: str, year: int | None, language: str) -> int:
        text = candidate.title.casefold()
        score = 0
        if "official" in text or "offiziell" in text:
            score += 30
        if "trailer" in text:
            score += 20
        if year and str(year) in text:
            score += 8
        words = [w.casefold() for w in re.findall(r"[\wÀ-ÿ]+", movie_title) if len(w) > 2]
        score += sum(3 for w in words if w in text)
        lang_terms = _LANGUAGE_SEARCH.get(language.casefold(), language.casefold()).split()
        for term in lang_terms:
            if len(term) > 2 and term in text:
                score += 7
        if "teaser" in text:
            score -= 8
        if "reaction" in text or "review" in text:
            score -= 25
        if "theme" in text or "cover" in text or "fan trailer" in text:
            score -= 40
        return score

    def choose(self, candidates: list[Candidate], movie_title: str, year: int | None) -> Candidate | None:
        safe_candidates = [
            candidate for candidate in candidates
            if self.is_safe_candidate(candidate, movie_title, year)
        ]
        if not safe_candidates:
            return None
        return max(safe_candidates, key=lambda c: self._score(c, movie_title, year, self.preferred_language))

    def download(self, candidate: Candidate, output_stem: Path, ignore_minimum: bool = False) -> Path:
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
            paths = [Path(x.get("filepath")) for x in requested if x.get("filepath")]
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
        raise FileNotFoundError(f"yt-dlp completed but no output file was found for {output_stem}")


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

    return sorted(found, key=lambda p: (p.name.casefold() != trailer_folder.casefold(), p.name.casefold(), p.name))


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
                is_video = path.is_file() and path.suffix.casefold() in VIDEO_EXTENSIONS
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
