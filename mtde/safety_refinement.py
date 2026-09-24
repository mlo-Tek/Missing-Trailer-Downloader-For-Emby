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

_STANDALONE_NUMBER_RE = re.compile(r"(?<!\w)(\d{1,4})(?!\w)")


def _has_trailer_marker(title_lower: str) -> bool:
    """Accept normal and compact forms such as Kinotrailer/GermanTrailer."""
    return "trailer" in title_lower or "teaser" in title_lower


def _first_trailer_marker_position(text: str) -> int | None:
    positions = [pos for pos in (text.find("trailer"), text.find("teaser")) if pos >= 0]
    return min(positions) if positions else None


def _sequel_numbers(text: str) -> list[int]:
    """Return standalone sequel-like numbers while ignoring calendar years.

    Tokens such as 3D, 4K and 1080p are not standalone numbers and therefore
    do not match this regex. Four-digit 19xx/20xx values are treated as years,
    not sequel numbers.
    """
    values: list[int] = []
    for raw in _STANDALONE_NUMBER_RE.findall(text):
        value = int(raw)
        if len(raw) == 4 and 1900 <= value <= 2099:
            continue
        values.append(value)
    return values


def _numbered_sequel_mismatch(video_title: str, movie_title: str) -> bool:
    """Reject a different numbered sequel without confusing trailer numbers.

    Examples:
      * Nachts im Museum -> Nachts im Museum 2 Trailer: reject
      * Cars -> Cars 2 Trailer: reject
      * Cars 2 -> Cars 2 Trailer: allow
      * Ice Age 3 ... -> Ice Age 3 ... Trailer 2: allow

    Only numbers between the matched movie title and the first trailer/teaser
    marker are considered. A number after the marker describes the trailer
    itself (for example "Trailer 2") and must never be interpreted as a movie
    sequel number.
    """
    from . import hardening

    movie_norm = hardening._normalized(movie_title)
    video_norm = hardening._normalized(video_title)
    if not movie_norm or not video_norm:
        return False

    movie_match = re.search(r"\b" + re.escape(movie_norm) + r"\b", video_norm)
    if not movie_match:
        return False

    marker_pos = _first_trailer_marker_position(video_norm)
    if marker_pos is not None and marker_pos < movie_match.start():
        # Titles such as "Official Trailer | Wild Child | Publisher" put the
        # marker before the movie name. Any preceding number is ambiguous and
        # is not safe grounds for destructive auto-repair.
        return False

    segment_end = marker_pos if marker_pos is not None else len(video_norm)
    if segment_end <= movie_match.end():
        return False

    # Candidate numbers appearing after the exact movie title but before the
    # trailer marker indicate another sequel when the Emby title itself did not
    # contain that number. This is the historical Nachts im Museum -> Teil 2
    # failure that the generic short-title guard cannot safely catch.
    suffix_before_marker = video_norm[movie_match.end():segment_end]
    extra_numbers = _sequel_numbers(suffix_before_marker)
    if extra_numbers:
        return True

    # If the exact movie title already contains a sequel number, no mismatch
    # was introduced between the title and trailer marker. This preserves
    # Cars 2 and Ice Age 3 while still ignoring "Trailer 2" after the marker.
    return False


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

    if _numbered_sequel_mismatch(video_title, movie_title):
        return "numbered sequel mismatch"

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
