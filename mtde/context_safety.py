from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
import re
from typing import Iterable


@dataclass(frozen=True)
class _SafetyContext:
    preferred_language: str
    library_movies: tuple[tuple[str, int | None], ...]
    original_title: str = ""


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

_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
_TRAILER_MARKER_RE = re.compile(r"\b(?:trailer|teaser)\b")
_SEQUEL_BASE_RE = re.compile(
    r"(?:^|\s)(?:2|3|4|5|6|7|8|9|10|ii|iii|iv|v|vi|vii|viii|ix|x)$",
    re.IGNORECASE,
)
_SUBTITLE_STOPWORDS = {
    "a", "an", "the", "of", "and", "or", "in", "on", "to", "for", "is", "are",
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einer", "eines",
    "und", "oder", "von", "im", "in", "auf", "zu", "zum", "zur", "ist", "sind",
}
_SUBTITLE_NOISE = {
    "official", "offiziell", "offizieller", "offizielle", "offizielles",
    "deutsch", "deutscher", "german", "english", "englisch",
    "hd", "uhd", "4k", "full", "final", "finaler", "first", "erster", "erste",
    "exclusive", "exklusiv", "extended", "new", "neu", "neue", "neuer", "neues",
    "trailer", "teaser", "movie", "film", "kino", "kinotrailer", "tv", "spot",
}


def _normalized(text: str) -> str:
    from .trailer import normalize_title_for_match

    return normalize_title_for_match(text)


def _meaningful_tokens(text: str) -> set[str]:
    return {
        token
        for token in _normalized(text).split()
        if token
        and token not in _SUBTITLE_STOPWORDS
        and token not in _SUBTITLE_NOISE
        and not token.isdigit()
    }


def _has_preferred_language_marker(video_title: str, preferred_language: str) -> bool:
    preferred = (preferred_language or "").strip().casefold()
    if not preferred or preferred == "original":
        return False
    from .trailer import LANGUAGE_KEYWORDS, _matches_language_keyword

    keywords = LANGUAGE_KEYWORDS.get(preferred, [preferred])
    return _matches_language_keyword(video_title.casefold(), keywords)


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


def subtitle_divergence_reason(video_title: str, movie_title: str) -> str | None:
    """Reject a conflicting sequel subtitle only when the divergence is strong.

    This guard is deliberately limited to numbered sequels that have an
    explicit subtitle in Emby. It does not require an exact subtitle match:
    minor wording differences and English/original-title fallbacks remain
    possible. A rejection needs at least two shared subtitle words plus a low
    overall token similarity, which catches the observed
    "Lilo & Stitch 2 - Stitch völlig abgedreht" ->
    "Stitch völlig von der Rolle - Märchen" false positive without turning
    normal punctuation or release descriptors into destructive mismatches.
    """
    # Require whitespace around dash-like separators so internal title hyphens
    # such as Spider-Man are never mistaken for the start of a subtitle. Colons
    # remain valid subtitle separators with or without surrounding whitespace.
    parts = re.split(r"(?:\s+[-–—]\s+|\s*:\s*)", movie_title, maxsplit=1)
    if len(parts) != 2:
        return None
    base_title, expected_subtitle = (part.strip() for part in parts)
    if not base_title or not expected_subtitle:
        return None

    base_norm = _normalized(base_title)
    if not base_norm or not _SEQUEL_BASE_RE.search(base_norm):
        return None

    candidate_norm = _normalized(video_title)
    base_match = re.search(r"\b" + re.escape(base_norm) + r"\b", candidate_norm)
    if not base_match:
        return None

    marker = _TRAILER_MARKER_RE.search(candidate_norm, base_match.end())
    end = marker.start() if marker else len(candidate_norm)
    candidate_subtitle = candidate_norm[base_match.end():end].strip()
    candidate_subtitle = _YEAR_RE.sub(" ", candidate_subtitle)

    expected_tokens = _meaningful_tokens(expected_subtitle)
    candidate_tokens = _meaningful_tokens(candidate_subtitle)
    if len(expected_tokens) < 2 or len(candidate_tokens) < 2:
        return None

    shared = expected_tokens & candidate_tokens
    if len(shared) < 2:
        # A completely different-language/original subtitle can still be the
        # same movie, so do not reject it solely on subtitle wording.
        return None

    union = expected_tokens | candidate_tokens
    similarity = len(shared) / len(union) if union else 1.0
    if expected_tokens.issubset(candidate_tokens) or similarity >= 0.5:
        return None

    return f"subtitle mismatch: expected '{expected_subtitle}', candidate '{candidate_subtitle}'"


def localized_title_ambiguity_reason(
    video_title: str,
    movie_title: str,
    year: int | None,
    original_title: str,
    preferred_language: str,
) -> str | None:
    """Reject a risky yearless localized-title match using Emby OriginalTitle.

    This does not penalize ordinary translated titles. It only triggers when:
    * the candidate omits the movie year,
    * Emby has a substantially different OriginalTitle,
    * localized and original titles still share at least one meaningful token,
    * the candidate contains only the localized title (not the OriginalTitle),
      and
    * the candidate does not explicitly identify the preferred language.

    That narrow combination catches the 2002 `Manhattan Love Story` movie
    matching the unrelated 2014 `Manhattan Love Story` TV trailer while leaving
    titles such as `Flutsch und weg`/`Flushed Away` and appended German
    subtitles such as `Beverly Hills Ninja - Die Kampfwurst` alone.
    """
    if year is None or not original_title or _YEAR_RE.search(video_title):
        return None

    movie_norm = _normalized(movie_title)
    original_norm = _normalized(original_title)
    candidate_norm = _normalized(video_title)
    if not movie_norm or not original_norm or movie_norm == original_norm:
        return None
    if not re.search(r"\b" + re.escape(movie_norm) + r"\b", candidate_norm):
        return None
    if re.search(r"\b" + re.escape(original_norm) + r"\b", candidate_norm):
        return None
    if _has_preferred_language_marker(video_title, preferred_language):
        return None

    movie_tokens = _meaningful_tokens(movie_title)
    original_tokens = _meaningful_tokens(original_title)
    shared = movie_tokens & original_tokens
    if not shared:
        return None

    union = movie_tokens | original_tokens
    similarity = len(shared) / len(union) if union else 1.0
    if similarity >= 0.5:
        return None

    return f"ambiguous localized title without year/original title: OriginalTitle '{original_title}'"


def ambiguous_no_year_reason(
    video_title: str,
    movie_title: str,
    year: int | None,
    candidate_titles: Iterable[str],
) -> str | None:
    """Reject a yearless exact-title candidate when search results prove ambiguity.

    MTDP intentionally allows yearless trailer titles. Keep that behavior unless
    the same YouTube search also exposes the exact same normalized movie title
    with a conflicting production year. That is strong evidence of a remake,
    TV-series/movie name collision or another same-name work. Candidates that
    state the requested year remain allowed.
    """
    if year is None or _YEAR_RE.search(video_title):
        return None

    movie_norm = _normalized(movie_title)
    candidate_norm = _normalized(video_title)
    if not movie_norm or not re.search(r"\b" + re.escape(movie_norm) + r"\b", candidate_norm):
        return None

    conflicts: set[int] = set()
    exact_pattern = re.compile(r"\b" + re.escape(movie_norm) + r"\b")
    for other_title in candidate_titles:
        if other_title == video_title:
            continue
        other_norm = _normalized(other_title)
        if not exact_pattern.search(other_norm):
            continue
        if not _TRAILER_MARKER_RE.search(other_norm):
            continue
        # Do not interpret an explicitly advertised remaster/restoration year as
        # proof of a different production.
        if any(marker in other_norm for marker in ("remaster", "restored", "restauriert", "restaurierung")):
            continue
        for raw in _YEAR_RE.findall(other_title):
            other_year = int(raw)
            if abs(other_year - int(year)) > 1:
                conflicts.add(other_year)

    if not conflicts:
        return None
    years = ", ".join(str(value) for value in sorted(conflicts))
    return f"ambiguous yearless title: conflicting candidate year(s) {years}"


def install_contextual_safety() -> None:
    """Add library/language and candidate-set-aware safety to MTDE scans.

    The existing MTDP-style matcher and all earlier MTDE safety rules remain the
    base. The 0.3.16 contextual rules are also used for proven-history repair.
    The newer 0.3.17 subtitle/original-title/candidate-set heuristics are kept
    selection-only so they can prevent questionable new downloads without ever
    becoming grounds for deleting an existing trailer automatically.
    """
    from . import auto_repair as auto_repair_module
    from . import emby as emby_module
    from . import hardening
    from . import service as service_module
    from . import trailer as trailer_module

    if getattr(service_module, "_mtde_contextual_safety_installed", False):
        return

    original_reason = hardening.candidate_safety_reason
    original_iter_movies = emby_module.EmbyClient.iter_movies
    original_process_movie = service_module.MTDE._process_movie
    original_ranked_candidates = trailer_module.TrailerDownloader.ranked_candidates

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

    def ranked_candidates_with_ambiguity(self, candidates, movie_title, year):
        ranked = original_ranked_candidates(self, candidates, movie_title, year)
        titles = tuple(candidate.title for candidate in candidates)
        context = _CONTEXT.get()
        filtered = []
        for candidate in ranked:
            if subtitle_divergence_reason(candidate.title, movie_title) is not None:
                continue
            if context is not None and localized_title_ambiguity_reason(
                candidate.title,
                movie_title,
                year,
                context.original_title,
                context.preferred_language,
            ) is not None:
                continue
            if ambiguous_no_year_reason(candidate.title, movie_title, year, titles) is not None:
                continue
            filtered.append(candidate)
        return filtered

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
                original_title=getattr(movie, "original_title", "") or "",
            )
        )
        try:
            # At install time this is the auto-repair wrapper. Keeping context
            # active lets the 0.3.16 high-confidence repair rules and the 0.3.17
            # selection-only rules see the same movie metadata.
            return original_process_movie(self, library, movie, do_download, progress=progress)
        finally:
            _CONTEXT.reset(token)

    # hardening.ranked_candidates resolves the module attribute at runtime.
    # auto_repair imported the function directly earlier, so update that bound
    # reference for the high-confidence 0.3.16 library/language repair rules.
    hardening.candidate_safety_reason = contextual_reason
    auto_repair_module.candidate_safety_reason = contextual_reason
    trailer_module.TrailerDownloader.ranked_candidates = ranked_candidates_with_ambiguity
    emby_module.EmbyClient.iter_movies = iter_movies_with_catalog
    service_module.MTDE._process_movie = process_movie_with_context
    service_module._mtde_contextual_safety_installed = True
