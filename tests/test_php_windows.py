import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import php_windows  # noqa: E402
from pe_builder import make_dll  # noqa: E402

NEW = make_dll(imports={"php8.dll": ["zend_a", "php_win32_ioutil_path_kind_w"]})
OLD = make_dll(imports={"php8.dll": ["zend_a"]})


class FirstLoadable(unittest.TestCase):
    def setUp(self):
        self.tree = Path(tempfile.mkdtemp())
        (self.tree / "php8.dll").write_bytes(make_dll(exports=["zend_a"]))

    def test_a_release_built_against_a_newer_patch_is_passed_over(self):
        builds = {"2.5.3": NEW, "2.5.2": OLD}
        found = php_windows.first_loadable(
            [("2.5.3", "u3"), ("2.5.2", "u2")], lambda release, url: builds[release], self.tree
        )
        self.assertEqual(found[:2], ("2.5.2", "u2"))

    def test_the_newest_is_taken_when_it_fits(self):
        found = php_windows.first_loadable(
            [("2.5.3", "u3"), ("2.5.2", "u2")], lambda release, url: OLD, self.tree
        )
        self.assertEqual(found[0], "2.5.3")

    def test_none_when_nothing_fits(self):
        found = php_windows.first_loadable(
            [("2.5.3", "u3")], lambda release, url: NEW, self.tree
        )
        self.assertIsNone(found)

    def test_older_releases_are_not_fetched_once_one_fits(self):
        fetched = []
        php_windows.first_loadable(
            [("2.5.3", "u3"), ("2.5.2", "u2")],
            lambda release, url: fetched.append(release) or OLD, self.tree,
        )
        self.assertEqual(fetched, ["2.5.3"])


if __name__ == "__main__":
    unittest.main()
