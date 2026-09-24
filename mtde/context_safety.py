from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
import re
from typing import Iterable


@dataclass(frozen=True)
class _SafetyContext:
    preferred_language: str
    library_movies: tuple[tuple[str, int | None], ...]


_CONTEXT: ContextVar[_SafetyContext | None] = ContextVar("mtde_candidate_safety_context", default=None)

# English is deliberately absent: when German is preferred, an English trailer
# may still be used as a neutral fallback. These markers are only languages
# that are explicitly known to be a different language.
_FOREIGN_LANGUAGE_MARKERS = (
    "castellano",
    "espanol",
    "spanish",
    "italiano",
    "italian",
    "francais",
    "french",
    "vostfr",
    "dublado",
    "portugues",
    "portuguese",
    "japanese",
    "korean",
    "russian",
    "chinese",
)


def _normalized(text: str) -> str:
    from .trailer import normalize_title_for_match

    return normalize_title_for_match(text)


def explicit_foreign_language_reason(
    video_title: str,
    movie_title: str,
    preferred_language: str,
) -> str | None:
    """Reject an explicitly non-German fallback when German is requested.

    English remains a permitted neutral fallback. The movie title itself is
    removed before looking for language markers so titles containing words such
    as "French" are not rejected merely because that word belongs to the film.
    """
    preferred = (preferred_language or "").strip().casefold()
    if preferred not in {"german", "deutsch", "de"}:
        return None

    candidate = _normalized(video_title)
    movie = _normalized(movie_title)
    remainder = candidate
    if movie:
        match = re.search(r"\b" + re.escape(movie) + r"\b", candidate)
        if match:
            remainder = (candidate[: match.start()] + " " + candidate[match.end() :]).strip()

    # An explicit German marker wins. This also accepts compact forms such as
    # GermanTrailer because normalization keeps it as one token.
    if "german" in remainder or "deutsch" in remainder:
        return None

    for marker in _FOREIGN_LANGUAGE_MARKERS:
        if re.search(r"\b" + re.escape(marker) + r"\b", remainder):
            return f"explicit foreign language for German preference: {marker}"
    return None


def library_title_collision_reason(
    video_title: str,
    movie_title: str,
    year: int | None,
    library_movies: Iterable[tuple[str, int | None]],
) -> str | None:
    """Reject a candidate that clearly names another, more specific library film.

    This is intentionally narrow. It only triggers when another movie in the
    same Emby library has a longer title containing the current movie title and
    that full longer title appears in the candidate. This catches cases such as
    "Nachts im Museum" -> "Nachts im Museum - Das geheimnisvolle Grabmal"
    without rejecting the third movie merely because the shorter first-film
    title is part of its own title.
    """
    candidate = _normalized(video_title)
    current = _normalized(movie_title)
    if not candidate or not current:
        return None

    current_pattern = re.compile(r"\b" + re.escape(current) + r"\b")
    for other_title, other_year in library_movies:
        other = _normalized(other_title)
        if not other or other == current or len(other) <= len(current):
            continue
        if not current_pattern.search(other):
            continue
        if not re.search(r"\b" + re.escape(other) + r"\b", candidate):
            continue
        year_text = f" ({other_year})" if other_year is not None else ""
        return f"library title collision: {other_title}{year_text}"
    return None


def install_contextual_safety() -> None:
    """Add library-aware and preferred-language-aware safety to MTDE scans.

    The existing MTDP-style matcher and all earlier MTDE safety rules remain the
    base. This layer only supplies context that the candidate matcher otherwise
    does not have: the other movie titles in the current Emby library and the
    configured preferred language.
    """
    from . import auto_repair as auto_repair_module
    from . import emby as emby_module
    from . import hardening
    from . import service as service_module

    if getattr(service_module, "_mtde_contextual_safety_installed", False):
        return

    original_reason = hardening.candidate_safety_reason
    original_iter_movies = emby_module.EmbyClient.iter_movies
    original_process_movie = service_module.MTDE._process_movie

    def contextual_reason(video_title: str, movie_title: str, year: int | None) -> str | None:
        reason = original_reason(video_title, movie_title, year)
        if reason:
            return reason

        context = _CONTEXT.get()
        if context is None:
            return None

        reason = explicit_foreign_language_reason(
            video_title,
            movie_title,
            context.preferred_language,
        )
        if reason:
            return reason

        return library_title_collision_reason(
            video_title,
            movie_title,
            year,
            context.library_movies,
        )

    def iter_movies_with_catalog(self, library_name):
        # Materialize the existing Emby result once, then reuse that same list
        # for the caller while retaining only title/year metadata for matching.
        # This avoids a second Emby library request and adds negligible overhead.
        movies = list(original_iter_movies(self, library_name))
        catalogs = self.__dict__.setdefault("_mtde_safety_library_catalogs", {})
        catalogs[library_name] = tuple((movie.name, movie.year) for movie in movies)
        return iter(movies)

    def process_movie_with_context(self, library, movie, do_download, progress=None):
        catalogs = getattr(self.emby, "_mtde_safety_library_catalogs", {})
        library_movies = catalogs.get(library) or ((movie.name, movie.year),)
        token = _CONTEXT.set(
            _SafetyContext(
                preferred_language=self.settings.preferred_language,
                library_movies=tuple(library_movies),
            )
        )
        try:
            # At install time this is the auto-repair wrapper. Keeping the
            # context active around it means both historical repair checks and
            # the replacement search use exactly the same new safety rules.
            return original_process_movie(self, library, movie, do_download, progress=progress)
        finally:
            _CONTEXT.reset(token)

    # hardening.ranked_candidates resolves the module attribute at runtime.
    # auto_repair imported the function directly earlier, so update that bound
    # reference as well; otherwise historical bad downloads would not benefit
    # from the new library/language context on the next scan.
    hardening.candidate_safety_reason = contextual_reason
    auto_repair_module.candidate_safety_reason = contextual_reason
    emby_module.EmbyClient.iter_movies = iter_movies_with_catalog
    service_module.MTDE._process_movie = process_movie_with_context
    service_module._mtde_contextual_safety_installed = True
