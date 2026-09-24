import tempfile
import unittest
from pathlib import Path

from mtde.hardening import (
    _parse_download_history,
    candidate_safety_reason,
    is_partial_output_path,
)
from mtde.trailer import Candidate, TrailerDownloader, find_local_trailers


class CandidateSafetyTests(unittest.TestCase):
    def setUp(self):
        self.downloader = TrailerDownloader("german", 480, 2160, 300, 15, "mkv")

    def assertRejected(self, movie, year, candidate_title):
        reason = candidate_safety_reason(candidate_title, movie, year)
        self.assertIsNotNone(reason, candidate_title)
        candidate = Candidate("x", candidate_title, 120, 1080, None)
        self.assertIsNone(self.downloader.choose([candidate], movie, year), candidate_title)

    def test_real_run_false_positives_are_rejected(self):
        cases = [
            ("Cars", 2006, "CARS ON THE ROAD Trailer German Deutsch (2022)"),
            ("Der König der Löwen 3 - Hakuna Matata", 2004, "Der König der Löwen 3 – Hakuna Matata (2004) Soundtrack: Gänge graben (längere Version)"),
            ("Madagascar 2", 2008, "Madagascar: Escape 2 Africa (2008) We are unique in German"),
            ("Toy Story 3", 2010, "Barbie trifft Ken! - TOY STORY 3 Clip German Deutsch (2010)"),
            ("WALL·E - Der Letzte räumt die Erde auf", 2008, "Die Wohlstandsgesellschaft (WALL·E - Der Letzte räumt die Erde auf - 2008)"),
            ("Harry Potter und der Orden des Phönix", 2007, "Harry Potter und der Orden des Phönix-official trailer remake 2014 [German]"),
            ("Madagascar", 2005, "Madagascar - Trailer German/Deutsch (Reversed)"),
            ("Kung Fu Panda 3", 2016, "Kung Fu Panda 3 | Die deutschen Stimmen - Synchrontrailer | Deutsch HD DreamWorks"),
            ("Stockmann", 2015, "Stockmann - Sinua varten, trailer"),
            ("Die Croods", 2013, "Die Croods - Alles auf Anfang – Trailer deutsch/german HD"),
        ]
        for case in cases:
            with self.subTest(movie=case[0]):
                self.assertRejected(*case)

    def test_legitimate_trailers_stay_allowed(self):
        cases = [
            ("Cars", 2006, "Cars - Trailer Deutsch (HD)"),
            ("Toy Story 3", 2010, "TOY STORY 3 (2010) | Offizieller Trailer Deutsch [HD]"),
            ("Die Croods", 2013, "DIE CROODS | Trailer german deutsch [HD]"),
            ("Asterix und das Geheimnis des Zaubertranks", 2018, "ASTERIX UND DAS GEHEIMNIS DES ZAUBERTRANKS Trailer German Deutsch (2019) Exklusiv"),
        ]
        for movie, year, title in cases:
            with self.subTest(movie=movie):
                self.assertIsNone(candidate_safety_reason(title, movie, year))
                candidate = Candidate("x", title, 120, 1080, None)
                self.assertEqual(self.downloader.choose([candidate], movie, year), candidate)


class PartialFileTests(unittest.TestCase):
    def test_partial_file_patterns(self):
        self.assertTrue(is_partial_output_path("Movie - Trailer.f616.mp4"))
        self.assertTrue(is_partial_output_path("Movie - Trailer.webm.part"))
        self.assertTrue(is_partial_output_path("Movie - Trailer.ytdl"))
        self.assertFalse(is_partial_output_path("Movie - Trailer.mkv"))
        self.assertFalse(is_partial_output_path("Movie - Trailer.mp4"))

    def test_fragment_is_not_a_local_trailer(self):
        with tempfile.TemporaryDirectory() as tmp:
            movie = Path(tmp) / "Movie" / "Movie.mkv"
            movie.parent.mkdir()
            movie.touch()
            trailers = movie.parent / "Trailers"
            trailers.mkdir()
            fragment = trailers / "Movie - Trailer.f616.mp4"
            fragment.touch()
            self.assertEqual(find_local_trailers(movie, "Trailers"), [])


class RepairHistoryTests(unittest.TestCase):
    def test_latest_download_candidate_is_correlated_with_output_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            movies = root / "Movies"
            movies.mkdir()
            path = "/data/media/movies-kids/Cars (2006)/Trailers/Cars (2006) - Trailer.mkv"
            (movies / "log_20260924_100000.txt").write_text(
                "2026-09-24 10:00:00 | DOWNLOADING        | Filme Kids | Cars | candidate 4/13: CARS ON THE ROAD Trailer German Deutsch (2022)\n"
                f"2026-09-24 10:00:10 | DOWNLOADED         | Filme Kids | Cars | {path}\n",
                encoding="utf-8",
            )
            records = _parse_download_history(root)
            self.assertEqual(records[path]["candidate"], "CARS ON THE ROAD Trailer German Deutsch (2022)")
            self.assertEqual(records[path]["year"], 2006)


if __name__ == "__main__":
    unittest.main()
