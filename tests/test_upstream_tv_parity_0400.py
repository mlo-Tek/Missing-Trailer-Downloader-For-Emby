import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from mtde.config import Settings
from mtde.emby import EmbyMovie
from mtde.service import MTDE
from mtde.trailer import Candidate
from mtde.tv import (
    TVTrailerDownloader,
    find_series_local_trailers,
    verify_tv_title_match,
)


class UpstreamTVParityTests(unittest.TestCase):
    def test_settings_load_movie_and_tv_libraries(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yml"
            path.write_text(
                """
EMBY_URL: http://emby:8096
EMBY_API_KEY: token
MOVIE_LIBRARIES:
  - name: Filme
    genres_to_skip: []
TV_LIBRARIES:
  - name: Serien Kids
    genres_to_skip:
      - Documentary
SCHEDULE_TYPE: disabled
""".strip(),
                encoding="utf-8",
            )
            settings = Settings.from_yaml(path)
            self.assertEqual(settings.movie_libraries, ["Filme"])
            self.assertEqual(settings.tv_libraries, ["Serien Kids"])
            self.assertEqual(settings.genres_for_tv_library("Serien Kids"), ["Documentary"])

    def test_tv_only_configuration_is_valid(self):
        settings = Settings(
            emby_url="http://emby:8096",
            emby_api_key="token",
            movie_libraries=[],
            tv_libraries=["Serien Kids"],
        )
        settings.validate()

    def test_tv_queries_match_upstream_order(self):
        downloader = TVTrailerDownloader("german", 480, 2160, 300, 15, "mkv")
        self.assertEqual(
            downloader.queries("Bluey", 2018),
            [
                "Bluey 2018 TV show official trailer german",
                "Bluey trailer 2018 TV series german",
                "Bluey 2018 series trailer german",
            ],
        )

    def test_tv_title_matcher_is_separate_from_movie_matcher(self):
        self.assertTrue(verify_tv_title_match("Bluey 2018 Official Trailer", "Bluey", 2018))
        self.assertTrue(verify_tv_title_match("Stranger Things Official Trailer", "Stranger Things", 2016))
        self.assertFalse(verify_tv_title_match("Different Show Official Trailer", "Bluey", 2018))

    def test_series_local_trailer_conventions_match_upstream(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "Bluey"
            root.mkdir()
            direct = root / "Bluey.1080p.de-trailer.mkv"
            direct.touch()
            trailers = root / "Trailers"
            trailers.mkdir()
            extra = trailers / "Bluey trailer.mp4"
            extra.touch()
            self.assertEqual(find_series_local_trailers(root), [direct, extra])

    def test_normal_scan_processes_movies_then_tv_libraries(self):
        with TemporaryDirectory() as tmp:
            movie_file = Path(tmp) / "Movies" / "Movie" / "Movie.mkv"
            movie_file.parent.mkdir(parents=True)
            movie_file.touch()
            series_dir = Path(tmp) / "TV" / "Bluey"
            series_dir.mkdir(parents=True)

            settings = Settings(
                emby_url="http://emby:8096",
                emby_api_key="token",
                movie_libraries=["Filme"],
                tv_libraries=["Serien Kids"],
                dry_run=True,
            )
            service = MTDE(settings)
            movie = EmbyMovie("m1", "Movie", 2026, str(movie_file), [], 0, [], {})
            show = EmbyMovie("s1", "Bluey", 2018, str(series_dir), [], 0, [], {})
            service.emby.iter_movies = Mock(return_value=iter([movie]))
            service.emby.iter_series = Mock(return_value=iter([show]))

            movie_candidate = Candidate("m", "Movie Official Trailer 2026", 100, 1080, None)
            tv_candidate = Candidate("s", "Bluey 2018 Official Trailer", 100, 1080, None)
            service.downloader.search = Mock(return_value=[movie_candidate])
            service.tv_downloader.search = Mock(return_value=[tv_candidate])

            results = service.scan(download=True)

            self.assertEqual([result.library for result in results], ["Filme", "Serien Kids"])
            self.assertEqual([result.status for result in results], ["would_download", "would_download"])
            service.emby.iter_movies.assert_called_once_with("Filme")
            service.emby.iter_series.assert_called_once_with("Serien Kids")


if __name__ == "__main__":
    unittest.main()
