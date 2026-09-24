from __future__ import annotations

import re


# Context words that may legitimately appear between a short movie title and
# the trailer/teaser marker. These describe the trailer/release, not a
# different movie or spin-off title.
_ALLOWED_TRAILER_CONTEXT = {
    "i",
    "ii",
    "new",
    "neu",
    "neue",
    "neuer",
    "neues",
    "exclusive",
    "exklusiv",
    "extended",
    "restored",
    "restoration",
    "restauriert",
    "restaurierung",
    "bluray",
    "blu",
    "ray",
    "3d",
    "2d",
    "release",
    "theatrical",
    "cinema",
}


def _has_trailer_marker(title_lower: str) -> bool:
    """Accept normal and compact forms such as Kinotrailer/GermanTrailer."""
    return "trailer" in title_lower or "teaser" in title_lower


def _refined_short_title_mismatch(video_title: str, movie_title: str) -> bool:
    """Conservative spin-off guard for genuinely short base titles only.

    The 0.3.12 guard was intentionally strict but proved too broad when used
    for automatic deletion. It incorrectly marked legitimate sources such as
    "Hoppers | Offizieller Trailer", "Hotel Transsilvanien 3D Trailer",
    "Findet Dorie Exklusiv Trailer 2" and restoration/Blu-ray trailers.

    Automatic repair is destructive, so only one- or two-word base titles use
    this additional suffix guard. Longer titles continue to rely on the
    upstream MTDP verifier plus the explicit year/content safety checks.
    """
    from . import hardening

    movie_norm = hardening._normalized(movie_title)
    video_norm = hardening._normalized(video_title)
    movie_words = movie_norm.split()
    if not movie_norm or len(movie_words) > 2:
        return False

    match = re.search(r"\b" + re.escape(movie_norm) + r"\b", video_norm)
    if not match:
        return False

    # If the trailer marker appears before the movie title, text after the
    # movie title is commonly a channel/publisher name (for example
    # "Official Trailer | Wild Child | Screen Bites"). Do not infer a spin-off
    # from that trailing publisher text.
    marker_positions = [
        pos for pos in (video_norm.find("trailer"), video_norm.find("teaser"))
        if pos >= 0
    ]
    if marker_positions and min(marker_positions) < match.start():
        return False

    suffix = video_norm[match.end():].strip()
    if not suffix:
        return False

    marker_positions = [
        pos for pos in (suffix.find("trailer"), suffix.find("teaser"))
        if pos >= 0
    ]
    before = suffix[: min(marker_positions)].strip() if marker_positions else suffix
    if not before:
        return False

    allowed = set(hardening._ALLOWED_SUFFIX_WORDS) | _ALLOWED_TRAILER_CONTEXT
    tokens = [token for token in before.split() if not token.isdigit()]
    significant = [token for token in tokens if token not in allowed]
    return bool(significant)


def refined_candidate_safety_reason(video_title: str, movie_title: str, year: int | None) -> str | None:
    """Conservative safety classification used for downloads and auto-repair.

    This keeps the upstream MTDP matcher as the base. The extra layer rejects
    only high-confidence unsafe content. In particular, a historical MTDE
    download is not auto-deleted merely because its legitimate trailer title
    contains words such as "Exklusiv", "Neuer", "Extended", "3D",
    "Restaurierung", "Blu-ray", Kinotrailer or GermanTrailer.
    """
    from . import hardening

    title_lower = video_title.casefold()

    for phrase in hardening._BLOCKED_CONTENT_PHRASES:
        if phrase in title_lower:
            return f"blocked content marker: {phrase}"

    # Compact forms like GermanTrailer and Kinotrailer are valid trailer
    # markers. The old word-boundary regex falsely classified them as missing.
    if not _has_trailer_marker(title_lower):
        return "missing trailer/teaser keyword"

    if year is not None:
        years = [int(value) for value in hardening._YEAR_RE.findall(video_title)]
        if years and all(abs(value - int(year)) > 1 for value in years):
            return f"year mismatch: movie {year}, candidate {', '.join(map(str, years))}"

    if _refined_short_title_mismatch(video_title, movie_title):
        return "short-title spin-off/subtitle mismatch"

    return None


def install_safety_refinement() -> None:
    """Replace only MTDE's supplemental safety classifier.

    install_trailer_hardening() already patched ranked_candidates with a
    closure that resolves hardening.candidate_safety_reason at call time, so
    replacing the module attribute also refines future matching. Installing
    this before auto_repair is imported ensures destructive repair uses the
    same conservative classifier.
    """
    from . import hardening

    hardening.candidate_safety_reason = refined_candidate_safety_reason
