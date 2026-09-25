import unittest

from mtde import auto_repair
from mtde.context_safety import _CONTEXT, _SafetyContext, library_title_collision_reason
from mtde.final_safety import game_platform_reason
from mtde.hardening import candidate_safety_reason


class FinalSafety0320Tests(unittest.TestCase):
    def setUp(self):
        self.family_library = (
            ("Meine Braut, ihr Vater und ich", 2000, "Meet the Parents"),
            ("Meine Frau, ihre Schwiegereltern und ich", 2004, "Meet the Fockers"),
            ("Meine Frau, unsere Kinder und ich", 2010, "Little Fockers"),
        )

    def test_ps3_movie_game_trailer_is_blocked(self):
        reason = game_platform_reason(
            "Toy Story 3 PS3 ZURG-Trailer German",
            "Toy Story 3",
        )
        self.assertIsNotNone(reason)
        self.assertIn("PlayStation", reason)

    def test_game_word_in_movie_title_is_not_blocked(self):
        self.assertIsNone(
            game_platform_reason(
                "The Game Official Trailer German Deutsch",
                "The Game",
            )
        )

    def test_installed_candidate_safety_blocks_ps3_trailer(self):
        reason = candidate_safety_reason(
            "Toy Story 3 PS3 ZURG-Trailer German",
            "Toy Story 3",
            2010,
        )
        self.assertIsNotNone(reason)
        self.assertIn("video-game/platform", reason)

    def test_auto_repair_uses_game_platform_guard(self):
        reason = auto_repair.candidate_safety_reason(
            "Toy Story 3 PS3 ZURG-Trailer German",
            "Toy Story 3",
            2010,
        )
        self.assertIsNotNone(reason)
        self.assertIn("video-game/platform", reason)

    def test_other_movie_original_title_is_collision(self):
        token = _CONTEXT.set(
            _SafetyContext(
                preferred_language="german",
                library_movies=self.family_library,
                original_title="Meet the Parents",
            )
        )
        try:
            reason = library_title_collision_reason(
                "Meine Braut, Ihr Vater und ich - Meet the Fockers (Film) Trailer - English (Untertitel: Deutsch)",
                "Meine Braut, ihr Vater und ich",
                2000,
                self.family_library,
            )
        finally:
            _CONTEXT.reset(token)
        self.assertIsNotNone(reason)
        self.assertIn("OriginalTitle collision", reason)
        self.assertIn("Meet the Fockers", reason)

    def test_current_movie_original_title_is_allowed(self):
        token = _CONTEXT.set(
            _SafetyContext(
                preferred_language="german",
                library_movies=self.family_library,
                original_title="Meet the Parents",
            )
        )
        try:
            reason = library_title_collision_reason(
                "Meine Braut, ihr Vater und ich - Meet the Parents Official Trailer",
                "Meine Braut, ihr Vater und ich",
                2000,
                self.family_library,
            )
        finally:
            _CONTEXT.reset(token)
        self.assertIsNone(reason)

    def test_auto_repair_uses_original_title_collision_guard(self):
        token = _CONTEXT.set(
            _SafetyContext(
                preferred_language="german",
                library_movies=self.family_library,
                original_title="Meet the Parents",
            )
        )
        try:
            reason = auto_repair.candidate_safety_reason(
                "Meine Braut, Ihr Vater und ich - Meet the Fockers (Film) Trailer - English (Untertitel: Deutsch)",
                "Meine Braut, ihr Vater und ich",
                2000,
            )
        finally:
            _CONTEXT.reset(token)
        self.assertIsNotNone(reason)
        self.assertIn("OriginalTitle collision", reason)

    def test_legacy_two_field_library_catalog_still_works(self):
        nights_library = (
            ("Nachts im Museum", 2006),
            ("Nachts im Museum 2", 2009),
            ("Nachts im Museum - Das geheimnisvolle Grabmal", 2014),
        )
        reason = library_title_collision_reason(
            "Nachts im Museum - Das geheimnisvolle Grabmal | Offizieller Trailer #1 | Deutsch HD",
            "Nachts im Museum",
            2006,
            nights_library,
        )
        self.assertIsNotNone(reason)
        self.assertIn("library title collision", reason)


if __name__ == "__main__":
    unittest.main()
