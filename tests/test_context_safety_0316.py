import unittest

from mtde.context_safety import (
    _CONTEXT,
    _SafetyContext,
    explicit_foreign_language_reason,
    library_title_collision_reason,
)
from mtde.hardening import candidate_safety_reason


class ContextSafety0316Tests(unittest.TestCase):
    def setUp(self):
        self.nights_library = (
            ("Nachts im Museum", 2006),
            ("Nachts im Museum 2", 2009),
            ("Nachts im Museum - Das geheimnisvolle Grabmal", 2014),
        )

    def test_library_collision_blocks_other_movie_full_title(self):
        reason = library_title_collision_reason(
            "Nachts im Museum - Das geheimnisvolle Grabmal | Offizieller Trailer #1 | Deutsch HD",
            "Nachts im Museum",
            2006,
            self.nights_library,
        )
        self.assertIsNotNone(reason)
        self.assertIn("Das geheimnisvolle Grabmal", reason)

    def test_library_collision_allows_correct_base_movie(self):
        self.assertIsNone(
            library_title_collision_reason(
                "Nachts im Museum | Offizieller Trailer | Deutsch HD",
                "Nachts im Museum",
                2006,
                self.nights_library,
            )
        )

    def test_library_collision_does_not_reject_specific_movie_for_shorter_title(self):
        self.assertIsNone(
            library_title_collision_reason(
                "Nachts im Museum - Das geheimnisvolle Grabmal | Offizieller Trailer | Deutsch HD",
                "Nachts im Museum - Das geheimnisvolle Grabmal",
                2014,
                self.nights_library,
            )
        )

    def test_german_preference_blocks_explicit_spanish_fallback(self):
        reason = explicit_foreign_language_reason(
            "STOCKMANN Trailer Castellano",
            "Stockmann",
            "german",
        )
        self.assertIsNotNone(reason)
        self.assertIn("castellano", reason)

    def test_german_preference_keeps_english_as_neutral_fallback(self):
        self.assertIsNone(
            explicit_foreign_language_reason(
                "Stockmann Official Trailer English",
                "Stockmann",
                "german",
            )
        )

    def test_german_preference_keeps_explicit_german_candidate(self):
        self.assertIsNone(
            explicit_foreign_language_reason(
                "STOCKMANN | Trailer | Deutsch | FSK 0",
                "Stockmann",
                "german",
            )
        )

    def test_foreign_language_word_inside_movie_title_is_not_a_false_positive(self):
        self.assertIsNone(
            explicit_foreign_language_reason(
                "French Kiss Official Trailer German Deutsch",
                "French Kiss",
                "german",
            )
        )

    def test_installed_wrapper_blocks_library_collision_during_scan_context(self):
        token = _CONTEXT.set(
            _SafetyContext(
                preferred_language="german",
                library_movies=self.nights_library,
            )
        )
        try:
            reason = candidate_safety_reason(
                "Nachts im Museum - Das geheimnisvolle Grabmal | Offizieller Trailer #1 | Deutsch HD",
                "Nachts im Museum",
                2006,
            )
        finally:
            _CONTEXT.reset(token)
        self.assertIsNotNone(reason)
        self.assertIn("library title collision", reason)

    def test_installed_wrapper_blocks_explicit_foreign_language_during_scan_context(self):
        token = _CONTEXT.set(
            _SafetyContext(
                preferred_language="german",
                library_movies=(("Stockmann", 2015),),
            )
        )
        try:
            reason = candidate_safety_reason(
                "STOCKMANN Trailer Castellano",
                "Stockmann",
                2015,
            )
        finally:
            _CONTEXT.reset(token)
        self.assertIsNotNone(reason)
        self.assertIn("explicit foreign language", reason)

    def test_existing_three_argument_safety_api_remains_compatible(self):
        self.assertIsNone(
            candidate_safety_reason(
                "Cars (2006) Official Trailer German Deutsch",
                "Cars",
                2006,
            )
        )


if __name__ == "__main__":
    unittest.main()
