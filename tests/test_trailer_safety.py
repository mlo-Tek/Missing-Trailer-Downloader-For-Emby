import unittest

from mtde.trailer import is_likely_trailer


class TrailerSafetyTests(unittest.TestCase):
    def test_rejects_intro_opening_and_vorspann_clips(self):
        rejected = [
            "Asterix erobert Rom - Intro (1976) (german)",
            "Asterix erobert Rom - Opening Credits (1976)",
            "Asterix erobert Rom - Vorspann (1976)",
        ]
        for title in rejected:
            with self.subTest(title=title):
                self.assertFalse(is_likely_trailer(title))

    def test_keeps_legitimate_trailer_titles(self):
        accepted = [
            "ASTERIX EROBERT ROM - Trailer (1976)",
            "Horton hört ein Hu! - Von den Machern von ICE AGE - Trailer",
            "Die wilden Hühner und die Liebe (Trailer) | ARD Plus",
        ]
        for title in accepted:
            with self.subTest(title=title):
                self.assertTrue(is_likely_trailer(title))


if __name__ == "__main__":
    unittest.main()
