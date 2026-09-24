import unittest

from mtde.context_safety import (
    _CONTEXT,
    _SafetyContext,
    ambiguous_no_year_reason,
    localized_title_ambiguity_reason,
    subtitle_divergence_reason,
)
from mtde.emby import EmbyClient
from mtde.hardening import candidate_safety_reason
from mtde.trailer import Candidate, TrailerDownloader


class SelectionSafety0317Tests(unittest.TestCase):
    def _downloader(self):
        return TrailerDownloader(
            preferred_language="german",
            min_height=480,
            max_height=2160,
            max_duration=600,
            search_results=15,
            output_format="mkv",
        )

    @staticmethod
    def _candidate(url, title, query_index=0):
        return Candidate(
            url=url,
            title=title,
            duration=120,
            height=1080,
            channel="Trailer Channel",
            query_index=query_index,
        )

    def test_lilo_alternate_german_subtitle_is_rejected(self):
        reason = subtitle_divergence_reason(
            "Lilo & Stitch 2: Stitch völlig von der Rolle - Märchen - 2005 - Trailer",
            "Lilo & Stitch 2 - Stitch völlig abgedreht",
        )
        self.assertIsNotNone(reason)
        self.assertIn("subtitle mismatch", reason)

    def test_lilo_guard_is_applied_by_ranker_not_destructive_repair_classifier(self):
        # 0.3.17 ambiguity heuristics prevent new downloads but are not grounds
        # for automatically deleting a historical local trailer.
        self.assertIsNone(
            candidate_safety_reason(
                "Lilo & Stitch 2: Stitch völlig von der Rolle - Märchen - 2005 - Trailer",
                "Lilo & Stitch 2 - Stitch völlig abgedreht",
                2005,
            )
        )
        ranked = self._downloader().ranked_candidates(
            [
                self._candidate(
                    "https://example.invalid/lilo-wrong",
                    "Lilo & Stitch 2: Stitch völlig von der Rolle - Märchen - 2005 - Trailer",
                )
            ],
            "Lilo & Stitch 2 - Stitch völlig abgedreht",
            2005,
        )
        self.assertEqual([], ranked)

    def test_exact_sequel_subtitle_stays_allowed(self):
        self.assertIsNone(
            subtitle_divergence_reason(
                "Lilo & Stitch 2 - Stitch völlig abgedreht | Trailer Deutsch | 2005",
                "Lilo & Stitch 2 - Stitch völlig abgedreht",
            )
        )
        self.assertIsNone(
            subtitle_divergence_reason(
                "Ice Age 3 - Die Dinosaurier sind los - Trailer 2 (deutsch/german)",
                "Ice Age 3 - Die Dinosaurier sind los",
            )
        )

    def test_original_language_subtitle_is_not_blocked_by_wording_alone(self):
        self.assertIsNone(
            subtitle_divergence_reason(
                "Lilo & Stitch 2: Stitch Has a Glitch Official Trailer 2005",
                "Lilo & Stitch 2 - Stitch völlig abgedreht",
            )
        )

    def test_internal_hyphen_is_not_treated_as_subtitle_separator(self):
        self.assertIsNone(
            subtitle_divergence_reason(
                "Spider-Man 2 Official Trailer 2004",
                "Spider-Man 2",
            )
        )

    def test_manhattan_yearless_localized_title_is_rejected_from_original_title(self):
        reason = localized_title_ambiguity_reason(
            "Manhattan: Love Story Trailer",
            "Manhattan Love Story",
            2002,
            "Maid in Manhattan",
            "german",
        )
        self.assertIsNotNone(reason)
        self.assertIn("Maid in Manhattan", reason)

    def test_manhattan_original_title_guard_is_selection_only_and_deterministic(self):
        token = _CONTEXT.set(
            _SafetyContext(
                preferred_language="german",
                library_movies=(("Manhattan Love Story", 2002),),
                original_title="Maid in Manhattan",
            )
        )
        try:
            self.assertIsNone(
                candidate_safety_reason(
                    "Manhattan: Love Story Trailer",
                    "Manhattan Love Story",
                    2002,
                )
            )
            ranked = self._downloader().ranked_candidates(
                [
                    self._candidate(
                        "https://example.invalid/manhattan-tv",
                        "Manhattan: Love Story Trailer",
                    )
                ],
                "Manhattan Love Story",
                2002,
            )
        finally:
            _CONTEXT.reset(token)
        self.assertEqual([], ranked)

    def test_requested_year_or_preferred_language_disambiguates_localized_title(self):
        self.assertIsNone(
            localized_title_ambiguity_reason(
                "Manhattan Love Story 2002 Trailer",
                "Manhattan Love Story",
                2002,
                "Maid in Manhattan",
                "german",
            )
        )
        self.assertIsNone(
            localized_title_ambiguity_reason(
                "Manhattan Love Story Trailer Deutsch",
                "Manhattan Love Story",
                2002,
                "Maid in Manhattan",
                "german",
            )
        )

    def test_unrelated_translation_without_shared_title_token_stays_allowed(self):
        self.assertIsNone(
            localized_title_ambiguity_reason(
                "Flutsch und Weg - Trailer",
                "Flutsch und weg",
                2006,
                "Flushed Away",
                "german",
            )
        )

    def test_appended_localized_subtitle_with_high_original_overlap_stays_allowed(self):
        self.assertIsNone(
            localized_title_ambiguity_reason(
                "Beverly Hills Ninja Die Kampfwurst (Orginal Trailer)",
                "Beverly Hills Ninja - Die Kampfwurst",
                1997,
                "Beverly Hills Ninja",
                "german",
            )
        )

    def test_emby_movie_fields_include_original_title(self):
        self.assertIn("OriginalTitle", EmbyClient._fields())
        movie = EmbyClient._movie_from_item(
            {
                "Id": "1",
                "Name": "Manhattan Love Story",
                "OriginalTitle": "Maid in Manhattan",
                "ProductionYear": 2002,
                "Path": "/movies/Manhattan Love Story",
            }
        )
        self.assertEqual("Maid in Manhattan", movie.original_title)

    def test_yearless_same_title_is_rejected_when_search_proves_other_year(self):
        reason = ambiguous_no_year_reason(
            "Manhattan: Love Story Trailer",
            "Manhattan Love Story",
            2002,
            (
                "Manhattan: Love Story Trailer",
                "Manhattan Love Story Official Trailer 2014",
            ),
        )
        self.assertIsNotNone(reason)
        self.assertIn("2014", reason)

    def test_remaster_year_is_not_treated_as_other_production(self):
        self.assertIsNone(
            ambiguous_no_year_reason(
                "Example Movie Trailer",
                "Example Movie",
                1988,
                (
                    "Example Movie Trailer",
                    "Example Movie 2014 Remastered Trailer",
                ),
            )
        )

    def test_yearless_title_stays_allowed_without_conflicting_year_evidence(self):
        self.assertIsNone(
            ambiguous_no_year_reason(
                "KUNG FU PANDA : TRAILER",
                "Kung Fu Panda",
                2008,
                (
                    "KUNG FU PANDA : TRAILER",
                    "Kung Fu Panda Official Trailer German Deutsch",
                ),
            )
        )

    def test_candidate_with_requested_year_stays_allowed_even_if_other_year_exists(self):
        self.assertIsNone(
            ambiguous_no_year_reason(
                "Manhattan Love Story 2002 Trailer",
                "Manhattan Love Story",
                2002,
                (
                    "Manhattan Love Story 2002 Trailer",
                    "Manhattan Love Story Official Trailer 2014",
                ),
            )
        )

    def test_installed_ranker_filters_ambiguous_yearless_manhattan_candidate(self):
        ranked = self._downloader().ranked_candidates(
            [
                self._candidate("https://example.invalid/no-year", "Manhattan: Love Story Trailer"),
                self._candidate("https://example.invalid/2014", "Manhattan Love Story Official Trailer 2014"),
            ],
            "Manhattan Love Story",
            2002,
        )
        self.assertEqual([], ranked)

    def test_installed_ranker_keeps_target_year_manhattan_candidate(self):
        ranked = self._downloader().ranked_candidates(
            [
                self._candidate("https://example.invalid/2002", "Manhattan Love Story 2002 Trailer"),
                self._candidate("https://example.invalid/2014", "Manhattan Love Story Official Trailer 2014"),
            ],
            "Manhattan Love Story",
            2002,
        )
        self.assertEqual(["https://example.invalid/2002"], [item.url for item in ranked])


if __name__ == "__main__":
    unittest.main()
