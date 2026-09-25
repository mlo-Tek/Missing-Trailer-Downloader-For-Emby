from __future__ import annotations

import re
from typing import Iterable


_GAME_MARKERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bps\s*[345]\b", re.IGNORECASE), "PlayStation platform"),
    (re.compile(r"\bplaystation(?:\s*[345])?\b", re.IGNORECASE), "PlayStation platform"),
    (re.compile(r"\bxbox(?:\s*(?:360|one|series(?:\s*[sx])?))?\b", re.IGNORECASE), "Xbox platform"),
    (re.compile(r"\bnintendo(?:\s+switch)?\b", re.IGNORECASE), "Nintendo platform"),
    (re.compile(r"\bgameplay\b", re.IGNORECASE), "gameplay"),
    (re.compile(r"\bvideo\s*game\b", re.IGNORECASE), "video game"),
    (re.compile(r"\bvideogame\b", re.IGNORECASE), "video game"),
    (re.compile(r"\bpc\s+game\b", re.IGNORECASE), "PC game"),
    (re.compile(r"\bgame\s+trailer\b", re.IGNORECASE), "game trailer"),
)


def _normalized(text: str) -> str:
    from .trailer import normalize_title_for_match

    return normalize_title_for_match(text)


def _contains_phrase(text: str, phrase: str) -> bool:
    return bool(phrase and re.search(r"\b" + re.escape(phrase) + r"\b", text))


def _without_movie_title(video_title: str, movie_title: str) -> str:
    candidate = _normalized(video_title)
    movie = _normalized(movie_title)
    if not movie:
        return candidate
    match = re.search(r"\b" + re.escape(movie) + r"\b", candidate)
    if not match:
        return candidate
    return (candidate[: match.start()] + " " + candidate[match.end() :]).strip()


def game_platform_reason(video_title: str, movie_title: str) -> str | None:
    """Reject candidates that explicitly advertise a video-game/platform trailer.

    The movie title is removed before checking markers so a legitimate film whose
    title itself contains a word such as "Game" is not rejected. Bare "game" or
    "switch" are intentionally not markers; only explicit platforms/game-video
    wording is considered high-confidence enough for automatic repair.
    """
    remainder = _without_movie_title(video_title, movie_title)
    for pattern, label in _GAME_MARKERS:
        if pattern.search(remainder):
            return f"video-game/platform trailer marker: {label}"
    return None


def _catalog_entry(entry) -> tuple[str, int | None, str]:
    """Accept both legacy (title, year) and 0.3.20 (title, year, OriginalTitle)."""
    try:
        title = str(entry[0] or "")
    except (IndexError, TypeError):
        return "", None, ""
    try:
        year = entry[1]
    except (IndexError, TypeError):
        year = None
    try:
        original_title = str(entry[2] or "")
    except (IndexError, TypeError):
        original_title = ""
    return title, year, original_title


def library_title_collision_with_originals_reason(
    video_title: str,
    movie_title: str,
    year: int | None,
    library_movies: Iterable[tuple],
) -> str | None:
    """Preserve localized-title collisions and add narrow OriginalTitle evidence.

    The pre-0.3.20 rule is retained unchanged for longer localized titles such as
    `Nachts im Museum - Das geheimnisvolle Grabmal`. In addition, a candidate is
    rejected when it contains the full OriginalTitle of a *different* movie in
    the same Emby library, provided that OriginalTitle is substantial (at least
    two words/eight characters) and the other movie has a different known year.

    This catches the observed 2000 `Meine Braut, ihr Vater und ich` candidate
    containing `Meet the Fockers` (the OriginalTitle of the 2004 sequel), while
    still allowing the current movie's own OriginalTitle as an English fallback.
    """
    from . import context_safety

    candidate = _normalized(video_title)
    current = _normalized(movie_title)
    if not candidate or not current:
        return None

    context = context_safety._CONTEXT.get()
    current_original = _normalized(getattr(context, "original_title", "") or "") if context else ""
    current_pattern = re.compile(r"\b" + re.escape(current) + r"\b")

    for raw_entry in library_movies:
        other_title, other_year, other_original_title = _catalog_entry(raw_entry)
        other = _normalized(other_title)
        other_original = _normalized(other_original_title)

        is_current_movie = (
            other == current
            and (year is None or other_year is None or int(other_year) == int(year))
        )

        # Preserve the established 0.3.16 localized-title collision rule.
        if not is_current_movie and other and len(other) > len(current):
            if current_pattern.search(other) and _contains_phrase(candidate, other):
                year_text = f" ({other_year})" if other_year is not None else ""
                return f"library title collision: {other_title}{year_text}"

        # OriginalTitle collision is intentionally narrower because English
        # titles can be common. Require a substantial exact phrase from another
        # movie, a different known production year, and never reject the current
        # movie's own OriginalTitle.
        if is_current_movie or not other_original:
            continue
        if current_original and other_original == current_original:
            continue
        if len(other_original) < 8 or len(other_original.split()) < 2:
            continue
        if year is None or other_year is None or int(other_year) == int(year):
            continue
        if not _contains_phrase(candidate, other_original):
            continue
        if current_original and _contains_phrase(candidate, current_original):
            continue

        year_text = f" ({other_year})" if other_year is not None else ""
        return (
            f"library OriginalTitle collision: {other_title}{year_text} "
            f"[OriginalTitle: {other_original_title}]"
        )

    return None


def install_final_safety() -> None:
    """Install the two high-confidence guards found in the final 0.3.19 run."""
    from . import auto_repair as auto_repair_module
    from . import context_safety as context_safety_module
    from . import emby as emby_module
    from . import hardening
    from . import service as service_module

    if getattr(service_module, "_mtde_final_safety_installed", False):
        return

    original_reason = hardening.candidate_safety_reason
    original_iter_movies = emby_module.EmbyClient.iter_movies

    def final_reason(video_title: str, movie_title: str, year: int | None) -> str | None:
        reason = original_reason(video_title, movie_title, year)
        if reason:
            return reason
        return game_platform_reason(video_title, movie_title)

    def iter_movies_with_original_catalog(self, library_name, *args, **kwargs):
        # context_safety already materializes the Emby result once. Reuse that
        # result and enrich only the in-memory safety catalog with OriginalTitle;
        # no additional Emby request is introduced.
        movies = list(original_iter_movies(self, library_name, *args, **kwargs))
        catalogs = self.__dict__.setdefault("_mtde_safety_library_catalogs", {})
        catalogs[library_name] = tuple(
            (movie.name, movie.year, getattr(movie, "original_title", "") or "")
            for movie in movies
        )
        return iter(movies)

    # context_safety's contextual_reason resolves this module attribute at call
    # time, so replacing it upgrades both new candidate selection and proven-log
    # auto-repair without rewriting the existing wrapper stack.
    context_safety_module.library_title_collision_reason = library_title_collision_with_originals_reason

    # hardening's ranked-candidate wrapper also resolves its module-global safety
    # function dynamically. Update auto_repair's earlier direct import as well so
    # the same game/platform rule can repair the proven Toy Story 3 PS3 download.
    hardening.candidate_safety_reason = final_reason
    auto_repair_module.candidate_safety_reason = final_reason

    emby_module.EmbyClient.iter_movies = iter_movies_with_original_catalog
    service_module._mtde_final_safety_installed = True
