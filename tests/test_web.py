import unittest

from mtde.config import Settings
from mtde.web import create_app


class FakeService:
    def __init__(self):
        self.settings = Settings(
            emby_url="http://emby:8096",
            emby_api_key="token",
            movie_libraries=["Movies"],
            dry_run=True,
            preferred_language="german",
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
        self.assertIn("if (false && section === 'General')", html)

    def test_auth_compatibility_does_not_block_ui(self):
        response = self.app.get("/api/auth/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"authenticated": True, "setup_required": False},
        )

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

    def test_settings_are_emby_native_and_have_no_label_option(self):
        response = self.app.get("/api/config/settings")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        options = {item["key"]: item for item in payload["options"]}

        for key in (
            "DRY_RUN",
            "EMBY_URL",
            "EMBY_API_KEY",
            "EMBY_TIMEOUT",
            "CHECK_REMOTE_TRAILERS",
            "DOWNLOAD_TRAILERS",
            "PREFERRED_LANGUAGE",
            "TRAILER_RESOLUTION_MIN",
            "TRAILER_RESOLUTION_MAX",
            "UPGRADE_TRAILERS",
            "YT_DLP_CUSTOM_OPTIONS",
            "SCHEDULE_TYPE",
            "SCHEDULE_HOURS",
            "SCHEDULE_CRON",
            "NEW_ITEM_DETECTION",
            "NEW_ITEM_DELAY",
        ):
            self.assertIn(key, options)

        self.assertNotIn("USE_LABELS", options)
        self.assertEqual(payload["libraries"]["movie"][0]["name"], "Movies")


if __name__ == "__main__":
    unittest.main()
