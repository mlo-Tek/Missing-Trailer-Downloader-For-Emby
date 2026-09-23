import os
import tempfile
import time
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
        self.scan_calls = []

    def update_settings(self, settings):
        self.settings = settings

    def test_connection(self):
        return {"ServerName": "Test Emby", "Version": "4.10.0"}

    def scan(self, download=True, should_stop=None, progress=None):
        self.scan_calls.append({"download": download, "dry_run": self.settings.dry_run})
        if progress:
            progress("FAKE_SCAN          | Movies | test")
        if should_stop and should_stop():
            return []
        return []

    def serialize(self, results):
        return []


class WebUiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.tmp.name, "config.yml")
        with open(self.config_path, "w", encoding="utf-8") as f:
            f.write(
                'EMBY_URL: "http://emby:8096"\n'
                'EMBY_API_KEY: "token"\n'
                'MOVIE_LIBRARIES:\n'
                '  - "Movies"\n'
                'DRY_RUN: true\n'
            )
        self.old_config = os.environ.get("MTDE_CONFIG")
        os.environ["MTDE_CONFIG"] = self.config_path
        self.service = FakeService()
        self.app = create_app(self.service).test_client()

    def tearDown(self):
        if self.old_config is None:
            os.environ.pop("MTDE_CONFIG", None)
        else:
            os.environ["MTDE_CONFIG"] = self.old_config
        self.tmp.cleanup()

    def test_upstream_style_ui_is_restored_and_rebranded(self):
        response = self.app.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Dashboard", html)
        self.assertIn("General Statistics", html)
        self.assertIn("Recently Downloaded Trailers", html)
        self.assertIn("MTDE", html)
        self.assertIn("DRY RUN is active", html)
        self.assertIn("Dry-Run Scan starten", html)
        self.assertIn("Echten Scan starten", html)
        self.assertIn("Scan stoppen", html)
        self.assertIn("Logdatei", html)
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
        self.assertIn("scan_progress", payload)
        self.assertIn("stop_requested", payload["scan_progress"])
        self.assertIn("log_file", payload["scan_progress"])

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

    def test_dry_run_endpoint_switches_to_dry_and_starts_scan(self):
        response = self.app.post("/api/run/dry-run")
        self.assertEqual(response.status_code, 202)
        time.sleep(0.05)
        self.assertTrue(self.service.scan_calls)
        self.assertTrue(self.service.scan_calls[-1]["dry_run"])
        log = self.app.get("/api/log").get_json()["lines"]
        self.assertTrue(any("DRY-RUN SCAN REQUESTED FROM WEB UI" in line for line in log))
        self.assertTrue(any("Writing persistent scan log" in line for line in log))

    def test_real_run_endpoint_switches_to_real_and_starts_scan(self):
        response = self.app.post("/api/run/real-run")
        self.assertEqual(response.status_code, 202)
        time.sleep(0.05)
        self.assertTrue(self.service.scan_calls)
        self.assertFalse(self.service.scan_calls[-1]["dry_run"])
        log = self.app.get("/api/log").get_json()["lines"]
        self.assertTrue(any("REAL RUN REQUESTED FROM WEB UI" in line for line in log))

    def test_stop_endpoint_sets_stop_request_when_running(self):
        response = self.app.post("/api/run/stop")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertIn("running", payload)

    def test_log_files_endpoint_exists(self):
        response = self.app.get("/api/log/files")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("root", payload)
        self.assertIn("files", payload)


if __name__ == "__main__":
    unittest.main()
