import io
import sys
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import blueprints  # noqa: E402

BASE = "https://example.test/blueprints"


def zipped(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


class Starters(unittest.TestCase):
    """mixlab T205b: the starters published beside the gallery, compared with the tree."""

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "same").mkdir()
        (self.root / "same" / "index.html").write_bytes(b"hi")
        (self.root / "edited").mkdir()
        (self.root / "edited" / "index.php").write_bytes(b"new")
        (self.root / "grown").mkdir()
        (self.root / "grown" / "a.txt").write_bytes(b"a")
        (self.root / "rails-template.rb").write_bytes(b"gsub_file")

    def tearDown(self):
        self.temp.cleanup()

    def served(self, extra=None):
        files = {
            f"{BASE}/same-starter.zip": zipped({"same/": b"", "same/index.html": b"hi"}),
            f"{BASE}/edited-starter.zip": zipped({"edited/index.php": b"old"}),
            f"{BASE}/grown-starter.zip": zipped({"grown/a.txt": b"a", "grown/b.txt": b"b"}),
            f"{BASE}/rails-template.rb": b"gsub_file",
        }
        files.update(extra or {})
        return files.__getitem__

    def assets(self, *more):
        return ["same-starter.zip", "edited-starter.zip", "grown-starter.zip",
                "rails-template.rb", "x.toml", "x.toml.minisig", *more]

    def test_a_matching_starter_says_nothing(self):
        problems = blueprints.starters(self.root, BASE, self.assets(), self.served())
        self.assertFalse(any(p.startswith("same-") for p in problems), problems)
        self.assertFalse(any(p.startswith("rails-template.rb") for p in problems), problems)

    def test_a_changed_file_is_named(self):
        problems = blueprints.starters(self.root, BASE, self.assets(), self.served())
        self.assertTrue(any("edited" in p and "index.php" in p for p in problems), problems)

    def test_an_extra_entry_is_named(self):
        problems = blueprints.starters(self.root, BASE, self.assets(), self.served())
        self.assertTrue(any("grown" in p and "b.txt" in p for p in problems), problems)

    def test_a_starter_the_tree_no_longer_has_is_named(self):
        problems = blueprints.starters(
            self.root, BASE, self.assets("gone-starter.zip"), self.served())
        self.assertTrue(any("gone-starter.zip" in p for p in problems), problems)

    def test_a_changed_starter_file_is_named(self):
        served = self.served({f"{BASE}/rails-template.rb": b"other"})
        problems = blueprints.starters(self.root, BASE, self.assets(), served)
        self.assertTrue(any(p.startswith("rails-template.rb") for p in problems), problems)

    def test_a_starter_that_cannot_be_read_is_named(self):
        served = self.served()

        def missing(url):
            if url.endswith("same-starter.zip"):
                raise KeyError(url)
            return served(url)

        problems = blueprints.starters(self.root, BASE, self.assets(), missing)
        self.assertTrue(any("same-starter.zip" in p and "could not" in p for p in problems),
                        problems)


if __name__ == "__main__":
    unittest.main()
