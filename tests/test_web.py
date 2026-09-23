import unittest
from types import SimpleNamespace

from mtde.web import create_app


class FakeService:
    def __init__(self):
        self.settings = SimpleNamespace(
            dry_run=True,
            download_trailers=True,
            movie_libraries=["Movies"],
            skip_genres=[],
            emby_url="http://emby:8096",
            emby_api_key="token",
            preferred_language="german deutsch",
            search_results=8,
            max_trailer_duration=300,
            trailer_resolution_min=1080,
            trailer_resolution_max=2160,
            trailer_file_format="mkv",
            trailer_folder="trailers",
            refresh_emby_after_download=True,
        )

    def test_connection(self):
        return {"ServerName": "Test Emby", "Version": "4.10.0"}


class WebUiTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(FakeService()).test_client()

    def test_upstream_style_ui_is_restored_and_rebranded(self):
        response = self.app.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Dashboard", html)
        self.assertIn("General Statistics", html)
        self.assertIn("Recently Downloaded Trailers", html)
        self.assertIn("MTDE", html)
        self.assertIn("DRY RUN is active", html)
        self.assertIn("mlo-Tek/Missing-Trailer-Downloader-For-Emby", html)
        self.assertNotIn("netplexflix/Missing-Trailer-Downloader-For-Plex", html)

    def test_auth_compatibility_does_not_block_ui(self):
        response = self.app.get("/api/auth/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"authenticated": True, "setup_required": False})

    def test_status_exposes_dry_run(self):
        response = self.app.get("/api/status")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["status"], "idle")

    def test_server_endpoint_uses_emby(self):
        response = self.app.get("/api/server")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["name"], "Test Emby")


if __name__ == "__main__":
    unittest.main()
