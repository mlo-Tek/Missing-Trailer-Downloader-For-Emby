import unittest

from mtde.hardening import candidate_safety_reason


class NumberedSequelRepair0315Tests(unittest.TestCase):
    def test_unnumbered_movie_rejects_numbered_sequel_candidate(self):
        cases = [
            ("Nachts im Museum", 2006, "Nachts im Museum 2 - Trailer 1"),
            ("Cars", 2006, "Cars 2 Trailer German Deutsch"),
        ]
        for movie, year, title in cases:
            with self.subTest(movie=movie, title=title):
                reason = candidate_safety_reason(title, movie, year)
                self.assertIsNotNone(reason)
                self.assertIn("numbered sequel mismatch", reason)

    def test_correct_numbered_movie_remains_allowed(self):
        cases = [
            ("Cars 2", 2011, "Cars 2 Trailer German Deutsch"),
            (
                "Ice Age 3 - Die Dinosaurier sind los",
                2009,
                "Ice Age 3 - Die Dinosaurier sind los - Trailer 2 (deutsch/german) | 20th Century Studios",
            ),
        ]
        for movie, year, title in cases:
            with self.subTest(movie=movie, title=title):
                self.assertIsNone(candidate_safety_reason(title, movie, year))

    def test_trailer_number_after_marker_is_not_a_sequel(self):
        self.assertIsNone(
            candidate_safety_reason(
                "Findet Dorie Exklusiv Trailer 2 German Deutsch (2016)",
                "Findet Dorie",
                2016,
            )
        )

    def test_year_before_marker_is_not_a_sequel_number(self):
        self.assertIsNone(
            candidate_safety_reason(
                "Cars (2006) Official Trailer German Deutsch",
                "Cars",
                2006,
            )
        )


if __name__ == "__main__":
    unittest.main()
