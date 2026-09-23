import unittest

from mtde.emby import EmbyClient


class EmbyFieldTests(unittest.TestCase):
    def test_movie_fields_include_production_year(self):
        self.assertIn("ProductionYear", EmbyClient._fields().split(","))


if __name__ == "__main__":
    unittest.main()
