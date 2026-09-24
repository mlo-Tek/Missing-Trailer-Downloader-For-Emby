import tempfile
import unittest
from pathlib import Path

from mtde.auto_repair import classify_suspicious_local_files


class AutoRepairProvenanceTests(unittest.TestCase):
    def test_tracked_unsafe_cars_download_is_auto_repairable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Cars (2006) - Trailer.mkv"
            path.touch()
            history = {
                str(path): {
                    "candidate": "CARS ON THE ROAD Trailer German Deutsch (2022)",
                    "library": "Filme Kids",
                    "title": "Cars",
                    "year": 2006,
                }
            }
            suspicious = classify_suspicious_local_files([path], history, "Cars", 2006)
            self.assertEqual(len(suspicious), 1)
            self.assertEqual(suspicious[0][0], path)
            self.assertIn("year mismatch", suspicious[0][1])

    def test_untracked_local_trailer_is_never_auto_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Cars (2006) - Trailer.mkv"
            path.touch()
            suspicious = classify_suspicious_local_files([path], {}, "Cars", 2006)
            self.assertEqual(suspicious, [])

    def test_tracked_legitimate_trailer_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Cars (2006) - Trailer.mkv"
            path.touch()
            history = {
                str(path): {
                    "candidate": "Cars - Trailer Deutsch (HD)",
                    "library": "Filme Kids",
                    "title": "Cars",
                    "year": 2006,
                }
            }
            suspicious = classify_suspicious_local_files([path], history, "Cars", 2006)
            self.assertEqual(suspicious, [])

    def test_known_bad_classes_are_auto_repairable_when_tracked(self):
        cases = [
            ("Harry Potter und der Orden des Phönix", 2007, "Harry Potter und der Orden des Phönix-official trailer remake 2014 [German]"),
            ("Kung Fu Panda 3", 2016, "Kung Fu Panda 3 | Die deutschen Stimmen - Synchrontrailer | Deutsch HD DreamWorks"),
            ("Der König der Löwen 3 - Hakuna Matata", 2004, "Der König der Löwen 3 – Hakuna Matata (2004) Soundtrack: Gänge graben"),
            ("Toy Story 3", 2010, "Barbie trifft Ken! - TOY STORY 3 Clip German Deutsch (2010)"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            for index, (movie, year, candidate) in enumerate(cases):
                with self.subTest(movie=movie):
                    path = Path(tmp) / f"{index}.mkv"
                    path.touch()
                    history = {str(path): {"candidate": candidate}}
                    suspicious = classify_suspicious_local_files([path], history, movie, year)
                    self.assertEqual(len(suspicious), 1)


if __name__ == "__main__":
    unittest.main()
