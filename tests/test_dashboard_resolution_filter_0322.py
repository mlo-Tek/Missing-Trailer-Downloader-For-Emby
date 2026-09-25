import unittest

from mtde.dashboard_resolution_filter import DISPLAY_RESOLUTIONS, _filter_resolution_counts


class DashboardResolutionFilterTests(unittest.TestCase):
    def test_only_six_standard_tiers_are_exposed(self):
        raw = {
            "2160p": 61,
            "1440p": 7,
            "1080p": 889,
            "720p": 87,
            "480p": 82,
            "360p": 3,
            "1024p": 1,
            "1032p": 2,
            "960p": 62,
            "2076p": 4,
            "478p": 1,
            "800p": 9,
        }
        filtered = _filter_resolution_counts(raw)
        self.assertEqual(tuple(filtered.keys()), DISPLAY_RESOLUTIONS)
        self.assertEqual(filtered["2160p"], 61)
        self.assertEqual(filtered["1080p"], 889)
        self.assertNotIn("960p", filtered)
        self.assertNotIn("2076p", filtered)
        self.assertNotIn("478p", filtered)

    def test_missing_standard_tiers_remain_visible_as_zero(self):
        filtered = _filter_resolution_counts({"1080p": 12, "800p": 4})
        self.assertEqual(filtered, {
            "2160p": 0,
            "1440p": 0,
            "1080p": 12,
            "720p": 0,
            "480p": 0,
            "360p": 0,
        })


if __name__ == "__main__":
    unittest.main()
