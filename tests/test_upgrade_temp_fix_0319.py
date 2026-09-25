from pathlib import Path
import unittest

from mtde import hardening
from mtde.upgrade_temp_fix import is_intentional_upgrade_temp, is_true_fragment_path


class UpgradeTempFix0319Tests(unittest.TestCase):
    def test_complete_upgrade_staging_file_is_intentional(self):
        self.assertTrue(
            is_intentional_upgrade_temp(
                Path('/tmp/.mtde-upgrade-392367.mkv'),
                Path('/tmp/.mtde-upgrade-392367'),
            )
        )

    def test_upgrade_fragment_is_never_intentional(self):
        self.assertFalse(
            is_intentional_upgrade_temp(
                Path('/tmp/.mtde-upgrade-392367.f616.mp4'),
                Path('/tmp/.mtde-upgrade-392367'),
            )
        )
        self.assertTrue(is_true_fragment_path('/tmp/.mtde-upgrade-392367.f616.mp4'))

    def test_part_and_ytdl_files_remain_fragments(self):
        self.assertTrue(is_true_fragment_path('/tmp/.mtde-upgrade-1.mkv.part'))
        self.assertTrue(is_true_fragment_path('/tmp/.mtde-upgrade-1.ytdl'))

    def test_upgrade_staging_leftover_still_counts_as_partial_outside_download_context(self):
        # The 0.3.19 fix must not weaken local trailer discovery/repair cleanup.
        self.assertTrue(hardening.is_partial_output_path('/tmp/.mtde-upgrade-392367.mkv'))

    def test_normal_output_stem_cannot_whitelist_upgrade_prefix(self):
        self.assertFalse(
            is_intentional_upgrade_temp(
                Path('/tmp/.mtde-upgrade-392367.mkv'),
                Path('/tmp/Movie (2003) - Trailer'),
            )
        )


if __name__ == '__main__':
    unittest.main()
