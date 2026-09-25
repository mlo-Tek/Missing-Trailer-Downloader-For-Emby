import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml

from mtde.config import Settings
from mtde.ui_tv_perf import _UICache, find_series_local_trailers


class UITVPerformance0321Tests(unittest.TestCase):
    def test_settings_parse_tv_libraries_and_genres(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "EMBY_URL": "http://emby:8096",
                        "EMBY_API_KEY": "test",
                        "MOVIE_LIBRARIES": [{"name": "Filme", "genres_to_skip": []}],
                        "TV_LIBRARIES": [
                            {"name": "Serien", "genres_to_skip": ["Reality"]},
                            {"name": "Serien Kids", "genres_to_skip": []},
                        ],
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            settings = Settings.from_yaml(path)
            self.assertEqual(settings.tv_libraries, ["Serien", "Serien Kids"])
            self.assertEqual(settings.genres_for_tv_library("Serien"), ["Reality"])
            self.assertEqual(settings.genres_for_tv_library("Serien Kids"), [])

    def test_series_local_trailers_support_root_and_trailers_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Show (2020)"
            trailers = root / "Trailers"
            trailers.mkdir(parents=True)
            root_trailer = root / "Show (2020)-trailer.mkv"
            folder_trailer = trailers / "Show Trailer.mp4"
            unrelated = root / "episode01.mkv"
            root_trailer.write_bytes(b"x")
            folder_trailer.write_bytes(b"x")
            unrelated.write_bytes(b"x")

            settings = SimpleNamespace(
                trailer_folder="trailers",
                map_path=lambda value: value,
            )
            service = SimpleNamespace(settings=settings)
            series = SimpleNamespace(path=str(root))
            found = find_series_local_trailers(service, series)

            self.assertEqual(set(found), {root_trailer, folder_trailer})

    def test_successfully_built_empty_cache_obeys_ttl(self):
        cache = _UICache.__new__(_UICache)
        cache.lock = threading.RLock()
        cache.items = {"movie": [], "tv": []}
        cache.saved_at = {"movie": time.time(), "tv": time.time()}
        cache.refreshing = {"movie": False, "tv": False}
        cache.errors = {"movie": "", "tv": ""}
        calls = []
        cache.request_refresh = lambda kind: calls.append(kind)

        items, refreshing, error = cache.snapshot("tv")
        self.assertEqual(items, [])
        self.assertFalse(refreshing)
        self.assertEqual(error, "")
        self.assertEqual(calls, [])

    def test_never_built_empty_cache_starts_background_refresh(self):
        cache = _UICache.__new__(_UICache)
        cache.lock = threading.RLock()
        cache.items = {"movie": [], "tv": []}
        cache.saved_at = {"movie": 0.0, "tv": 0.0}
        cache.refreshing = {"movie": False, "tv": False}
        cache.errors = {"movie": "", "tv": ""}
        calls = []
        cache.request_refresh = lambda kind: calls.append(kind)

        cache.snapshot("movie")
        self.assertEqual(calls, ["movie"])


if __name__ == "__main__":
    unittest.main()
