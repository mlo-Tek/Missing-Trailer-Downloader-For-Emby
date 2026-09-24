import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from mtde.app import create_app
from mtde.config import Settings
from mtde.emby import EmbyClient, EmbyMovie
from mtde.service import MTDE
from mtde.trailer import Candidate, TrailerDownloader, is_likely_trailer


class MatchingRegressionTests(unittest.TestCase):
    def setUp(self):
        self.downloader = TrailerDownloader("german", 480, 2160, 300, 15, "mkv")

    def test_base_movie_does_not_match_numbered_sequel(self):
        cases = [
            ("Ice Age", 2002, "ICE AGE 4 - Voll verschoben - Trailer 1 (Full-HD) - Deutsch / German"),
            ("Kung Fu Panda", 2008, "Kung Fu Panda 4 | Offizieller Trailer deutsch/german HD"),
            ("Nachts im Museum", 2006, "Nachts im Museum 2 - Trailer 1"),
            ("Die Unglaublichen", 2004, "Die Unglaublichen 2 - Offizieller Trailer | Disney•Pixar HD"),
        ]
        for title, year, candidate_title in cases:
            with self.subTest(title=title):
                candidate = Candidate("x", candidate_title, 120, 1080, None)
                self.assertIsNone(self.downloader.choose([candidate], title, year))

    def test_numbered_movie_still_matches_its_own_sequel_title(self):
        candidate = Candidate(
            "x", "Kung Fu Panda 4 | Offizieller Trailer deutsch/german HD", 120, 1080, None
        )
        self.assertEqual(self.downloader.choose([candidate], "Kung Fu Panda 4", 2024), candidate)

    def test_non_trailer_dvd_menu_and_german_compilation_are_rejected(self):
        # These content-type guards are applied while YouTube search results are
        # built, before MTDP title verification/scoring runs.
        blocked_titles = [
            "Leroy & Stitch (2006) - Hauptmenü (German/Deutsch) (DVD)",
            "Stitch & Co. - Der Film (2003) - Hauptmenu (German/Deutsch) (DVD)",
            "VAIANA - Alle Trailer (deutsch | german) | Disney HD",
        ]
        for candidate_title in blocked_titles:
            with self.subTest(candidate_title=candidate_title):
                self.assertFalse(is_likely_trailer(candidate_title))

        # Compilation-style numbered sequel conflicts are checked by the title
        # verifier because the phrase itself can still look like a trailer.
        candidate = Candidate(
            "x", "LILO & STITCH 1&2 - Lieblingsfilm-Trailer | Disney Channel", 120, 1080, None
        )
        self.assertIsNone(self.downloader.choose([candidate], "Lilo & Stitch", 2002))


class DownloadFallbackRegressionTests(unittest.TestCase):
    def test_real_run_tries_next_verified_candidate_after_download_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            movie_file = Path(tmp) / "Movie" / "Movie.mkv"
            movie_file.parent.mkdir()
            movie_file.touch()
            settings = Settings(
                emby_url="http://emby:8096",
                emby_api_key="token",
                movie_libraries=["Movies"],
                dry_run=False,
                download_trailers=True,
                preferred_language="german",
                trailer_resolution_min=480,
            )
            service = MTDE(settings)
            movie = EmbyMovie("1", "Movie", 2026, str(movie_file), [], 0, [], {})
            first = Candidate("a", "Movie Official Trailer German 2026", 120, 1080, None, search_position=0)
            second = Candidate("b", "Movie Trailer Deutsch 2026", 120, 1080, None, search_position=1)
            service.downloader.search = Mock(return_value=[first, second])
            final_path = movie_file.parent / "Trailers" / "Movie (2026) - Trailer.mkv"
            service._download_candidate = Mock(side_effect=[RuntimeError("video unavailable"), final_path])

            result = service._process_movie("Movies", movie, True)

            self.assertEqual(result.status, "downloaded")
            self.assertEqual(result.message, second.title)
            self.assertEqual(service._download_candidate.call_count, 2)


class EmbyDetailRegressionTests(unittest.TestCase):
    def test_get_item_uses_user_independent_items_query(self):
        client = EmbyClient("http://emby:8096", "token")
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "Items": [{"Id": "108695", "Name": "Movie", "Path": "/data/media/movies/Movie/Movie.mkv"}]
        }
        client.session.get = Mock(return_value=response)

        item = client.get_item("108695")

        self.assertEqual(item["Id"], "108695")
        args, kwargs = client.session.get.call_args
        self.assertTrue(args[0].endswith("/Items"))
        self.assertEqual(kwargs["params"]["Ids"], "108695")


class UiRegressionTests(unittest.TestCase):
    class FakeService:
        def __init__(self):
            self.settings = Settings(
                emby_url="http://emby:8096",
                emby_api_key="token",
                movie_libraries=["Movies"],
                dry_run=True,
                preferred_language="german",
            )
            self.scan_calls = []

        def update_settings(self, settings):
            self.settings = settings

        def test_connection(self):
            return {"ServerName": "Test Emby", "Version": "4.10.0"}

        def scan(self, download=True, should_stop=None, progress=None):
            return []

        def serialize(self, results):
            return []

    def test_emby_refresh_is_integrated_into_movies_toolbar_not_floating(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = os.path.join(tmp, "config.yml")
            with open(config_path, "w", encoding="utf-8") as handle:
                handle.write(
                    'EMBY_URL: "http://emby:8096"\n'
                    'EMBY_API_KEY: "token"\n'
                    'MOVIE_LIBRARIES:\n  - "Movies"\n'
                    'DRY_RUN: true\n'
                )
            old = os.environ.get("MTDE_CONFIG")
            os.environ["MTDE_CONFIG"] = config_path
            try:
                client = create_app(self.FakeService()).test_client()
                html = client.get("/").get_data(as_text=True)
                self.assertIn("mtde-emby-toolbar-btn", html)
                self.assertIn("In Emby aktualisieren", html)
                self.assertIn("#mtde-emby-refresh-launcher{display:none!important}", html)
            finally:
                if old is None:
                    os.environ.pop("MTDE_CONFIG", None)
                else:
                    os.environ["MTDE_CONFIG"] = old


if __name__ == "__main__":
    unittest.main()
