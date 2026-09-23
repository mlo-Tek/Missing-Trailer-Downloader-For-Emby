from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any



VIDEO_EXTENSIONS = {".mkv", ".mp4", ".m4v", ".mov", ".avi", ".webm", ".ts", ".m2ts"}


@dataclass
class Candidate:
    url: str
    title: str
    duration: int | None
    height: int | None
    channel: str | None


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
    ):
        self.preferred_language = preferred_language.strip()
        self.min_height = min_height
        self.max_height = max_height
        self.max_duration = max_duration
        self.search_results = search_results
        self.output_format = output_format
        self.cookies_file = cookies_file

    def queries(self, title: str, year: int | None) -> list[str]:
        year_text = f" {year}" if year else ""
        lang = f" {self.preferred_language}" if self.preferred_language else ""
        return [
            f"{title}{year_text} official trailer{lang}".strip(),
            f"{title}{year_text} trailer{lang}".strip(),
            f"{title}{year_text} official trailer".strip(),
        ]

    def _common_opts(self) -> dict[str, Any]:
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
        }
        if self.cookies_file:
            opts["cookiefile"] = self.cookies_file
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
                    if not url or url in seen:
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
                    ))
                if found:
                    break
        return found

    @staticmethod
    def _score(candidate: Candidate, movie_title: str, year: int | None, language: str) -> int:
        text = candidate.title.casefold()
        score = 0
        if "official" in text:
            score += 30
        if "trailer" in text:
            score += 20
        if year and str(year) in text:
            score += 8
        words = [w.casefold() for w in re.findall(r"[\wÀ-ÿ]+", movie_title) if len(w) > 2]
        score += sum(3 for w in words if w in text)
        for term in language.casefold().split():
            if len(term) > 2 and term in text:
                score += 7
        if "teaser" in text:
            score -= 8
        if "reaction" in text or "review" in text:
            score -= 25
        return score

    def choose(self, candidates: list[Candidate], movie_title: str, year: int | None) -> Candidate | None:
        if not candidates:
            return None
        return max(candidates, key=lambda c: self._score(c, movie_title, year, self.preferred_language))

    def download(self, candidate: Candidate, output_stem: Path) -> Path:
        output_stem.parent.mkdir(parents=True, exist_ok=True)
        outtmpl = str(output_stem) + ".%(ext)s"
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
        for p in paths + [prepared]:
            if p.exists():
                return p
        matches = sorted(output_stem.parent.glob(output_stem.name + ".*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if matches:
            return matches[0]
        raise FileNotFoundError(f"yt-dlp completed but no output file was found for {output_stem}")


def find_local_trailers(movie_path: str | Path, trailer_folder: str) -> list[Path]:
    movie_path = Path(movie_path)
    movie_dir = movie_path if movie_path.is_dir() else movie_path.parent
    trailer_dir = movie_dir / trailer_folder
    if not trailer_dir.is_dir():
        return []
    return [p for p in trailer_dir.iterdir() if p.is_file() and p.suffix.casefold() in VIDEO_EXTENSIONS]
