import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import mysql  # noqa: E402


class ExactVersion(unittest.TestCase):
    def test_an_exact_version_of_a_packed_line_is_planned_as_itself(self):
        with mock.patch.object(mysql, "resolve", side_effect=lambda spec: spec):
            planned = mysql.legs("8.4.11")
        versions = {leg["version"] for legs in planned.values() for leg in legs}
        self.assertEqual(versions, {"8.4.11"})

    def test_an_exact_version_of_a_compiled_line_keeps_its_compiled_legs(self):
        with mock.patch.object(mysql, "resolve", side_effect=lambda spec: spec):
            planned = mysql.legs("5.7.44")
        self.assertTrue(planned["linux"])

    def test_an_unpacked_line_is_still_refused(self):
        with self.assertRaises(SystemExit):
            mysql.legs("6.0.11")


if __name__ == "__main__":
    unittest.main()
