from __future__ import annotations

import re
from typing import Iterable


_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
_TRAILER_MARKER_RE = re.compile(r"\b(?:trailer|teaser)\b")
_YEAR_EVIDENCE_NOISE = {
    "official", "offiziell", "offizieller", "offizielle", "offizielles",
    "german", "deutsch", "deutscher", "english", "englisch",
    "hd", "uhd", "4k", "full", "final", "finaler", "new", "neu", "neue", "neuer", "neues",
    "movie", "film", "kino", "kinotrailer", "theatrical", "international",
}


def _normalized(text: str) -> str:
    from .trailer import normalize_title_for_match

    return normalize_title_for_match(text)


def _same_work_year_evidence(other_title: str, movie_title: str) -> bool:
    """Return True only when another result still describes the same base work.

    The 0.3.17 ambiguity guard treated every result containing the base title as
    evidence for a conflicting production year. That made sequel results such as
    ``Kung Fu Panda 4 ... 2024`` invalidate a perfectly valid yearless
    ``Kung Fu Panda - Trailer`` candidate for the 2008 movie.

    Keep year-conflict evidence deliberately narrow: between the matched movie
    title and the first trailer/teaser marker or production year, only ordinary
    release/language noise may appear. A sequel number, subtitle or spin-off
    wording means the result is a different work and must not create ambiguity.
    """
    movie = _normalized(movie_title)
    candidate = _normalized(other_title)
    if not movie or not candidate:
        return False

    match = re.search(r"\b" + re.escape(movie) + r"\b", candidate)
    if not match:
        return False

    suffix = candidate[match.end():].strip()
    if not suffix:
        return True

    cut_positions: list[int] = []
    marker = _TRAILER_MARKER_RE.search(suffix)
    if marker:
        cut_positions.append(marker.start())
    year_match = _YEAR_RE.search(suffix)
    if year_match:
        cut_positions.append(year_match.start())

    before = suffix[: min(cut_positions)].strip() if cut_positions else suffix
    if not before:
        return True

    tokens = [token for token in before.split() if token]
    return all(token in _YEAR_EVIDENCE_NOISE for token in tokens)


def refined_ambiguous_no_year_reason(
    video_title: str,
    movie_title: str,
    year: int | None,
    candidate_titles: Iterable[str],
) -> str | None:
    """Reject a yearless title only when another result proves same-work ambiguity.

    Same-title remakes/reboots with another year still count. Numbered sequels,
    subtitle continuations and spin-offs no longer poison the base movie merely
    because their title starts with the same words.
    """
    if year is None or _YEAR_RE.search(video_title):
        return None

    movie_norm = _normalized(movie_title)
    candidate_norm = _normalized(video_title)
    if not movie_norm or not re.search(r"\b" + re.escape(movie_norm) + r"\b", candidate_norm):
        return None

    conflicts: set[int] = set()
    for other_title in candidate_titles:
        if other_title == video_title:
            continue
        other_norm = _normalized(other_title)
        if not _TRAILER_MARKER_RE.search(other_norm):
            continue
        if any(marker in other_norm for marker in ("remaster", "restored", "restauriert", "restaurierung")):
            continue
        if not _same_work_year_evidence(other_title, movie_title):
            continue

        for raw in _YEAR_RE.findall(other_title):
            other_year = int(raw)
            if abs(other_year - int(year)) > 1:
                conflicts.add(other_year)

    if not conflicts:
        return None
    years = ", ".join(str(value) for value in sorted(conflicts))
    return f"ambiguous yearless title: conflicting candidate year(s) {years}"


def install_ambiguity_refinement() -> None:
    """Replace only the 0.3.17 candidate-set ambiguity helper.

    The high-confidence 0.3.16 repair rules and all other MTDP/MTDE matching
    logic stay untouched. The contextual ranker resolves this module-level
    function at runtime, so replacing the attribute is sufficient and keeps the
    refinement selection-only.
    """
    from . import context_safety

    if getattr(context_safety, "_mtde_ambiguity_refinement_installed", False):
        return

    context_safety.ambiguous_no_year_reason = refined_ambiguous_no_year_reason
    context_safety._mtde_ambiguity_refinement_installed = True
