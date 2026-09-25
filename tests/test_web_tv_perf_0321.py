import os
import tempfile
import unittest
from pathlib import Path

import yaml

from mtde.config import Settings
from mtde.service import MTDE
from mtde.web import create_app


class WebTVPerformance0321Tests(unittest.TestCase):
    def test_tv_settings_and_navigation_are_exposed(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.yml"
            config_path.write_text(
                yaml.safe_dump(
                    {
                        "EMBY_URL": "http://127.0.0.1:9",
                        "EMBY_API_KEY": "test",
                        "EMBY_TIMEOUT": 5,
                        "MOVIE_LIBRARIES": [{"name": "Filme", "genres_to_skip": []}],
                        "TV_LIBRARIES": [{"name": "Serien", "genres_to_skip": ["Reality"]}],
                        "SCHEDULE_TYPE": "disabled",
                        "NEW_ITEM_DETECTION": False,
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            previous = os.environ.get("MTDE_CONFIG")
            os.environ["MTDE_CONFIG"] = str(config_path)
            try:
                service = MTDE(Settings.from_yaml(config_path))
                app = create_app(service)
                app.testing = True
                client = app.test_client()

                settings_response = client.get("/api/config/settings")
                self.assertEqual(settings_response.status_code, 200)
                payload = settings_response.get_json()
                self.assertEqual(payload["libraries"]["tv"], [{"name": "Serien", "genres_to_skip": ["Reality"]}])

                index_response = client.get("/")
                self.assertEqual(index_response.status_code, 200)
                html = index_response.get_data(as_text=True)
                self.assertIn('data-page="tvshows"', html)
                self.assertIn("TV Show Libraries", html)
                self.assertNotIn('a[data-page="tvshows"], #page-tvshows { display:none !important; }', html)
            finally:
                if previous is None:
                    os.environ.pop("MTDE_CONFIG", None)
                else:
                    os.environ["MTDE_CONFIG"] = previous


if __name__ == "__main__":
    unittest.main()
