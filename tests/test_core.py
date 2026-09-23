import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from mtde.config import PathMapping
from mtde.emby import EmbyClient
from mtde.trailer import Candidate, TrailerDownloader, find_local_trailers


class CoreTests(unittest.TestCase):
    def test_path_mapping(self):
        m = PathMapping("/data/media", "/media")
        self.assertEqual(m.map("/data/media/movies/300/300.mkv"), "/media/movies/300/300.mkv")
        self.assertEqual(m.map("/other/x.mkv"), "/other/x.mkv")

    def test_local_trailer_detection(self):
        with TemporaryDirectory() as tmp:
            movie = Path(tmp) / "Movie" / "Movie.mkv"
            movie.parent.mkdir()
            movie.touch()
            self.assertEqual(find_local_trailers(movie, "trailers"), [])
            trailers = movie.parent / "trailers"
            trailers.mkdir()
            f = trailers / "Trailer.mkv"
            f.touch()
            self.assertEqual(find_local_trailers(movie, "trailers"), [f])

    def test_candidate_scoring_prefers_official_language(self):
        d = TrailerDownloader("german deutsch", 1080, 2160, 300, 8, "mkv")
        good = Candidate("a", "Movie Official Trailer Deutsch 2026", 120, 1080, None)
        bad = Candidate("b", "Movie Trailer Reaction 2026", 120, 1080, None)
        self.assertEqual(d.choose([bad, good], "Movie", 2026), good)

    def test_emby_api_base_normalization(self):
        self.assertEqual(EmbyClient("http://emby:8096", "token").base_url, "http://emby:8096/emby")
        self.assertEqual(EmbyClient("http://emby:8096/emby", "token").base_url, "http://emby:8096/emby")

    def test_media_folder_library_resolution(self):
        client = EmbyClient("http://emby:8096", "token")
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"Items": [{"Name": "Movies", "Id": "123"}], "TotalRecordCount": 1}
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
        virtual_response.json.return_value = {"Items": [{"Name": "Movies", "ItemId": "456"}]}
        client.session.get = Mock(side_effect=[media_response, virtual_response])
        self.assertEqual(client.resolve_library("Movies"), "456")


if __name__ == "__main__":
    unittest.main()
