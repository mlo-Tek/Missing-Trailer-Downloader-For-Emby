import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from mtde.config import PathMapping, Settings
from mtde.emby import EmbyClient, EmbyMovie
from mtde.service import MTDE
from mtde.trailer import Candidate, TrailerDownloader, find_local_trailers, select_trailer_directory


class CoreTests(unittest.TestCase):
    def test_path_mapping(self):
        mapping = PathMapping("/data/media", "/media")
        self.assertEqual(
            mapping.map("/data/media/movies/300/300.mkv"),
            "/media/movies/300/300.mkv",
        )
        self.assertEqual(mapping.map("/other/x.mkv"), "/other/x.mkv")

    def test_local_trailer_detection(self):
        with TemporaryDirectory() as tmp:
            movie = Path(tmp) / "Movie" / "Movie.mkv"
            movie.parent.mkdir()
            movie.touch()
            self.assertEqual(find_local_trailers(movie, "trailers"), [])
            trailers = movie.parent / "trailers"
            trailers.mkdir()
            trailer = trailers / "Trailer.mkv"
            trailer.touch()
            self.assertEqual(find_local_trailers(movie, "trailers"), [trailer])

    def test_legacy_trailer_folder_names_are_detected_case_insensitively(self):
        for folder_name in ("Trailers", "TRAILERS", "Trailer", "TRAILER"):
            with self.subTest(folder_name=folder_name), TemporaryDirectory() as tmp:
                movie = Path(tmp) / "Movie" / "Movie.mkv"
                movie.parent.mkdir()
                movie.touch()
                legacy = movie.parent / folder_name
                legacy.mkdir()
                trailer = legacy / "legacy.mp4"
                trailer.touch()
                self.assertEqual(find_local_trailers(movie, "trailers"), [trailer])

    def test_empty_legacy_trailer_folder_is_safe(self):
        with TemporaryDirectory() as tmp:
            movie = Path(tmp) / "Movie" / "Movie.mkv"
            movie.parent.mkdir()
            movie.touch()
            (movie.parent / "Trailers").mkdir()
            self.assertEqual(find_local_trailers(movie, "trailers"), [])
            self.assertEqual(
                select_trailer_directory(movie, "trailers"),
                movie.parent / "Trailers",
            )

    def test_candidate_scoring_prefers_official_language(self):
        downloader = TrailerDownloader("german", 1080, 2160, 300, 8, "mkv")
        good = Candidate(
            "a", "Movie Official Trailer Deutsch 2026", 120, 1080, None
        )
        bad = Candidate(
            "b", "Movie Trailer Reaction 2026", 120, 1080, None
        )
        self.assertEqual(downloader.choose([bad, good], "Movie", 2026), good)

    def test_global_dry_run_blocks_download_even_when_requested(self):
        with TemporaryDirectory() as tmp:
            movie_file = Path(tmp) / "Movie" / "Movie.mkv"
            movie_file.parent.mkdir()
            movie_file.touch()
            settings = Settings(
                emby_url="http://emby:8096",
                emby_api_key="token",
                movie_libraries=["Movies"],
                dry_run=True,
            )
            service = MTDE(settings)
            movie = EmbyMovie(
                "1", "Movie", 2026, str(movie_file), [], 0, [], {}
            )
            service.emby.iter_movies = Mock(return_value=iter([movie]))
            service.emby.refresh_item = Mock()
            candidate = Candidate(
                "https://example.invalid",
                "Movie Official Trailer Deutsch 2026",
                120,
                1080,
                None,
            )
            service.downloader.search = Mock(return_value=[candidate])
            service.downloader.choose = Mock(return_value=candidate)
            service.downloader.download = Mock()

            results = service.scan(download=True)

            self.assertEqual(results[0].status, "would_download")
            service.downloader.download.assert_not_called()
            service.emby.refresh_item.assert_not_called()

    def test_remote_trailer_policy_is_configurable(self):
        with TemporaryDirectory() as tmp:
            movie_file = Path(tmp) / "Movie" / "Movie.mkv"
            movie_file.parent.mkdir()
            movie_file.touch()
            movie = EmbyMovie(
                "1",
                "Movie",
                2026,
                str(movie_file),
                [],
                0,
                [{"Url": "https://example.invalid/trailer"}],
                {},
            )

            local_first = MTDE(
                Settings(
                    emby_url="http://emby:8096",
                    emby_api_key="token",
                    movie_libraries=["Movies"],
                    check_remote_trailers=False,
                )
            )
            self.assertEqual(
                local_first.movie_ui("Movies", movie)["trailerStatus"],
                "missing",
            )

            remote_counts = MTDE(
                Settings(
                    emby_url="http://emby:8096",
                    emby_api_key="token",
                    movie_libraries=["Movies"],
                    check_remote_trailers=True,
                )
            )
            self.assertEqual(
                remote_counts.movie_ui("Movies", movie)["trailerStatus"],
                "plexpass",
            )

    def test_settings_parse_upstream_style_libraries_and_legacy_language(self):
        with TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.yml"
            config.write_text(
                """
EMBY_URL: http://emby:8096
EMBY_API_KEY: token
MOVIE_LIBRARIES:
  - name: Movies
    genres_to_skip:
      - Short
PREFERRED_LANGUAGE: german deutsch
SCHEDULE_TYPE: disabled
UPGRADE_TRAILERS: local
""".strip(),
                encoding="utf-8",
            )
            settings = Settings.from_yaml(config)
            self.assertEqual(settings.movie_libraries, ["Movies"])
            self.assertEqual(settings.genres_for_library("Movies"), ["Short"])
            self.assertEqual(settings.preferred_language, "german")
            self.assertEqual(settings.upgrade_trailers, "local")

    def test_emby_api_base_normalization(self):
        self.assertEqual(
            EmbyClient("http://emby:8096", "token").base_url,
            "http://emby:8096/emby",
        )
        self.assertEqual(
            EmbyClient("http://emby:8096/emby", "token").base_url,
            "http://emby:8096/emby",
        )

    def test_media_folder_library_resolution(self):
        client = EmbyClient("http://emby:8096", "token")
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "Items": [{"Name": "Movies", "Id": "123"}],
            "TotalRecordCount": 1,
        }
        client.session.get = Mock(return_value=response)
        self.assertEqual(client.resolve_library("Movies"), "123")
        called_url = client.session.get.call_args.args[0]
        self.assertTrue(called_url.endswith("/Library/MediaFolders"))

    def test_virtual_folder_fallback(self):
        client = EmbyClient("http://emby:8096", "token")
        media_response = Mock()
        media_response.raise_for_status.return_value = None
        media_response.json.return_value = {"Items": []}
        virtual_response = Mock()
        virtual_response.raise_for_status.return_value = None
        virtual_response.json.return_value = {
            "Items": [{"Name": "Movies", "ItemId": "456"}]
        }
        client.session.get = Mock(side_effect=[media_response, virtual_response])
        self.assertEqual(client.resolve_library("Movies"), "456")


if __name__ == "__main__":
    unittest.main()
