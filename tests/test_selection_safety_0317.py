import unittest

from mtde.context_safety import ambiguous_no_year_reason, subtitle_divergence_reason
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

    def test_installed_classifier_rejects_lilo_false_positive(self):
        reason = candidate_safety_reason(
            "Lilo & Stitch 2: Stitch völlig von der Rolle - Märchen - 2005 - Trailer",
            "Lilo & Stitch 2 - Stitch völlig abgedreht",
            2005,
        )
        self.assertIsNotNone(reason)
        self.assertIn("subtitle mismatch", reason)

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
