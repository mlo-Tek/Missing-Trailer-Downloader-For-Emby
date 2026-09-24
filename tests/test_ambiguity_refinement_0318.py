import unittest

from mtde.context_safety import ambiguous_no_year_reason
from mtde.trailer import Candidate, TrailerDownloader


class AmbiguityRefinement0318Tests(unittest.TestCase):
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

    def _downloader(self):
        return TrailerDownloader(
            preferred_language="german",
            min_height=480,
            max_height=2160,
            max_duration=600,
            search_results=15,
            output_format="mkv",
        )

    def test_kung_fu_panda_sequel_year_does_not_poison_base_movie(self):
        reason = ambiguous_no_year_reason(
            "KUNG FU PANDA : TRAILER",
            "Kung Fu Panda",
            2008,
            (
                "KUNG FU PANDA : TRAILER",
                "KUNG FU PANDA 4 Trailer German Deutsch (2024)",
            ),
        )
        self.assertIsNone(reason)

    def test_spin_off_subtitle_does_not_poison_base_movie(self):
        reason = ambiguous_no_year_reason(
            "KUNG FU PANDA : TRAILER",
            "Kung Fu Panda",
            2008,
            (
                "KUNG FU PANDA : TRAILER",
                "Kung Fu Panda: The Dragon Knight Trailer 2022",
            ),
        )
        self.assertIsNone(reason)

    def test_same_title_other_year_still_blocks_manhattan(self):
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

    def test_ranker_keeps_kung_fu_panda_despite_sequel_results(self):
        ranked = self._downloader().ranked_candidates(
            [
                self._candidate("https://example.invalid/base", "KUNG FU PANDA : TRAILER"),
                self._candidate("https://example.invalid/sequel", "KUNG FU PANDA 4 Trailer German Deutsch (2024)"),
            ],
            "Kung Fu Panda",
            2008,
        )
        self.assertEqual(["https://example.invalid/base"], [item.url for item in ranked])

    def test_ranker_still_blocks_manhattan_same_title_collision(self):
        ranked = self._downloader().ranked_candidates(
            [
                self._candidate("https://example.invalid/no-year", "Manhattan: Love Story Trailer"),
                self._candidate("https://example.invalid/2014", "Manhattan Love Story Official Trailer 2014"),
            ],
            "Manhattan Love Story",
            2002,
        )
        self.assertEqual([], ranked)


if __name__ == "__main__":
    unittest.main()
